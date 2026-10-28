"""Draft the bank's `purpose` and `baseline` columns with our model, for the owner to review.

The master bank belongs to people: nothing here writes to it. The command prints a CSV (id, question,
baseline, purpose) that the owner reads, corrects and pastes into the master by ID, then loads with
`im_bank_load` (dry run first). Run inside the app container, from the repo:

    mkdir -p data/drafts && docker compose exec -T app python -m imcp.bank.draft > data/drafts/bank-columns.csv

Our model's output is checked like everywhere else: unknown IDs are dropped, a purpose is one line of at
most MAX_PURPOSE characters, baseline is Y or N. A question the model skipped is in the CSV with empty
cells, so the owner sees it.
"""

import csv
import io
import logging
import sys
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from imcp.bank.parse import MAX_PURPOSE
from imcp.db import enums as E
from imcp.db.models import Question
from imcp.llm import ModelError, parse_json_object
from imcp.scope.candidates import SUBSECTION_LABELS, TAG_ENUMS
from imcp.scope.text import one_line

log = logging.getLogger("imcp.bank.draft")

BATCH = 30
MAX_WORDS = 20

SYSTEM_PROMPT = """You help maintain the question bank that Adyen implementation managers (IMs) use to scope a merchant's
payment project. For each question you get its ID, section, priority, the question, its tags (channels, pillars,
categories, platforms; none means it applies to everyone) and any notes.

For each question give:
- "purpose": one plain sentence, at most 20 words, saying what the answer decides or accomplishes for the
  integration or the proposal. For example: "Sets the regions and currencies the integration must support."
  Everyday words, no jargon the IM wouldn't use, no merchant names.
- "baseline": true only if the question should be asked in every merchant project, whatever the channel, product
  or pillar: the facts every proposal needs (regions, payment methods, platforms, go-live date, volumes, stakeholders).
  Questions about one product, channel or feature are false. Keep the baseline small: at most one question in six.

Answer with one JSON object and nothing else:
{"items": [{"id": "ID-0000", "purpose": "...", "baseline": false}]}

Use the IDs exactly as listed and give every question exactly once."""


@dataclass
class DraftResult:
    model: str | None = None
    items: list[dict] = field(default_factory=list)  # id, question, baseline, purpose (empty when missing)
    missing: list[str] = field(default_factory=list)  # questions the model skipped, or whose batch failed
    dropped: dict[str, int] = field(default_factory=dict)  # counts of what was thrown away, by reason
    notes: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {"model": self.model, "questions": len(self.items), "baseline": sum(1 for i in self.items if i["baseline"]),
                "missing": len(self.missing), "dropped": self.dropped, "notes": self.notes}


def question_lines(questions: list[Question]) -> str:
    lines = []
    for q in questions:
        tags = " · ".join(", ".join(enum_cls(v).value for v in getattr(q, name))
                          for name, enum_cls in TAG_ENUMS.items() if getattr(q, name)) or "no tags"
        notes = f" | notes: {one_line(q.notes, 200)}" if q.notes else ""
        lines.append(f"{q.question_id} | {SUBSECTION_LABELS[E.Subsection(q.subsection)]} | P{q.priority} | "
                     f"{one_line(q.text, 400)} | {tags}{notes}")
    return "\n".join(lines)


def _as_bool(value) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        word = value.strip().lower()
        if word in ("y", "yes", "true", "1"):
            return True
        if word in ("n", "no", "false", "0", ""):
            return False
    return None


def _purpose(value) -> str:
    text = one_line(value, MAX_PURPOSE * 2) if isinstance(value, str) else ""
    words = text.split()
    if len(words) > MAX_WORDS * 2:  # far too long: cut at a word, the owner rewrites it
        text = " ".join(words[:MAX_WORDS * 2])
    return text[:MAX_PURPOSE].rstrip(" ,;")


def draft_columns(model, questions: list[Question], *, batch: int = BATCH) -> DraftResult:
    """Ask our model for a purpose and a baseline flag per question, in batches, and check what it returns."""
    result = DraftResult(model=getattr(model, "model", None))
    found: dict[str, dict] = {}
    dropped: dict[str, int] = {}
    for start in range(0, len(questions), batch):
        chunk = questions[start:start + batch]
        allowed = {q.question_id for q in chunk}
        try:
            reply = model.chat([{"role": "system", "content": SYSTEM_PROMPT},
                                {"role": "user", "content": f"Questions:\n{question_lines(chunk)}"}],
                               max_tokens=4000, timeout=180)
            data = parse_json_object(reply)
        except ModelError as exc:
            result.notes.append(f"batch starting at {chunk[0].question_id} failed: {exc}")
            continue
        items = data.get("items")
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                dropped["not_an_object"] = dropped.get("not_an_object", 0) + 1
                continue
            qid = str(item.get("id") or "").strip()
            if qid not in allowed:
                dropped["unknown_id"] = dropped.get("unknown_id", 0) + 1
                continue
            if qid in found:
                dropped["repeated_id"] = dropped.get("repeated_id", 0) + 1
                continue
            baseline = _as_bool(item.get("baseline"))
            if baseline is None:
                dropped["bad_baseline"] = dropped.get("bad_baseline", 0) + 1
                baseline = False
            found[qid] = {"baseline": baseline, "purpose": _purpose(item.get("purpose"))}
    for q in questions:
        item = found.get(q.question_id)
        if item is None or not item["purpose"]:
            result.missing.append(q.question_id)
        result.items.append({"id": q.question_id, "question": q.text,
                             "baseline": bool(item and item["baseline"]), "purpose": item["purpose"] if item else ""})
    result.dropped = dropped
    return result


def to_csv(result: DraftResult) -> str:
    """The draft as CSV: id, question, baseline (Y/N), purpose. The owner pastes baseline and purpose by ID."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["id", "question", "baseline", "purpose"])
    for item in result.items:
        writer.writerow([item["id"], item["question"], "Y" if item["baseline"] else "N", item["purpose"]])
    return buf.getvalue()


def active_questions(session: Session) -> list[Question]:
    return list(session.scalars(select(Question).where(Question.status == E.QuestionStatus.active)
                                .order_by(Question.subsection, Question.question_id)))


def main(argv: list[str] | None = None) -> int:
    """Print the draft CSV to stdout; the summary goes to stderr."""
    from imcp.app.db import create_db_engine
    from imcp.config import AppSettings
    from imcp.llm import ModelClient

    settings = AppSettings()
    model = ModelClient.from_settings(settings)
    if model is None:
        print("Our model isn't configured (MODEL_BASE_URL, MODEL_NAME).", file=sys.stderr)
        return 2
    with Session(create_db_engine(settings.database_url())) as session:
        questions = active_questions(session)
    if not questions:
        print("The question bank isn't loaded yet. Load it with im_bank_load first.", file=sys.stderr)
        return 2
    result = draft_columns(model, questions)
    sys.stdout.write(to_csv(result))
    summary = result.summary()
    print(f"{summary['questions']} questions, {summary['baseline']} marked baseline, "
          f"{summary['missing']} without a purpose (empty in the CSV), dropped: {summary['dropped'] or 'nothing'}",
          file=sys.stderr)
    for note in result.notes:
        print(note, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
