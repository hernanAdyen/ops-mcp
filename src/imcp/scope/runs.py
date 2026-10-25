"""A /create-scope run in three calls. The server keeps the question list; Claude only sees a summary.

  start   tag query + topic matching (our model) -> a draft run; returns counts and the topic additions
  plan    the IM's confirmed changes + the copy's ID column -> one Sheets batch (see sheet_plan.py)
  record  merchant, opportunity (alias = the sheet ID), read-back check, feedback link

The draft is a row in `generation`; its trace says what was asked and chosen. The IM's notes are
sent to the model but never stored, only the short topic labels.
"""

import uuid
from typing import Literal
from collections import Counter

from pydantic import BaseModel, Field
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
from imcp.scope.sheet_plan import RowInfo, SheetPlanError, out_of_order, plan_sheet_edit
from imcp.scope.topics import match_topics

COMMAND = "create-scope"
FOUND_TAGS, FOUND_IM = "tags", "added by you"


class RunError(Exception):
    def __init__(self, status: int, message: str, **extra):
        super().__init__(message)
        self.status, self.detail = status, {"error": message, **extra}


class StartRequest(BaseModel):
    tags: Tags = Field(default_factory=Tags)
    context: str | None = Field(default=None, max_length=6000,
                                description="The IM's notes, for topic matching. Never stored.")
    merchant_name: str | None = Field(default=None, max_length=200,
                                      description="Only used to keep the name out of topics and reasons")


class PlanRequest(BaseModel):
    tab_sheet_id: int
    column_count: int = Field(ge=1)
    id_column: list[str]
    header_row: list[str] = Field(default_factory=list)
    basic_filter: dict | None = Field(default=None, description="The tab's basicFilter as read, if it has one")
    remove_ids: list[str] = Field(default_factory=list)
    add_ids: list[str] = Field(default_factory=list)


class RecordRequest(BaseModel):
    merchant_name: str = Field(min_length=1, max_length=200)
    sheet_id: str = Field(min_length=10, max_length=200)
    sheet_url: str = Field(max_length=500)
    sheet_question_ids: list[str]
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


def start_run(session: Session, settings: AppSettings, model, req: StartRequest) -> dict:
    bank = bank_status(session, settings)
    if not bank["active_questions"]:
        raise RunError(409, "The question bank isn't loaded yet. Load it with im_bank_load first.")
    matches = tag_matches(session, req.tags)
    matched = {q.question_id for q in matches}
    rest = {q.question_id: q for q in in_range(session, req.tags) if q.question_id not in matched}
    topics = match_topics(model, req.context, [brief(q) for q in rest.values()], req.merchant_name,
                          selected=[brief(q) for q in matches])

    # Topics no bank question covers get a drafted question, under 'Suggested additions' in the sheet
    gaps = [{"id": new_id, **g} for new_id, g in zip(new_ids([], len(topics.gap_questions)), topics.gap_questions)]
    gen = Generation(
        command=COMMAND, tool_version=SERVICE_VERSION, flags=describe_config(settings)["flags"],
        trace={
            "stage": "draft",
            "tags": req.tags.summary(),
            "tags_input": req.tags.model_dump(mode="json"),
            "tag_matches": sorted(matched),
            "topic_matching": topics.to_dict(),
            "gap_questions": gaps,
            "context_sha256": sha256(req.context) if req.context and req.context.strip() else None,
            "bank_load_run_id": bank["load_run_id"],
        },
    )
    session.add(gen)
    session.flush()

    additions = []
    for a in topics.additions:
        q = brief(rest[a["id"]])
        additions.append({"id": q["id"], "question": q["question"], "priority": q["priority"],
                          "subsection": q["subsection"], "topic": a["topic"], "reason": a["reason"]})
    return {
        "draft_id": str(gen.generation_id),
        "bank": bank,
        "tags_used": req.tags.summary(),
        "tag_matches": counts(matches),
        "topic_matching": {
            "status": topics.status,
            "note": topics.note,
            "topics": topics.topics,
            "uncovered_topics": topics.uncovered_topics,
            "additions": additions,
            # drafted for topics no bank question covers; added under 'Suggested additions' for review
            "gap_questions": [{"id": g["id"], "topic": g["topic"], "question": g["question"]} for g in gaps],
        },
        "total_questions": len(matches) + len(additions),
        "review_queue_on": settings.FLAG_CANDIDATE_QUEUE,
    }


def plan_run(session: Session, run_id: str, req: PlanRequest) -> dict:
    gen = _run(session, run_id, ("draft", "planned"))
    trace = gen.trace

    selection: dict[str, str] = {qid: FOUND_TAGS for qid in trace["tag_matches"]}
    for a in trace["topic_matching"]["additions"]:
        selection.setdefault(a["id"], f"topic: {a['topic']}")
    gap_ids = {g["id"] for g in trace.get("gap_questions", [])}
    removed = [qid for qid in dict.fromkeys(req.remove_ids) if selection.pop(qid, None) is not None or qid in gap_ids]
    not_in_scope = [qid for qid in dict.fromkeys(req.remove_ids) if qid not in removed]
    gaps = [g for g in trace.get("gap_questions", []) if g["id"] not in set(removed)]
    add = [qid for qid in dict.fromkeys(req.add_ids) if qid not in selection]
    unknown = sorted(set(add) - active_ids(session, set(add)))
    if unknown:  # stop before the sheet is touched
        raise RunError(422, "These IDs aren't active questions in the bank.", ids=unknown)
    for qid in add:
        selection[qid] = FOUND_IM
    no_longer_active = sorted(set(selection) - active_ids(session, set(selection)))  # e.g. bank reloaded since
    for qid in no_longer_active:
        selection.pop(qid)
    if not selection:
        raise RunError(422, "No questions are left in this scope.")

    info = row_info(session, set(selection))
    additions = [{**new_cells(g["id"], {"question": g["question"], "type": g["type"], "subsection": "discovery"}),
                  "found_by": f"topic gap: {g['topic']}"} for g in gaps] if req.header_row else []
    try:
        plan = plan_sheet_edit(req.tab_sheet_id, req.column_count, req.id_column, selection, info, req.header_row,
                               basic_filter=req.basic_filter, additions=additions)
    except SheetPlanError as exc:
        raise RunError(422, str(exc)) from exc
    sheet_ids = {v.strip() for v in req.id_column[1:] if v.strip()}
    not_loaded = sorted(sheet_ids - active_ids(session, sheet_ids))
    gen.trace = {
        **trace,
        "stage": "planned",
        "selection": [{"id": qid, "found_by": found} for qid, found in sorted(selection.items())],
        "removed_ids": removed,
        "added_ids": add,
        "no_longer_active": no_longer_active,
        "missing_from_sheet": plan["missing_from_sheet"],
        "in_sheet_not_loaded": not_loaded,
        "gap_rows": [g["id"] for g in gaps] if additions else [],
    }
    return {
        "draft_id": run_id,
        "requests": plan["requests"],
        "filter": plan["filter"],
        "suggested_additions": plan["suggested_additions"],
        "rows_kept": plan["rows_kept"],
        "rows_deleted": plan["rows_deleted"],
        "sections": plan["sections"],
        "removed_ids": removed,
        "not_in_scope": not_in_scope,
        "added_ids": add,
        "no_longer_active": no_longer_active,
        "missing_from_sheet": plan["missing_from_sheet"],
        "in_sheet_not_loaded": not_loaded,
    }


def record_run(session: Session, settings: AppSettings, run_id: str, req: RecordRequest) -> dict:
    gen = _run(session, run_id, ("planned", "recorded"))
    trace = gen.trace
    selected = {s["id"]: s["found_by"] for s in trace["selection"]}
    # Column A also holds the 'id' header and the section headings; only question IDs count.
    in_sheet = [v.strip() for v in req.sheet_question_ids if ID_PATTERN.fullmatch(v.strip())]
    chosen_in_sheet = [q for q in in_sheet if q in selected]
    new_in_sheet = {v.strip() for v in req.sheet_question_ids if NEW_ID.fullmatch(v.strip())}
    mismatches = {
        "missing_from_sheet": sorted(set(selected) - set(in_sheet)),
        "in_sheet_but_not_selected": sorted(set(in_sheet) - set(selected)),
        # right after the batch, the rows should be in section, priority, ID order
        "out_of_order": out_of_order(chosen_in_sheet, row_info(session, set(chosen_in_sheet))),
        "suggested_additions_missing": [g for g in trace.get("gap_rows", []) if g not in new_in_sheet],
    }

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
    tags = Tags(**trace.get("tags_input", {}))
    opportunity.channels, opportunity.pillars = tags.channels, tags.pillars
    opportunity.categories, opportunity.platforms = tags.categories, tags.platforms
    session.flush()

    queued = 0
    if settings.FLAG_CANDIDATE_QUEUE and req.share_new_questions:
        rows = [{"id": g["id"], "question": g["question"], "type": g["type"], "subsection": "discovery",
                 "raised_by": "im", "topic": g["topic"], "source_kind": "notes"}
                for g in trace.get("gap_questions", []) if g["id"] in new_in_sheet]
        queued = add_candidates(session, opportunity_id=opportunity.opportunity_id, sheet_id=req.sheet_id, rows=rows,
                                command=COMMAND, model=trace["topic_matching"].get("model"),
                                material=[{"kind": "notes", "sha256": trace.get("context_sha256")}])

    gen.opportunity_id, gen.output_ref = opportunity.opportunity_id, req.sheet_url
    gen.trace = {**trace, "stage": "recorded", "sheet_question_ids": in_sheet, "mismatches": mismatches,
                 "queued": queued, "share_consent": req.share_new_questions}
    session.flush()

    by_id = {q.question_id: q for q in session.scalars(select(Question).where(Question.question_id.in_(set(in_sheet))))}
    kept = [q for qid, q in by_id.items() if qid in selected]
    found_by = Counter(selected[q.question_id].split(":")[0].strip() for q in kept)
    by_subsection = Counter(SUBSECTION_LABELS[E.Subsection(q.subsection)] for q in kept)
    return {
        "ok": not any(mismatches.values()),
        "merchant": merchant.name,
        "sheet_url": req.sheet_url,
        "questions": len(in_sheet),
        "found_by": dict(found_by),
        "by_subsection": {label: by_subsection[label] for label in SUBSECTION_LABELS.values() if by_subsection[label]},
        "suggested_additions": len([g for g in trace.get("gap_rows", []) if g in new_in_sheet]),
        "queue": {"on": settings.FLAG_CANDIDATE_QUEUE, "shared": req.share_new_questions, "sent": queued},
        "mismatches": mismatches,
        "call_prompt": call_prompt([by_id[i] for i in in_sheet if i in by_id],
                                   [{"id": g["id"], "question": g["question"]} for g in trace.get("gap_questions", [])
                                    if g["id"] in new_in_sheet],
                                   tuple(req.call_prompt_priorities)),
        "feedback_url": feedback_link(settings, run_id),
    }
