"""A prompt the IM can paste into their call-notes tool (for example Gong's AI) after a call.

It lists the scope's questions with their IDs and asks for each answer by ID, or 'not discussed'.
When the IM brings that output to /source-scope-answers, answers map to questions by ID, so our
model doesn't have to guess which question a remark answers.
"""

from imcp.db import enums as E
from imcp.db.models import Question
from imcp.scope.text import one_line

INTRO = ("Answer these scoping questions from this call. For each one, write the ID, then the answer the merchant "
         "gave, in a few words. If it wasn't discussed or is still undecided, write 'not discussed'. Don't guess.")


def _hint(q: Question) -> str:
    kind = E.QuestionType(q.type)
    if kind is E.QuestionType.toggle:
        return " (yes / no)"
    if q.options:
        return f" ({' / '.join(q.options)}{', more than one' if kind is E.QuestionType.multi_choice else ''})"
    if kind is E.QuestionType.number:
        return " (a number)"
    return ""


def call_prompt(questions: list[Question], new_questions: list[dict] | None = None,
                priorities: tuple[int, ...] = (1,)) -> dict:
    """questions in sheet order; new_questions [{id, question}] from Suggested additions."""
    chosen = [q for q in questions if not priorities or q.priority in priorities]
    lines = [f"{q.question_id}: {one_line(q.text, 300)}{_hint(q)}" for q in chosen]
    lines += [f"{n['id']}: {one_line(n['question'], 300)}" for n in new_questions or []]
    return {
        "priorities": list(priorities) or "all",
        "questions": len(lines),
        "left_out": len(questions) - len(chosen),
        "text": INTRO + "\n\n" + "\n".join(lines) if lines else None,
    }
