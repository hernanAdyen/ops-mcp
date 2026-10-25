"""/source-scope-answers in two calls. The IM reviews the result in their own sheet.

  start   the sheet as read + the IM's merchant material -> our model finds answers and new
          questions -> one exact Sheets batch that writes them into Project Scope
  record  read-back check, the deal (opportunity), the review queue (behind FLAG_CANDIDATE_QUEUE),
          the open priority-1 questions for the next call, and the feedback link

The material is sent to our model for this run only. It is never stored or logged, and neither are
the answers: the run's trace keeps question IDs, counts and a hash of each piece of material.
"""

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
from imcp.scope.answers_plan import REVIEW_COLUMNS, SheetRead, plan_answers
from imcp.scope.candidates import bank_status
from imcp.scope.extract import MAX_MATERIAL_CHARS, Material, extract_answers
from imcp.scope.queue import add_candidates, observe_im_review, sha256
from imcp.scope.runs import RunError, feedback_link, normalise_name

COMMAND = "source-scope-answers"
FOUND_IN_MATERIAL, FOUND_NEW = "answered in material", "new question"
MAX_OPEN_LISTED = 10


class MaterialIn(BaseModel):
    label: str = Field(min_length=1, max_length=80, description="e.g. 'Call summary, Oct 24'")
    kind: Literal["transcript", "summary", "notes", "email", "document"] = "notes"
    text: str = Field(min_length=1, max_length=MAX_MATERIAL_CHARS)


class NewRowIn(BaseModel):
    id: str = Field(max_length=20)
    question: str = Field(default="", max_length=2000)


class AnswersStartRequest(BaseModel):
    sheet_id: str = Field(min_length=10, max_length=200)
    merchant_name: str | None = Field(default=None, max_length=200)
    tab_sheet_id: int
    column_count: int = Field(ge=1)
    row_count: int = Field(ge=1)
    header_row: list[str]
    id_column: list[str]
    columns: dict[str, list[str]] = Field(default_factory=dict)
    new_rows: list[NewRowIn] = Field(default_factory=list)
    basic_filter: dict | None = None
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
    if not req.id_column or req.id_column[0].strip().lower() not in ("id", "question_id"):
        raise RunError(422, "id_column must be column A of the Project Scope tab, starting with its 'id' header.")
    names = [h.strip().lower() for h in req.header_row]
    if not names or names[0] not in ("id", "question_id"):
        raise RunError(422, "header_row must be row 1 of the Project Scope tab, as read.")
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


def _earlier_runs(session: Session, sheet_id: str) -> list[Generation]:
    return list(session.scalars(select(Generation).where(
        Generation.command == COMMAND, Generation.trace["sheet_id"].astext == sheet_id)))


def start_answers(session: Session, settings: AppSettings, model, req: AnswersStartRequest) -> dict:
    if not bank_status(session, settings)["active_questions"]:
        raise RunError(409, "The question bank isn't loaded yet. Load it with im_bank_load first.")
    sheet = _sheet_read(req)
    opp, merchant = _opportunity(session, req.sheet_id)
    merchant_name = merchant.name if merchant else (req.merchant_name or "").strip()
    if not merchant_name:
        raise RunError(422, "This sheet wasn't made by /create-scope, so I don't know the merchant. Pass merchant_name.")

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

    materials = [Material(m.label.strip(), m.kind, m.text) for m in req.material]
    extraction = extract_answers(model, materials, sheet_questions, others,
                                 [r.question for r in req.new_rows if r.question.strip()], merchant_name,
                                 sanitize=settings.FLAG_SANITIZE)
    if extraction.status != "ok":
        raise RunError(503, f"{extraction.note} Nothing was written to the sheet.")

    in_sheet = [a for a in extraction.answers if a["in_sheet"]]
    from_bank = [a for a in extraction.answers if not a["in_sheet"]]
    kind_of = {m.label.casefold(): m.kind for m in materials}
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

    added_before = {qid for g in _earlier_runs(session, req.sheet_id) for qid in g.trace.get("added_bank_ids", [])}
    plan = plan_answers(sheet, in_sheet, additions, label_needed(sheet.ids, added_before))
    merge = plan["merge"]
    open_p1 = [q.question_id for q in sheet_questions if q.priority == 1 and q.question_id not in merge.answered]

    queue_on = settings.FLAG_CANDIDATE_QUEUE
    keep = ("id", "type", "options", "subsection", "raised_by", "closest_id", "source_kind")
    gen = Generation(
        command=COMMAND, tool_version=SERVICE_VERSION, flags=describe_config(settings)["flags"],
        opportunity_id=opp.opportunity_id if opp else None,
        trace={
            "stage": "planned",
            "sheet_id": req.sheet_id,
            "merchant_name": None if opp else merchant_name,  # only needed to create the deal at record
            "material": [{"kind": m.kind, "chars": len(m.text), "sha256": sha256(m.text)} for m in materials],
            "extraction": extraction.summary(),
            "filled_ids": merge.filled,
            "agreed_ids": merge.agreed,
            "conflict_ids": [c["id"] for c in merge.conflicts],
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
    text = {q.question_id: q.text for q in bank.values()}
    return {
        "draft_id": str(gen.generation_id),
        "requests": plan["requests"],
        "summary": {
            "model": extraction.model,
            "filled": len(merge.filled),
            "agreed_with_yours": len(merge.agreed),
            "conflicts": [{"id": c["id"], "question": text[c["id"]], "yours": c["yours"], "found": c["found"],
                           "source": c["source"]} for c in merge.conflicts],
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
        raise RunError(422, "id_column must be column A of the Project Scope tab, starting with its 'id' header.")
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
        "filled": len(trace["filled_ids"]),
        "conflicts": len(trace["conflict_ids"]),
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
        raise RunError(404, f"There's no /source-scope-answers run with ID {run_id}.")
    if gen.trace.get("stage") not in ("planned", "recorded"):
        raise RunError(409, "This run isn't ready to record.")
    return gen
