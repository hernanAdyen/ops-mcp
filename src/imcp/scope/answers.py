"""/ops-answer-scope in two calls. The IM reviews the result in their own sheet.

  start   one track's tab as read + the IM's merchant material -> our model finds answers and new
          questions -> one exact Sheets batch that writes them into that tab (a scope with several
          tracks has a tab per track: the skill runs this once per tab)
  record  read-back check, the deal (opportunity), the review queue (behind FLAG_CANDIDATE_QUEUE),
          the open priority-1 questions for the next call, and the feedback link

The material is sent to our model for this run only. It is never stored or logged, and neither are
the answers: the run's trace keeps question IDs, counts and a hash of each piece of material.

The scope is built over several meetings. Each piece of material can carry its date, which goes into
the sheet's `source` column; a finding that agrees with the IM's own answer confirms it and a
different one marks the row `conflict`; every change is appended to the sheet's Scope log tab; and
material already used on the same tab (same text, by its hash) is skipped, or refused when there is
nothing else.
"""

import re

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from imcp import SERVICE_VERSION
from imcp.bank.parse import ID_PATTERN
from imcp.config import AppSettings, describe_config
from imcp.db import enums as E
from imcp.db.models import Generation, Merchant, Opportunity, Question
from imcp.scope.additions import NEW_ID, bank_cells, label_needed, new_cells, new_ids
from imcp.scope.answers_plan import ADDED_FROM_BANK, NEW_QUESTION, REVIEW_COLUMNS, SheetRead, plan_answers, plan_scope_log
from imcp.scope.candidates import bank_status
from imcp.scope.extract import MAX_MATERIAL_CHARS, Material, extract_answers
from imcp.scope.queue import add_candidates, observe_im_review, sha256
from imcp.scope.runs import DEFAULT_TRACK, RunError, feedback_link, normalise_name

COMMAND = "ops-answer-scope"
OLD_COMMANDS = ("source-scope-answers",)  # the command's name before 2026-10-27; earlier runs are recorded under it
FOUND_IN_MATERIAL, FOUND_NEW = "answered in material", "new question"
MAX_OPEN_LISTED = 10


DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


class MaterialIn(BaseModel):
    label: str = Field(min_length=1, max_length=80, description="e.g. 'Call summary'")
    kind: Literal["transcript", "summary", "notes", "email", "document"] = "notes"
    date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$",
                             description="The day of the call, email or document (YYYY-MM-DD), if known")
    text: str = Field(min_length=1, max_length=MAX_MATERIAL_CHARS)

    def source(self) -> str:
        """What the sheet's source column says: the label with the date, e.g. 'Call summary, 2026-10-24'."""
        label = self.label.strip()
        return f"{label}, {self.date}" if self.date and self.date not in label else label


class TabIn(BaseModel):
    sheet_id: int
    title: str = Field(max_length=100)


class NewRowIn(BaseModel):
    id: str = Field(max_length=20)
    question: str = Field(default="", max_length=2000)


class AnswersStartRequest(BaseModel):
    sheet_id: str = Field(min_length=10, max_length=200)
    merchant_name: str | None = Field(default=None, max_length=200)
    tab_title: str = Field(default=DEFAULT_TRACK, min_length=1, max_length=100,
                           description="The tab being filled: the track's name")
    tab_sheet_id: int
    column_count: int = Field(ge=1)
    row_count: int = Field(ge=1)
    header_row: list[str]
    id_column: list[str]
    columns: dict[str, list[str]] = Field(default_factory=dict)
    new_rows: list[NewRowIn] = Field(default_factory=list)
    basic_filter: dict | None = None
    sheet_tabs: list[TabIn] | None = Field(default=None, description="Every tab of the sheet (sheetId, title), "
                                           "so the Scope log tab can be found or added")
    material: list[MaterialIn] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def _material_size(self) -> "AnswersStartRequest":
        total = sum(len(m.text) for m in self.material)
        if total > MAX_MATERIAL_CHARS:
            raise ValueError(f"the material is {total} characters; the limit is {MAX_MATERIAL_CHARS}. Split it into runs.")
        return self


class AnswersRecordRequest(BaseModel):
    sheet_url: str = Field(max_length=500)
    id_column: list[str]
    share_new_questions: bool = Field(default=False, description="The IM agreed to share new questions for review")


def _sheet_read(req: AnswersStartRequest) -> SheetRead:
    """Checks what the skill read, and returns it below the header row."""
    tab = req.tab_title.strip()
    if not req.id_column or req.id_column[0].strip().lower() not in ("id", "question_id"):
        raise RunError(422, f"id_column must be column A of the {tab!r} tab, starting with its 'id' header.")
    names = [h.strip().lower() for h in req.header_row]
    if not names or names[0] not in ("id", "question_id"):
        raise RunError(422, f"header_row must be row 1 of the {tab!r} tab, as read.")
    if "answer" not in names:
        raise RunError(422, "This tab has no 'answer' column, so there's nowhere to write answers.")
    columns: dict[str, list[str]] = {}
    for key, values in req.columns.items():
        name = key.strip().lower()
        first = values[0].strip().lower() if values else ""
        if first != name:
            raise RunError(422, f"The column passed as '{key}' starts with '{values[0] if values else ''}'. "
                                f"Pass the column whose header is '{name}', as read, starting with its header.")
        columns[name] = values[1:]
    needed = ["answer"] + [c for c in REVIEW_COLUMNS if c in names]
    missing = [c for c in needed if c not in columns]
    if missing:
        raise RunError(422, f"Read and pass these columns too: {', '.join(missing)} (each starting with its header).")
    return SheetRead(tab_sheet_id=req.tab_sheet_id, column_count=req.column_count, row_count=req.row_count,
                     header=req.header_row, ids=[v.strip() for v in req.id_column[1:]], columns=columns,
                     basic_filter=req.basic_filter)


def _opportunity(session: Session, sheet_id: str) -> tuple[Opportunity | None, Merchant | None]:
    opp = session.scalar(select(Opportunity).where(Opportunity.alias == sheet_id))
    return opp, (session.get(Merchant, opp.merchant_id) if opp else None)


def _earlier_runs(session: Session, sheet_id: str, tab_sheet_id: int) -> list[Generation]:
    """Earlier runs on the same tab (runs from before tabs were named count for every tab)."""
    runs = session.scalars(select(Generation).where(
        Generation.command.in_((COMMAND, *OLD_COMMANDS)), Generation.trace["sheet_id"].astext == sheet_id))
    return [g for g in runs if g.trace.get("tab_sheet_id", tab_sheet_id) == tab_sheet_id]


def _already_used(earlier: list[Generation]) -> dict[str, str]:
    """Hash of each piece of material used by a recorded run on this tab -> the day it was recorded."""
    used: dict[str, str] = {}
    for g in earlier:
        if g.trace.get("stage") != "recorded":
            continue  # a run whose batch may never have been sent doesn't count
        day = (g.trace.get("recorded_at") or "")[:10]
        for m in g.trace.get("material", []):
            if m.get("sha256"):
                used.setdefault(m["sha256"], day)
    return used


def start_answers(session: Session, settings: AppSettings, model, req: AnswersStartRequest) -> dict:
    if not bank_status(session, settings)["active_questions"]:
        raise RunError(409, "The question bank isn't loaded yet. Load it with im_bank_load first.")
    sheet = _sheet_read(req)
    opp, merchant = _opportunity(session, req.sheet_id)
    merchant_name = merchant.name if merchant else (req.merchant_name or "").strip()
    if not merchant_name:
        raise RunError(422, "This sheet wasn't made by /ops-create-scope, so I don't know the merchant. Pass merchant_name.")

    bank = {q.question_id: q for q in session.scalars(
        select(Question).where(Question.status == E.QuestionStatus.active).order_by(Question.subsection, Question.question_id))}
    sheet_ids = list(dict.fromkeys(i for i in sheet.ids if i in bank))
    sheet_questions = [bank[i] for i in sheet_ids]
    others = [q for qid, q in bank.items() if qid not in set(sheet_ids)]
    not_loaded = sorted({i for i in sheet.ids if ID_PATTERN.fullmatch(i) and i not in bank})

    # What the IM did with new questions queued earlier (kept, edited, confirmed, rejected, removed)
    status_col = sheet.values("status") if "status" in sheet.columns else [""] * len(sheet.ids)
    wording = {r.id.strip(): r.question for r in req.new_rows}
    sheet_new = {i: {"question": wording.get(i, ""), "status": status_col[n]}
                 for n, i in enumerate(sheet.ids) if NEW_ID.fullmatch(i)}
    im_review = observe_im_review(session, opp.opportunity_id, sheet_new, merchant_name) \
        if opp is not None and settings.FLAG_CANDIDATE_QUEUE else {}

    earlier = _earlier_runs(session, req.sheet_id, req.tab_sheet_id)
    used = _already_used(earlier)
    repeats = [m for m in req.material if sha256(m.text) in used]
    if len(repeats) == len(req.material):
        days = sorted({used[sha256(m.text)] for m in repeats if used[sha256(m.text)]})
        raise RunError(409, f"This material was already used for the {req.tab_title.strip()!r} tab"
                            + (f" on {', '.join(days)}" if days else "") + ": "
                            + ", ".join(m.label.strip() for m in repeats)
                            + ". Nothing was written. Pass material that is new, or run it on another tab.")
    fresh = [m for m in req.material if sha256(m.text) not in used]
    materials = [Material(m.label.strip(), m.kind, m.text) for m in fresh]
    source_of = {m.label.strip().casefold(): m.source() for m in fresh}
    extraction = extract_answers(model, materials, sheet_questions, others,
                                 [r.question for r in req.new_rows if r.question.strip()], merchant_name,
                                 sanitize=settings.FLAG_SANITIZE, track=req.tab_title.strip())
    if extraction.status != "ok":
        raise RunError(503, f"{extraction.note} Nothing was written to the sheet.")

    for a in extraction.answers + extraction.new_questions:  # the sheet shows the source with its date
        a["source"] = source_of.get(a["source"].casefold(), a["source"])
    in_sheet = [a for a in extraction.answers if a["in_sheet"]]
    from_bank = [a for a in extraction.answers if not a["in_sheet"]]
    kind_of = {m.source().casefold(): m.kind for m in fresh}
    additions: list[dict] = []
    for a in from_bank:
        additions.append({**bank_cells(bank[a["id"]]), "answer": a["answer"], "found_by": FOUND_IN_MATERIAL,
                          "source": a["source"], "confidence": a["confidence"], "status": "suggested",
                          "ai_note": "; ".join(x for x in (a["evidence"], a["problem"]) if x)})
    ids_new = new_ids(sheet.ids, len(extraction.new_questions))
    new_rows = []
    for new_id, item in zip(ids_new, extraction.new_questions):
        note = "; ".join(x for x in (item["reason"], f"closest bank question: {item['closest_id']}"
                                     if item["closest_id"] else None) if x)
        additions.append({**new_cells(new_id, item), "answer": item["answer"], "found_by": FOUND_NEW,
                          "source": item["source"], "status": "suggested", "ai_note": note})
        new_rows.append({"id": new_id, **item, "source_kind": kind_of.get(item["source"].casefold(), materials[0].kind)})

    added_before = {qid for g in earlier for qid in g.trace.get("added_bank_ids", [])}
    plan = plan_answers(sheet, in_sheet, additions, label_needed(sheet.ids, added_before))
    merge = plan["merge"]
    open_p1 = [q.question_id for q in sheet_questions if q.priority == 1 and q.question_id not in merge.answered]

    text = {q.question_id: q.text for q in bank.values()}
    log_entries = list(merge.log)
    log_entries += [{"id": a["id"], "change": ADDED_FROM_BANK, "answer": a["answer"], "source": a["source"],
                     "confidence": a["confidence"], "note": a["ai_note"]} for a in additions if a["id"] in bank]
    log_entries += [{"id": r["id"], "change": NEW_QUESTION, "answer": r["answer"] or "", "source": r["source"],
                     "confidence": "", "note": r["question"]} for r in new_rows]
    log = plan_scope_log([(t.sheet_id, t.title) for t in req.sheet_tabs] if req.sheet_tabs is not None else None,
                         req.tab_title.strip(), log_entries, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                         text)

    queue_on = settings.FLAG_CANDIDATE_QUEUE
    keep = ("id", "type", "options", "subsection", "raised_by", "closest_id", "source_kind")
    gen = Generation(
        command=COMMAND, tool_version=SERVICE_VERSION, flags=describe_config(settings)["flags"],
        opportunity_id=opp.opportunity_id if opp else None,
        trace={
            "stage": "planned",
            "sheet_id": req.sheet_id,
            "tab_title": req.tab_title.strip(),
            "tab_sheet_id": req.tab_sheet_id,
            "merchant_name": None if opp else merchant_name,  # only needed to create the deal at record
            "material": [{"kind": m.kind, "chars": len(m.text), "sha256": sha256(m.text)} for m in materials],
            "already_used": len(repeats),
            "extraction": extraction.summary(),
            "filled_ids": merge.filled,
            "agreed_ids": merge.agreed,
            "confirmed_ids": merge.confirmed,
            "conflict_ids": [c["id"] for c in merge.conflicts],
            "scope_log": {"tab_added": log["tab_added"], "rows": log["rows"], "sheet_id": log["sheet_id"]},
            "skipped_rejected_ids": merge.skipped_rejected,
            "added_bank_ids": [a["id"] for a in from_bank],
            # The wording is kept only when it may go to the queue; it is generic, never the IM's material.
            "new_rows": [{k: r[k] for k in keep} | ({"question": r["question"], "reason": r["reason"]} if queue_on else {})
                         for r in new_rows],
            "columns_added": plan["columns_added"],
            "open_p1_ids": open_p1,
            "im_review": im_review,
            "not_loaded": not_loaded,
        },
    )
    session.add(gen)
    session.flush()
    return {
        "draft_id": str(gen.generation_id),
        "requests": plan["requests"] + log["requests"],
        "summary": {
            "tab": req.tab_title.strip(),
            "model": extraction.model,
            "already_used": [m.label.strip() for m in repeats],  # skipped: used on this tab before
            "filled": len(merge.filled),
            "agreed_with_yours": len(merge.agreed),
            "confirmed_yours": len(merge.confirmed),
            "conflicts": [{"id": c["id"], "question": text[c["id"]], "yours": c["yours"], "found": c["found"],
                           "source": c["source"]} for c in merge.conflicts],
            "scope_log": {"tab_added": log["tab_added"], "rows": log["rows"],
                          "note": None if req.sheet_tabs is not None else "no Scope log: the sheet's tabs weren't passed"},
            "not_rewritten_rejected": len(merge.skipped_rejected),
            "added_from_bank": [{"id": a["id"], "question": text[a["id"]], "answer": a["answer"]} for a in from_bank],
            "new_questions": [{"id": r["id"], "question": r["question"], "answer": r["answer"]} for r in new_rows],
            "open_priority_1": len(open_p1),
            "dropped": extraction.dropped,
            "im_review_seen": im_review,
            "review_columns_added": plan["columns_added"],
            "not_loaded": not_loaded,
            "review_queue_on": queue_on,
        },
    }


def record_answers(session: Session, settings: AppSettings, run_id: str, req: AnswersRecordRequest) -> dict:
    gen = _get_run(session, run_id)
    trace = gen.trace
    if not req.id_column or req.id_column[0].strip().lower() not in ("id", "question_id"):
        raise RunError(422, f"id_column must be column A of the {trace.get('tab_title', DEFAULT_TRACK)!r} tab, "
                            "starting with its 'id' header.")
    present = {v.strip() for v in req.id_column[1:]}
    expected = trace["added_bank_ids"] + [r["id"] for r in trace["new_rows"]]
    missing = [x for x in expected if x not in present]

    opp, _ = _opportunity(session, trace["sheet_id"])
    if opp is None:
        name = trace.get("merchant_name") or "Unknown merchant"
        normalised = normalise_name(name)
        merchant = session.scalar(select(Merchant).where(Merchant.normalized_name == normalised))
        if merchant is None:
            merchant = Merchant(name=name, normalized_name=normalised)
            session.add(merchant)
            session.flush()
        opp = Opportunity(merchant_id=merchant.merchant_id, alias=trace["sheet_id"])
        session.add(opp)
        session.flush()

    sent = 0
    if settings.FLAG_CANDIDATE_QUEUE and req.share_new_questions:
        rows = [r for r in trace["new_rows"] if r["id"] in present and r.get("question")]
        sent = add_candidates(session, opportunity_id=opp.opportunity_id, sheet_id=trace["sheet_id"], rows=rows,
                              command=COMMAND, model=trace["extraction"].get("model"), material=trace["material"])

    gen.opportunity_id, gen.output_ref = opp.opportunity_id, req.sheet_url
    gen.trace = {**trace, "stage": "recorded", "merchant_name": None, "missing_after_edit": missing,
                 "queued": sent, "share_consent": req.share_new_questions, "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    session.flush()
    open_ids = trace["open_p1_ids"]
    texts = dict(session.execute(select(Question.question_id, Question.text).where(
        Question.question_id.in_(open_ids[:MAX_OPEN_LISTED]))).all()) if open_ids else {}
    return {
        "ok": not missing,
        "sheet_url": req.sheet_url,
        "tab": trace.get("tab_title", DEFAULT_TRACK),
        "filled": len(trace["filled_ids"]),
        "confirmed_yours": len(trace.get("confirmed_ids", [])),
        "conflicts": len(trace["conflict_ids"]),
        "scope_log": trace.get("scope_log", {"tab_added": False, "rows": 0}),
        "added": {"from_bank": len(trace["added_bank_ids"]), "new_questions": len(trace["new_rows"])},
        "open_priority_1": {"count": len(open_ids),
                            "first": [{"id": i, "question": texts[i]} for i in open_ids[:MAX_OPEN_LISTED] if i in texts]},
        "queue": {"on": settings.FLAG_CANDIDATE_QUEUE, "shared": req.share_new_questions, "sent": sent},
        "mismatches": {"missing_after_edit": missing},
        "feedback_url": feedback_link(settings, run_id),
    }


def _get_run(session: Session, run_id: str) -> Generation:
    import uuid

    try:
        gen = session.get(Generation, uuid.UUID(run_id))
    except ValueError:
        gen = None
    if gen is None or gen.command != COMMAND:
        raise RunError(404, f"There's no /ops-answer-scope run with ID {run_id}.")
    if gen.trace.get("stage") not in ("planned", "recorded"):
        raise RunError(409, "This run isn't ready to record.")
    return gen
