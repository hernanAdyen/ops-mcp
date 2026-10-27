"""A prompt the IM can paste into their call-notes tool (for example Gong's AI) after a call.

It lists the scope's questions with their IDs and asks for each answer by ID, or 'not discussed'.
When the IM brings that output to /ops-answer-scope, answers map to questions by ID, so our
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


TRACKS_NOTE = ("The questions are grouped by project track. The same question can appear under more than one "
               "track: answer it for each track.")


def call_prompt(questions: list[Question], new_questions: list[dict] | None = None,
                priorities: tuple[int, ...] = (1,), tracks: list[tuple[str, list[Question]]] | None = None) -> dict:
    """
    questions      in sheet order (one track); new_questions [{id, question}] from Suggested additions
    tracks         [(track name, its questions in sheet order)] when the scope has several tracks; then
                   `questions` is ignored and each track gets a heading
    """
    parts = tracks if tracks and len(tracks) > 1 else [(None, questions if not tracks else tracks[0][1])]
    lines, asked, total = [], 0, 0
    for name, qs in parts:
        chosen = [q for q in qs if not priorities or q.priority in priorities]
        total += len(qs)
        if not chosen and name is not None:
            continue
        if name is not None:
            lines += ([""] if lines else []) + [f"Track: {name}"]
        lines += [f"{q.question_id}: {one_line(q.text, 300)}{_hint(q)}" for q in chosen]
        asked += len(chosen)
    extra = [f"{n['id']}: {one_line(n['question'], 300)}" for n in new_questions or []]
    if extra:
        lines += ([""] + ["Suggested additions:"] if len(parts) > 1 else []) + extra
    intro = INTRO + (" " + TRACKS_NOTE if len(parts) > 1 else "")
    return {
        "priorities": list(priorities) or "all",
        "questions": asked + len(extra),
        "left_out": total - asked,
        # no text when nothing matched: a prompt of track headings alone is no prompt
        "text": intro + "\n\n" + "\n".join(lines) if lines and asked + len(extra) else None,
    }
