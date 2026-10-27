"""A /create-scope run in three calls. The server keeps the question list; Claude only sees a summary.

  start   per track: tag query + topic matching (our model) -> a draft run; returns counts and the
          topic additions by track
  plan    the IM's confirmed changes + the copy's ID column -> one Sheets batch (see sheet_plan.py):
          one tab per track
  record  merchant, opportunity (alias = the sheet ID) with its tracks, read-back check per tab,
          call-notes prompt, feedback link

A scope has one or more project tracks (e.g. "Ecommerce US" and "In-person payments UK"), each with
its own tags and its own tab in the scope sheet, named after the track. The default is one track,
whose tab keeps the master's name, Project Scope. The Introduction questions and the Suggested
additions go in the first tab only: there is one introduction per proposal.

The draft is a row in `generation`; its trace says what was asked and chosen. The IM's notes are
sent to the model but never stored, only the short topic labels.
"""

import re
import uuid
from collections import Counter
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from imcp import SERVICE_VERSION
from imcp.config import AppSettings, describe_config
from imcp.db import enums as E
from imcp.db.models import Generation, Merchant, Opportunity, Question
from imcp.bank.parse import ID_PATTERN
from imcp.scope.additions import NEW_ID, new_cells, new_ids
from imcp.scope.call_prompt import call_prompt
from imcp.scope.candidates import SUBSECTION_LABELS, Tags, bank_status, brief, counts, in_range, tag_matches
from imcp.scope.queue import add_candidates, sha256
from imcp.scope.sheet_plan import RowInfo, SheetPlanError, TrackEdit, out_of_order, plan_tracks
from imcp.scope.text import same_question
from imcp.scope.topics import match_topics

COMMAND = "create-scope"
FOUND_TAGS, FOUND_IM = "tags", "added by you"
DEFAULT_TRACK = "Project Scope"  # the master's tab name: a scope with one track keeps it
MAX_TRACKS = 6
BAD_TAB_CHARS = re.compile(r"[\[\]*?:/\\]")  # Sheets doesn't allow these in a tab title
TAG_NAMES = ("channels", "pillars", "categories", "platforms")


class RunError(Exception):
    def __init__(self, status: int, message: str, **extra):
        super().__init__(message)
        self.status, self.detail = status, {"error": message, **extra}


def clean_track_name(name: str) -> str:
    name = " ".join(name.split())
    if not name:
        raise ValueError("a track needs a name")
    if BAD_TAB_CHARS.search(name):
        raise ValueError(f"a track name can't contain any of [ ] * ? : / \\ (it becomes a tab title): {name!r}")
    return name


class TrackIn(BaseModel):
    name: str = Field(min_length=1, max_length=60, description="The track's name; it becomes the tab title")
    tags: Tags = Field(default_factory=Tags)

    _clean = field_validator("name")(clean_track_name)


class StartRequest(BaseModel):
    tags: Tags = Field(default_factory=Tags, description="The tags, when the scope has one track")
    tracks: list[TrackIn] = Field(default_factory=list, max_length=MAX_TRACKS,
                                  description="One per project track, each with its own tags. Empty: one track, "
                                              "'Project Scope', with `tags`.")
    context: str | None = Field(default=None, max_length=6000,
                                description="The IM's notes, for topic matching. Never stored.")
    merchant_name: str | None = Field(default=None, max_length=200,
                                      description="Only used to keep the name out of topics and reasons")

    @model_validator(mode="after")
    def _distinct_names(self) -> "StartRequest":
        names = [t.name.casefold() for t in self.tracks]
        if len(set(names)) != len(names):
            raise ValueError("track names must be different from each other")
        return self

    def track_list(self) -> list[TrackIn]:
        return list(self.tracks) or [TrackIn(name=DEFAULT_TRACK, tags=self.tags)]


class TrackChanges(BaseModel):
    """The IM's changes to one track (by its name)."""

    name: str = Field(min_length=1, max_length=60)
    remove_ids: list[str] = Field(default_factory=list)
    add_ids: list[str] = Field(default_factory=list)


class PlanRequest(BaseModel):
    tab_sheet_id: int = Field(description="The copy's Project Scope tab; it becomes the first track's tab")
    column_count: int = Field(ge=1)
    id_column: list[str]
    header_row: list[str] = Field(default_factory=list)
    basic_filter: dict | None = Field(default=None, description="The tab's basicFilter as read, if it has one")
    sheet_ids: list[int] = Field(default_factory=list,
                                 description="Every tab's sheetId in the copy, in tab order. Needed with several tracks.")
    remove_ids: list[str] = Field(default_factory=list, description="Dropped from every track that has them")
    add_ids: list[str] = Field(default_factory=list, description="Added to every track")
    tracks: list[TrackChanges] = Field(default_factory=list, description="Changes to one track only")


class TabRead(BaseModel):
    name: str = Field(min_length=1, max_length=100, description="The tab's title (the track name)")
    sheet_question_ids: list[str] = Field(description="Its column A, read back after the edit")


class RecordRequest(BaseModel):
    merchant_name: str = Field(min_length=1, max_length=200)
    sheet_id: str = Field(min_length=10, max_length=200)
    sheet_url: str = Field(max_length=500)
    sheet_question_ids: list[str] = Field(default_factory=list,
                                          description="Column A of the only tab, when the scope has one track")
    tabs: list[TabRead] = Field(default_factory=list, description="Column A of every track's tab")
    share_new_questions: bool = Field(default=False, description="The IM agreed to share new questions for review")
    call_prompt_priorities: list[Literal[1, 2, 3]] = Field(default_factory=lambda: [1],
                                                          description="Questions for the call-notes prompt; [] = all")


def normalise_name(name: str) -> str:
    return " ".join(name.casefold().split())


def active_ids(session: Session, ids: set[str]) -> set[str]:
    if not ids:
        return set()
    return set(session.scalars(select(Question.question_id).where(
        Question.question_id.in_(ids), Question.status == E.QuestionStatus.active)))


def feedback_link(settings: AppSettings, run_id: str) -> str | None:
    """The form link. If it contains {generation_id} (e.g. a prefilled Google Form link), it's filled in."""
    if not settings.FEEDBACK_FORM_URL:
        return None
    url = str(settings.FEEDBACK_FORM_URL)
    for placeholder in ("{generation_id}", "%7Bgeneration_id%7D", "%7bgeneration_id%7d"):
        url = url.replace(placeholder, run_id)
    return url


def row_info(session: Session, ids: set[str]) -> dict[str, RowInfo]:
    return {qid: RowInfo(E.Subsection(section), priority) for qid, section, priority in session.execute(
        select(Question.question_id, Question.subsection, Question.priority).where(Question.question_id.in_(ids)))}


def _run(session: Session, run_id: str, stages: tuple[str, ...]) -> Generation:
    try:
        gen = session.get(Generation, uuid.UUID(run_id))
    except ValueError:
        gen = None
    if gen is None or gen.command != COMMAND:
        raise RunError(404, f"There's no /create-scope run with ID {run_id}.")
    stage = gen.trace.get("stage")
    if stage not in stages:
        if stage == "recorded":
            raise RunError(409, "This run is already recorded. Start a new run to change the scope.")
        raise RunError(409, "Plan the sheet edit first (im_scope_sheet_plan), then record the run.")
    return gen


def _track_line(track: TrackIn) -> str:
    """A short description of the track for our model, e.g. 'In-person UK: channels IPP; pillars UC'."""
    parts = [f"{name} {', '.join(v)}" for name, v in track.tags.summary().items() if v != "all" and name in TAG_NAMES]
    return f"{track.name}: {'; '.join(parts)}" if parts else track.name


def start_run(session: Session, settings: AppSettings, model, req: StartRequest) -> dict:
    bank = bank_status(session, settings)
    if not bank["active_questions"]:
        raise RunError(409, "The question bank isn't loaded yet. Load it with im_bank_load first.")
    tracks = req.track_list()
    several = len(tracks) > 1

    trace_tracks, out_tracks, gap_items = [], [], []
    for index, track in enumerate(tracks):
        matches = tag_matches(session, track.tags)
        in_reach = in_range(session, track.tags)
        if index > 0:  # one introduction per proposal: its questions go in the first tab only
            matches = [q for q in matches if E.Subsection(q.subsection) is not E.Subsection.introduction]
            in_reach = [q for q in in_reach if E.Subsection(q.subsection) is not E.Subsection.introduction]
        matched = {q.question_id for q in matches}
        rest = {q.question_id: q for q in in_reach if q.question_id not in matched}
        topics = match_topics(model, req.context, [brief(q) for q in rest.values()], req.merchant_name,
                              selected=[brief(q) for q in matches], track=_track_line(track) if several else None)
        trace_tracks.append({
            "name": track.name,
            "tags": track.tags.summary(),
            "tags_input": track.tags.model_dump(mode="json"),
            "tag_matches": sorted(matched),
            "topic_matching": topics.to_dict(),
        })
        additions = []
        for a in topics.additions:
            q = brief(rest[a["id"]])
            additions.append({"id": q["id"], "question": q["question"], "priority": q["priority"],
                              "subsection": q["subsection"], "topic": a["topic"], "reason": a["reason"]})
        out_tracks.append({
            "name": track.name,
            "tags_used": track.tags.summary(),
            "tag_matches": counts(matches),
            "topic_matching": {"status": topics.status, "note": topics.note, "topics": topics.topics,
                               "uncovered_topics": topics.uncovered_topics, "additions": additions},
            "total_questions": len(matches) + len(additions),
        })
        # Topics no bank question covers are about the project, not one track: one drafted question each
        for g in topics.gap_questions:
            if not any(same_question(g["question"], h["question"]) for h in gap_items):
                gap_items.append(g)
    gaps = [{"id": new_id, **g} for new_id, g in zip(new_ids([], len(gap_items)), gap_items)]

    gen = Generation(
        command=COMMAND, tool_version=SERVICE_VERSION, flags=describe_config(settings)["flags"],
        trace={
            "stage": "draft",
            "tracks": trace_tracks,
            "gap_questions": gaps,
            "context_sha256": sha256(req.context) if req.context and req.context.strip() else None,
            "bank_load_run_id": bank["load_run_id"],
        },
    )
    session.add(gen)
    session.flush()
    return {
        "draft_id": str(gen.generation_id),
        "bank": bank,
        "tracks": out_tracks,
        # drafted for topics no bank question covers; added under 'Suggested additions' in the first tab
        "gap_questions": [{"id": g["id"], "topic": g["topic"], "question": g["question"]} for g in gaps],
        "total_questions": sum(t["total_questions"] for t in out_tracks),
        "review_queue_on": settings.FLAG_CANDIDATE_QUEUE,
    }


def _changes_by_track(req: PlanRequest, names: list[str]) -> dict[str, tuple[list[str], list[str]]]:
    """(remove_ids, add_ids) per track name: the changes for every track plus the track's own."""
    by_name = {name.casefold(): name for name in names}
    out = {name: (list(req.remove_ids), list(req.add_ids)) for name in names}
    for change in req.tracks:
        name = by_name.get(" ".join(change.name.split()).casefold())
        if name is None:
            raise RunError(422, f"There's no track called {change.name!r} in this run.", tracks=names)
        remove, add = out[name]
        out[name] = (remove + change.remove_ids, add + change.add_ids)
    return out


def plan_run(session: Session, run_id: str, req: PlanRequest) -> dict:
    gen = _run(session, run_id, ("draft", "planned"))
    trace = gen.trace
    tracks = trace["tracks"]
    names = [t["name"] for t in tracks]
    changes = _changes_by_track(req, names)
    if len(tracks) > 1 and req.tab_sheet_id not in req.sheet_ids:
        raise RunError(422, "With several tracks, pass sheet_ids: every tab's sheetId in the copy, in tab order, "
                            "including the Project Scope tab.")

    gap_ids = {g["id"] for g in trace.get("gap_questions", [])}
    removed_anywhere: set[str] = set()
    planned_tracks, edits = [], []
    for index, track in enumerate(tracks):
        remove_ids, add_ids = changes[track["name"]]
        selection: dict[str, str] = {qid: FOUND_TAGS for qid in track["tag_matches"]}
        for a in track["topic_matching"]["additions"]:
            selection.setdefault(a["id"], f"topic: {a['topic']}")
        removed = [qid for qid in dict.fromkeys(remove_ids)
                   if selection.pop(qid, None) is not None or (index == 0 and qid in gap_ids)]
        removed_anywhere.update(removed)
        add = [qid for qid in dict.fromkeys(add_ids) if qid not in selection]
        unknown = sorted(set(add) - active_ids(session, set(add)))
        if unknown:  # stop before the sheet is touched
            raise RunError(422, "These IDs aren't active questions in the bank.", ids=unknown, track=track["name"])
        for qid in add:
            selection[qid] = FOUND_IM
        no_longer_active = sorted(set(selection) - active_ids(session, set(selection)))  # e.g. bank reloaded since
        for qid in no_longer_active:
            selection.pop(qid)
        if not selection:
            raise RunError(422, f"No questions are left in the track {track['name']!r}.")
        planned_tracks.append({**track, "selection": [{"id": qid, "found_by": found} for qid, found in sorted(selection.items())],
                               "removed_ids": removed, "added_ids": add, "no_longer_active": no_longer_active})
        edits.append((track["name"], selection))

    gaps = [g for g in trace.get("gap_questions", []) if g["id"] not in removed_anywhere]
    additions = [{**new_cells(g["id"], {"question": g["question"], "type": g["type"], "subsection": "discovery"}),
                  "found_by": f"topic gap: {g['topic']}"} for g in gaps] if req.header_row else []
    info = row_info(session, {qid for _, selection in edits for qid in selection})
    track_edits = [TrackEdit(name, keep, additions if i == 0 and additions else None)
                   for i, (name, keep) in enumerate(edits)]
    try:
        plan = plan_tracks(req.tab_sheet_id, req.sheet_ids, req.column_count, req.id_column, track_edits, info,
                           req.header_row, basic_filter=req.basic_filter)
    except SheetPlanError as exc:
        raise RunError(422, str(exc)) from exc

    not_in_scope = [qid for qid in dict.fromkeys(req.remove_ids) if qid not in removed_anywhere]
    sheet_ids = {v.strip() for v in req.id_column[1:] if v.strip()}
    not_loaded = sorted(sheet_ids - active_ids(session, sheet_ids))
    for planned, tab in zip(planned_tracks, plan["tabs"]):
        planned["tab_sheet_id"] = tab["tab_sheet_id"]
        planned["missing_from_sheet"] = tab["missing_from_sheet"]
    gen.trace = {
        **trace,
        "stage": "planned",
        "tracks": planned_tracks,
        "not_in_scope": not_in_scope,
        "in_sheet_not_loaded": not_loaded,
        "gap_rows": [g["id"] for g in gaps] if additions else [],
    }
    first = plan["tabs"][0]
    return {
        "draft_id": run_id,
        "requests": plan["requests"],
        "filter": first["filter"],
        "tracks": [{"name": tab["name"], "tab_sheet_id": tab["tab_sheet_id"], "rows_kept": tab["rows_kept"],
                    "rows_deleted": tab["rows_deleted"], "sections": tab["sections"],
                    "removed_ids": planned["removed_ids"], "added_ids": planned["added_ids"],
                    "no_longer_active": planned["no_longer_active"], "missing_from_sheet": tab["missing_from_sheet"]}
                   for planned, tab in zip(planned_tracks, plan["tabs"])],
        "new_tabs": [{"name": tab["name"], "tab_sheet_id": tab["tab_sheet_id"]} for tab in plan["tabs"][1:]],
        "suggested_additions": first["suggested_additions"],
        "not_in_scope": not_in_scope,
        "in_sheet_not_loaded": not_loaded,
    }


def _reads_by_track(req: RecordRequest, tracks: list[dict]) -> dict[str, list[str]]:
    """Column A per track name, from `tabs` (or `sheet_question_ids` for a one-track scope)."""
    names = [t["name"] for t in tracks]
    if not req.tabs:
        if len(names) == 1 and req.sheet_question_ids:
            return {names[0]: req.sheet_question_ids}
        raise RunError(422, "Pass tabs: the title and column A of every track's tab.", tracks=names)
    by_name = {name.casefold(): name for name in names}
    reads: dict[str, list[str]] = {}
    for tab in req.tabs:
        name = by_name.get(" ".join(tab.name.split()).casefold())
        if name is not None:
            reads[name] = tab.sheet_question_ids
    missing = [name for name in names if name not in reads]
    if missing:
        raise RunError(422, "Read column A of every track's tab and pass them as tabs.", missing_tabs=missing)
    return reads


def _union_tags(tracks: list[Tags]) -> dict[str, list]:
    """The tags over all tracks. A track with no value for a tag ('all') makes the union 'all' (empty)."""
    out: dict[str, list] = {}
    for name in TAG_NAMES:
        values = [getattr(t, name) for t in tracks]
        out[name] = [] if any(not v for v in values) else sorted({x for v in values for x in v}, key=lambda e: e.value)
    return out


def record_run(session: Session, settings: AppSettings, run_id: str, req: RecordRequest) -> dict:
    gen = _run(session, run_id, ("planned", "recorded"))
    trace = gen.trace
    tracks = trace["tracks"]
    reads = _reads_by_track(req, tracks)

    recorded_tracks, all_in_sheet, by_track = [], [], []
    for index, track in enumerate(tracks):
        selected = {s["id"]: s["found_by"] for s in track["selection"]}
        column = reads[track["name"]]
        # Column A also holds the 'id' header and the section headings; only question IDs count.
        in_sheet = [v.strip() for v in column if ID_PATTERN.fullmatch(v.strip())]
        chosen_in_sheet = [q for q in in_sheet if q in selected]
        new_in_sheet = {v.strip() for v in column if NEW_ID.fullmatch(v.strip())}
        mismatches = {
            "missing_from_sheet": sorted(set(selected) - set(in_sheet)),
            "in_sheet_but_not_selected": sorted(set(in_sheet) - set(selected)),
            # right after the batch, the rows should be in section, priority, ID order
            "out_of_order": out_of_order(chosen_in_sheet, row_info(session, set(chosen_in_sheet))),
        }
        if index == 0:
            mismatches["suggested_additions_missing"] = [g for g in trace.get("gap_rows", []) if g not in new_in_sheet]
        recorded_tracks.append({**track, "sheet_question_ids": in_sheet, "mismatches": mismatches})
        all_in_sheet += in_sheet
        by_track.append((track["name"], selected, in_sheet, new_in_sheet if index == 0 else set()))
    new_in_first = by_track[0][3]

    normalised = normalise_name(req.merchant_name)
    merchant = session.scalar(select(Merchant).where(Merchant.normalized_name == normalised))
    if merchant is None:
        merchant = Merchant(name=req.merchant_name.strip(), normalized_name=normalised)
        session.add(merchant)
        session.flush()
    opportunity = session.scalar(select(Opportunity).where(Opportunity.alias == req.sheet_id))
    if opportunity is None:
        opportunity = Opportunity(merchant_id=merchant.merchant_id, alias=req.sheet_id)
        session.add(opportunity)
    tags = [Tags(**t["tags_input"]) for t in tracks]
    union = _union_tags(tags)
    opportunity.channels, opportunity.pillars = union["channels"], union["pillars"]
    opportunity.categories, opportunity.platforms = union["categories"], union["platforms"]
    opportunity.tracks = [{"name": t["name"], **tg.model_dump(mode="json")} for t, tg in zip(tracks, tags)]
    session.flush()

    queued = 0
    if settings.FLAG_CANDIDATE_QUEUE and req.share_new_questions:
        rows = [{"id": g["id"], "question": g["question"], "type": g["type"], "subsection": "discovery",
                 "raised_by": "im", "topic": g["topic"], "source_kind": "notes"}
                for g in trace.get("gap_questions", []) if g["id"] in new_in_first]
        queued = add_candidates(session, opportunity_id=opportunity.opportunity_id, sheet_id=req.sheet_id, rows=rows,
                                command=COMMAND, model=tracks[0]["topic_matching"].get("model"),
                                material=[{"kind": "notes", "sha256": trace.get("context_sha256")}])

    mismatches = {t["name"]: t["mismatches"] for t in recorded_tracks}
    gen.opportunity_id, gen.output_ref = opportunity.opportunity_id, req.sheet_url
    gen.trace = {**trace, "stage": "recorded", "tracks": recorded_tracks, "mismatches": mismatches,
                 "queued": queued, "share_consent": req.share_new_questions}
    session.flush()

    by_id = {q.question_id: q for q in session.scalars(select(Question).where(Question.question_id.in_(set(all_in_sheet))))}
    summaries, found_total, section_total = [], Counter(), Counter()
    for name, selected, in_sheet, _ in by_track:
        kept = [by_id[qid] for qid in dict.fromkeys(in_sheet) if qid in by_id and qid in selected]
        found_by = Counter(selected[q.question_id].split(":")[0].strip() for q in kept)
        by_subsection = Counter(SUBSECTION_LABELS[E.Subsection(q.subsection)] for q in kept)
        found_total.update(found_by)
        section_total.update(by_subsection)
        summaries.append({"name": name, "questions": len(in_sheet), "found_by": dict(found_by),
                          "by_subsection": {label: by_subsection[label] for label in SUBSECTION_LABELS.values()
                                            if by_subsection[label]},
                          "mismatches": mismatches[name]})
    new_questions = [{"id": g["id"], "question": g["question"]} for g in trace.get("gap_questions", [])
                     if g["id"] in new_in_first]
    questions_by_track = [(name, [by_id[i] for i in in_sheet if i in by_id]) for name, _, in_sheet, _ in by_track]
    return {
        "ok": not any(any(m.values()) for m in mismatches.values()),
        "merchant": merchant.name,
        "sheet_url": req.sheet_url,
        "questions": len(all_in_sheet),
        "found_by": dict(found_total),
        "by_subsection": {label: section_total[label] for label in SUBSECTION_LABELS.values() if section_total[label]},
        "tracks": summaries,
        "suggested_additions": len(new_questions),
        "queue": {"on": settings.FLAG_CANDIDATE_QUEUE, "shared": req.share_new_questions, "sent": queued},
        "mismatches": mismatches,
        "call_prompt": call_prompt(questions_by_track[0][1], new_questions, tuple(req.call_prompt_priorities),
                                   tracks=questions_by_track),
        "feedback_url": feedback_link(settings, run_id),
    }
