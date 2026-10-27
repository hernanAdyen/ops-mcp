"""Which answers from a track's tab go into the proposal, and in what form.

Rules (agreed 2026-10-26):
  - The IM's own answer wins: no `source`, or `status` confirmed.
  - A `suggested` answer (found by /ops-answer-scope, not yet confirmed) is used, but flagged.
  - A `rejected` answer is skipped.
  - Unanswered questions are left out of the document; the open priority-1 ones are listed in the reply.
  - NEW- rows (the IM's own additions) count as Discovery questions, with the text from the sheet.
  - Features & Functionality: every answered row goes in the table. A toggle shows a ticked box when yes
    and an empty box when no; any other type shows its answer text.

Pure functions over what the skill read from the sheet. Nothing here is stored.
"""

from dataclasses import dataclass, field

from imcp.bank.parse import ID_PATTERN
from imcp.db import enums as E
from imcp.db.models import Question
from imcp.scope.additions import NEW_ID

YES = {"yes", "y", "true", "x", "✓", "✔", "☑", "in scope", "included"}
NO = {"no", "n", "false", "-", "out of scope", "not in scope", "excluded", "☐"}
OWN, SUGGESTED = "own", "suggested"
MAX_ANSWER_CHARS = 2000


@dataclass
class Answer:
    id: str
    question: str
    subsection: str  # introduction | discovery | features_functionality
    type: str  # bank question type, or free_text for NEW- rows
    answer: str
    origin: str  # own | suggested
    priority: int | None = None

    @property
    def display(self) -> str:
        """The answer as it reads in a document: a toggle's yes/no, or any TRUE/FALSE from a sheet
        checkbox (also on NEW- rows), becomes Yes/No."""
        if self.type == E.QuestionType.toggle.value:
            scope = in_scope(self)
            if scope is not None:
                return "Yes" if scope else "No"
        value = self.answer.strip().casefold()
        if value in ("true", "false"):
            return "Yes" if value == "true" else "No"
        return self.answer

    def to_dict(self) -> dict:
        return {"id": self.id, "question": self.question, "answer": self.display, "origin": self.origin}


@dataclass
class TrackAnswers:
    name: str
    answers: list[Answer] = field(default_factory=list)
    open_p1_ids: list[str] = field(default_factory=list)  # priority-1 bank questions with no usable answer
    skipped_rejected_ids: list[str] = field(default_factory=list)
    not_loaded: list[str] = field(default_factory=list)  # ID- rows the bank doesn't know

    def by_subsection(self, subsection: str) -> list[Answer]:
        return [a for a in self.answers if a.subsection == subsection]

    @property
    def suggested_ids(self) -> list[str]:
        return [a.id for a in self.answers if a.origin == SUGGESTED]

    @property
    def used_ids(self) -> list[str]:
        return [a.id for a in self.answers]


def _cells(values: list[str] | None, n: int) -> list[str]:
    col = [str(v or "").strip() for v in (values or [])]
    return col + [""] * max(0, n - len(col))


def pick_answers(name: str, ids: list[str], columns: dict[str, list[str]], bank: dict[str, Question]) -> TrackAnswers:
    """
    ids: column A below the header. columns: by header name (answer, status, source, question), each
    below its header and aligned with ids.
    """
    n = len(ids)
    answer_col, status_col = _cells(columns.get("answer"), n), _cells(columns.get("status"), n)
    source_col, question_col = _cells(columns.get("source"), n), _cells(columns.get("question"), n)
    out = TrackAnswers(name=name)
    seen: set[str] = set()
    for i, raw in enumerate(ids):
        qid = raw.strip()
        if not qid or qid in seen:
            continue
        seen.add(qid)
        answer, status = answer_col[i][:MAX_ANSWER_CHARS], status_col[i].casefold()
        q = bank.get(qid)
        is_new = bool(NEW_ID.fullmatch(qid))
        if q is None:
            if ID_PATTERN.fullmatch(qid):
                out.not_loaded.append(qid)
            if not is_new:
                continue
        if status == "rejected":
            if answer:
                out.skipped_rejected_ids.append(qid)
            if q is not None and q.priority == 1:
                out.open_p1_ids.append(qid)
            continue
        if not answer:
            if q is not None and q.priority == 1:
                out.open_p1_ids.append(qid)
            continue
        origin = SUGGESTED if (source_col[i] and status != "confirmed") or status == "suggested" else OWN
        if q is None:  # a NEW- row the IM kept
            text = question_col[i]
            if not text:
                continue
            out.answers.append(Answer(qid, text, E.Subsection.discovery.value, E.QuestionType.free_text.value,
                                      answer, origin))
            continue
        out.answers.append(Answer(qid, q.text, E.Subsection(q.subsection).value, E.QuestionType(q.type).value,
                                  answer, origin, q.priority))
    return out


def in_scope(answer: Answer) -> bool | None:
    """True/False for a toggle answer; None when the answer isn't a clear yes or no."""
    value = answer.answer.strip().casefold()
    if value in YES:
        return True
    if value in NO:
        return False
    return None


def feature_rows(track: TrackAnswers) -> list[dict]:
    """The Features & Functionality table rows: [{id, feature, in_scope (bool | None), text}]."""
    rows = []
    for a in track.by_subsection(E.Subsection.features_functionality.value):
        scope = in_scope(a) if a.type == E.QuestionType.toggle.value else None
        text = "" if scope is not None else a.answer
        if a.type == E.QuestionType.toggle.value and scope is None:
            text = a.answer  # a toggle with a written answer: show the text
        rows.append({"id": a.id, "feature": a.question, "in_scope": scope, "text": text, "origin": a.origin})
    return rows
