"""The review queue for new questions (behind FLAG_CANDIDATE_QUEUE).

A new question found in an IM's material, or drafted for a topic the bank doesn't cover, is stored
as an `instance` (a question, review status pending) with a `source` that is only a pointer: the
scope sheet and the kind of material, never the material. Only the generic wording and its
suggested type, subsection and closest bank question are kept: no answers, no names.

The IM reviews new questions in their own sheet. Each later run reads those rows back, and the
queue records what the IM did: kept, edited (with their wording), confirmed, rejected or removed.
That is the signal for whoever curates the master bank; nothing here changes the bank.
"""

import hashlib
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from imcp import SERVICE_VERSION
from imcp.db import enums as E
from imcp.db.models import IngestionRun, Instance, Source
from imcp.scope.text import one_line, scrub_contacts, scrub_name, similar

KINDS = {"transcript": E.ChatKind.transcript, "summary": E.ChatKind.brief, "notes": E.ChatKind.notes,
         "email": E.ChatKind.email, "document": E.ChatKind.document}
SPEAKERS = {"im": E.SpeakerRole.im, "merchant": E.SpeakerRole.merchant}
EDITED = 0.97  # below this similarity, the IM changed the wording


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def queued_rows(session: Session, opportunity_id) -> dict[str, Instance]:
    """New questions already queued for this deal, by their sheet ID (NEW-0001, ...)."""
    found = session.scalars(select(Instance).where(
        Instance.opportunity_id == opportunity_id, Instance.act_type == E.ActType.question,
        Instance.extraction["sheet_ref"].astext.is_not(None)))
    return {i.extraction["sheet_ref"]: i for i in found}


def add_candidates(session: Session, *, opportunity_id, sheet_id: str, rows: list[dict], command: str,
                   model: str | None, material: list[dict]) -> int:
    """
    rows      the new questions now in the sheet: id (NEW-…), question, type, options, subsection,
              raised_by, closest_id, reason, source_kind, and topic for topic gaps
    material  [{kind, sha256}] for the pieces they came from (pointers only)
    Returns how many were added (a row already queued for this deal isn't added twice).
    """
    already = queued_rows(session, opportunity_id)
    rows = [r for r in rows if r["id"] not in already]
    if not rows:
        return 0
    run = IngestionRun(kind="chat_candidates", status=E.RunStatus.succeeded, finished_at=datetime.now(timezone.utc),
                       extractor_version=f"{command}/{SERVICE_VERSION}", model=model, stats={"candidates": len(rows)})
    session.add(run)
    sources: dict[str, Source] = {}
    hashes = {m["kind"]: m.get("sha256") for m in material}
    for kind in dict.fromkeys(r.get("source_kind") or "notes" for r in rows):
        sources[kind] = Source(opportunity_id=opportunity_id, type=E.SourceType.chat,
                               chat_kind=KINDS.get(kind, E.ChatKind.notes),
                               ref=f"sheet {sheet_id} · {command} · {kind}", content_hash=hashes.get(kind))
        session.add(sources[kind])
    session.flush()
    for r in rows:
        extraction = {k: r.get(k) for k in ("type", "options", "subsection", "closest_id", "reason", "topic")
                      if r.get(k) not in (None, "", [])}
        session.add(Instance(
            opportunity_id=opportunity_id,
            source_id=sources[r.get("source_kind") or "notes"].source_id,
            ingestion_run_id=run.run_id,
            speaker_role=SPEAKERS.get(r.get("raised_by"), E.SpeakerRole.other),
            act_type=E.ActType.question,
            subtype=E.InstanceSubtype.im_discovery,
            statement=r["question"],
            extraction={**extraction, "sheet_id": sheet_id, "sheet_ref": r["id"], "command": command,
                        "im_status": "suggested"},
        ))
    session.flush()
    return len(rows)


def observe_im_review(session: Session, opportunity_id, sheet_rows: dict[str, dict],
                      merchant_name: str | None = None) -> dict:
    """
    Records what the IM did with the new questions queued for this deal.
    sheet_rows: the NEW- rows now in the sheet, by ID: {"question": current wording, "status": status cell}.
    Returns counts by what was seen.
    """
    seen: dict[str, int] = {}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for ref, inst in queued_rows(session, opportunity_id).items():
        row = sheet_rows.get(ref)
        extraction = dict(inst.extraction)
        if row is None:
            state = "removed"
        else:
            wording = scrub_contacts(scrub_name(one_line(row.get("question"), 300), merchant_name))
            status = one_line(row.get("status"), 20).casefold()
            edited = bool(wording) and similar(wording, inst.statement) < EDITED
            if edited:
                extraction["im_wording"] = wording
            state = status if status in ("confirmed", "rejected") else "edited" if edited else "kept"
        seen[state] = seen.get(state, 0) + 1
        changed = (inst.extraction.get("im_status") != state
                   or extraction.get("im_wording") != inst.extraction.get("im_wording"))
        if changed:
            extraction.update({"im_status": state, "im_seen_at": now})
            inst.extraction = extraction
    session.flush()
    return seen
