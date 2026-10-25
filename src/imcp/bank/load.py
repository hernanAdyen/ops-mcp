"""Load a parsed question bank into the database.

A dry run by default: it works out what would change and writes nothing. With apply=True it
makes the changes and records the run in bank_load_run. The caller commits.

Rules (agreed 2026-10-24):
  new ID                      inserted
  changed content             updated; the old version is kept in question_history
  unchanged                   last_seen_at updated
  deactivated ID is back      reactivated
  ID missing from the sheet   deactivated (IDs are permanent and never reused)
  invalid row                 skipped and reported; an ID that's already loaded keeps its last good version
"""

from dataclasses import asdict, dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from imcp.bank.parse import BankRow, ParseResult
from imcp.db import enums as E
from imcp.db.models import BankLoadRun, Question, QuestionHistory

CONTENT_FIELDS = ("text", "type", "options", "notes", "priority", "subsection",
                  "channels", "pillars", "categories", "platforms")
ACTIVE, DEACTIVATED = E.QuestionStatus.active, E.QuestionStatus.deactivated


@dataclass
class LoadReport:
    applied: bool
    source: str | None
    run_id: str | None = None
    fatal: str | None = None
    counts: dict[str, int] = field(default_factory=dict)
    new: list[str] = field(default_factory=list)
    changed: list[dict] = field(default_factory=list)  # {"id": ..., "fields": [...]}
    reactivated: list[str] = field(default_factory=list)
    deactivated: list[str] = field(default_factory=list)
    invalid: list[dict] = field(default_factory=list)  # {"row", "id", "problems", "kept_previous_version"}
    ignored_columns: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def stored_content(q: Question) -> dict:
    """A stored question's content, in the same shape as BankRow.content()."""
    return {
        "text": q.text,
        "type": E.QuestionType(q.type).value,
        "options": list(q.options or []),
        "notes": q.notes,
        "priority": q.priority,
        "subsection": E.Subsection(q.subsection).value,
        "channels": [E.Channel(v).value for v in q.channels],
        "pillars": [E.Pillar(v).value for v in q.pillars],
        "categories": [E.Category(v).value for v in q.categories],
        "platforms": [E.Platform(v).value for v in q.platforms],
    }


def _snapshot(q: Question) -> dict:
    return {**stored_content(q), "status": E.QuestionStatus(q.status).value}


def _set_content(q: Question, r: BankRow) -> None:
    q.text, q.type, q.options, q.notes = r.text, r.type, list(r.options), r.notes
    q.priority, q.subsection = r.priority, r.subsection
    q.channels, q.pillars, q.categories, q.platforms = r.channels, r.pillars, r.categories, r.platforms
    q.content_hash = r.content_hash()


def load_bank(session: Session, parsed: ParseResult, *, source_ref: str | None, apply: bool) -> LoadReport:
    report = LoadReport(applied=False, source=source_ref, ignored_columns=list(parsed.ignored_columns))
    if parsed.fatal:
        report.fatal = parsed.fatal
        return report

    existing = {q.question_id: q for q in session.scalars(select(Question))}
    in_sheet = {r.question_id for r in parsed.rows} | {p.question_id for p in parsed.invalid if p.question_id}

    to_insert: list[BankRow] = []
    to_update: list[tuple[Question, BankRow]] = []
    to_touch: list[Question] = []  # same content
    for r in parsed.rows:
        q = existing.get(r.question_id)
        if q is None:
            to_insert.append(r)
            report.new.append(r.question_id)
            continue
        if q.status == DEACTIVATED:
            report.reactivated.append(r.question_id)
        old, new = stored_content(q), r.content()
        changed_fields = [f for f in CONTENT_FIELDS if old[f] != new[f]]
        if changed_fields:
            to_update.append((q, r))
            report.changed.append({"id": r.question_id, "fields": changed_fields})
        else:
            to_touch.append(q)

    to_deactivate = [q for qid, q in sorted(existing.items()) if qid not in in_sheet and q.status == ACTIVE]
    report.deactivated = [q.question_id for q in to_deactivate]
    report.invalid = [
        {"row": p.row, "id": p.question_id, "problems": p.problems, "kept_previous_version": p.question_id in existing}
        for p in parsed.invalid
    ]

    still_active = sum(1 for qid, q in existing.items() if q.status == ACTIVE and qid not in report.deactivated)
    report.counts = {
        "rows_read": parsed.data_rows,
        "valid": len(parsed.rows),
        "invalid": len(parsed.invalid),
        "new": len(report.new),
        "changed": len(report.changed),
        "unchanged": sum(1 for q in to_touch if q.status == ACTIVE),
        "reactivated": len(report.reactivated),
        "deactivated": len(report.deactivated),
        "active_after": still_active + len(report.new) + len(report.reactivated),
    }
    if not apply:
        return report

    run = BankLoadRun(source_ref=source_ref)
    session.add(run)
    session.flush()
    now = func.now()

    for r in to_insert:
        q = Question(question_id=r.question_id, status=ACTIVE)
        _set_content(q, r)
        session.add(q)
    for q, r in to_update:
        old = _snapshot(q)
        _set_content(q, r)
        q.status, q.last_seen_at = ACTIVE, now
        session.add(QuestionHistory(question_id=q.question_id, bank_load_run_id=run.run_id,
                                    old=old, new={**r.content(), "status": ACTIVE.value}))
    for q in to_touch:
        if q.status == DEACTIVATED:
            old = _snapshot(q)
            q.status = ACTIVE
            session.add(QuestionHistory(question_id=q.question_id, bank_load_run_id=run.run_id,
                                        old=old, new={**old, "status": ACTIVE.value}))
        q.last_seen_at = now
    for q in to_deactivate:
        old = _snapshot(q)
        q.status = DEACTIVATED
        session.add(QuestionHistory(question_id=q.question_id, bank_load_run_id=run.run_id,
                                    old=old, new={**old, "status": DEACTIVATED.value}))

    report.applied, report.run_id = True, str(run.run_id)
    run.seen = parsed.data_rows
    run.inserted = len(report.new)
    run.updated = len({c["id"] for c in report.changed} | set(report.reactivated))
    run.deactivated = len(report.deactivated)
    run.invalid = len(report.invalid)
    run.report = report.to_dict()
    run.status, run.finished_at = E.RunStatus.succeeded, now
    session.flush()
    return report
