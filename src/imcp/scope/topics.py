"""Topic matching: from the IM's notes, pick the bank questions the tags didn't select.

Runs on our backend with our model, so the IM's Claude never has to hold the bank.
The tag filter runs first. The model sees its matches read-only (to judge what's covered) and may
only add from the questions the filter left out; anything else it returns is dropped. The IM's
notes are sent to the model but never stored. If the model isn't available, the scope still
works with the tag matches alone and says so.

For a topic in the notes that no bank question covers, the model drafts a general question. It goes
under 'Suggested additions' in the IM's sheet for review (and to the review queue, if that's on).
"""

import re
from dataclasses import asdict, dataclass, field
from typing import Protocol

from imcp.llm import ModelError, parse_json_object
from imcp.scope.text import same_question

SAME_QUESTION = 0.85  # a drafted question this close to a bank question is the bank question

MAX_ADDITIONS = 15
MAX_GAP_QUESTIONS = 5
MAX_TOPIC = 60
MAX_REASON = 160
MAX_QUESTION = 300

SYSTEM_PROMPT = """You help an Adyen implementation manager (IM) build the list of scoping questions for a merchant project.
You get three things: the IM's notes about the merchant, the questions already in the scope (chosen by the IM's tag filter),
and the other questions in the question bank, which the tag filter did NOT select.

Choose additions only from the other questions:
- Add each question that asks about a topic, product or requirement the notes mention.
- For each such topic, also add the follow-up questions needed to scope it: how it will be set up, its options and its
  dependencies. For example, if the notes mention in-store payments: terminal types, network connection, offline processing.
- Do not add questions that are only generally useful, or near-duplicates of questions already in the scope.

Answer with one JSON object and nothing else:
{"topics": ["short topic from the notes, 1-4 words"],
 "additions": [{"id": "ID-0000", "topic": "one of your topics", "reason": "why it fits, at most 15 words"}],
 "uncovered_topics": [{"topic": "a topic from the notes that no question covers, neither those already in the scope nor the others",
                       "question": "a general scoping question about it that an IM could ask any merchant",
                       "type": "free_text or toggle"}]}

Rules:
- Never choose a question that is already in the scope.
- Use question IDs exactly as listed. Never invent an ID.
- At most 15 additions. Prefer questions whose answers would change the integration design or the effort.
- Topics, reasons and questions must not contain merchant names, people's names or other personal details.
- If nothing fits, return empty lists."""


class ChatModel(Protocol):
    model: str

    def chat(self, messages: list[dict], *, max_tokens: int = ..., temperature: float = ...,
             timeout: float | None = ...) -> str: ...


@dataclass
class TopicResult:
    status: str  # ok | skipped (no notes) | unavailable (no model, or it failed)
    model: str | None = None
    topics: list[str] = field(default_factory=list)
    additions: list[dict] = field(default_factory=list)  # {"id", "topic", "reason"}
    uncovered_topics: list[str] = field(default_factory=list)
    gap_questions: list[dict] = field(default_factory=list)  # {"topic", "question", "type"}: drafted for review
    dropped_ids: list[str] = field(default_factory=list)  # chosen by the model but not in the list
    note: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _clean(value, limit: int, scrub: str | None) -> str:
    text = " ".join(str(value or "").split())
    if scrub:
        text = re.sub(re.escape(scrub), "the merchant", text, flags=re.IGNORECASE)
    return text[:limit]


def question_lines(questions: list[dict]) -> str:
    """One line per question: id | priority | subsection | question | tags."""
    lines = []
    for q in questions:
        tags = " · ".join(", ".join(v) for v in q["tags"].values()) or "no tags"
        text = " ".join(q["question"].split())
        lines.append(f'{q["id"]} | P{q["priority"]} | {q["subsection"]} | {text} | {tags}')
    return "\n".join(lines)


def match_topics(model: ChatModel | None, notes: str | None, questions: list[dict],
                 merchant_name: str | None = None, selected: list[dict] | None = None,
                 track: str | None = None) -> TopicResult:
    """
    questions  the ones the tags didn't select: the only ones the model may add
    selected   the tag matches, shown read-only so the model can tell what's already covered
    Both are dicts with id, question, priority, subsection and tags.
    track      a line naming the project track this list is for (e.g. "In-person payments UK: channels
               IPP"), when the scope has several, so the notes' other tracks don't leak in
    """
    if not notes or not notes.strip():
        return TopicResult(status="skipped", note="No context from the IM, so only the tag matches are used.")
    if model is None:
        return TopicResult(status="unavailable", note="The model isn't configured (MODEL_BASE_URL, MODEL_NAME).")
    if not questions:
        return TopicResult(status="ok", model=model.model, note="Every question in range was already selected by tags.")

    about = (f"This list is for the project track \"{track}\". The notes may cover other tracks too: add only "
             "questions that belong to this track.\n\n") if track else ""
    user = (
        f'IM notes:\n"""\n{notes.strip()}\n"""\n\n' + about +
        "Already in the scope, selected by the IM's tags. Do not choose these; use them only to judge what is covered "
        f"(id | priority | subsection | question | tags):\n{question_lines(selected or []) or '(none)'}\n\n"
        f"Other questions, the only ones you may add (id | priority | subsection | question | tags):\n{question_lines(questions)}"
    )
    try:
        reply = model.chat([{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}])
        data = parse_json_object(reply)
    except ModelError as exc:
        return TopicResult(status="unavailable", model=model.model,
                           note=f"Topic matching didn't run: {exc}. Only the tag matches are used.")

    scrub = merchant_name.strip() if merchant_name and len(merchant_name.strip()) >= 3 else None
    allowed = {q["id"] for q in questions}
    result = TopicResult(status="ok", model=model.model)
    result.topics = [t for t in (_clean(t, MAX_TOPIC, scrub) for t in _as_list(data.get("topics"))) if t]
    known = [q["question"] for q in questions] + [q["question"] for q in selected or []]
    for item in _as_list(data.get("uncovered_topics")):
        topic = _clean(item.get("topic") if isinstance(item, dict) else item, MAX_TOPIC, scrub)
        if not topic or topic in result.uncovered_topics:
            continue
        result.uncovered_topics.append(topic)
        question = _clean(item.get("question"), MAX_QUESTION, scrub) if isinstance(item, dict) else ""
        if not question or len(result.gap_questions) >= MAX_GAP_QUESTIONS:
            continue
        if any(same_question(question, k, SAME_QUESTION) for k in known):
            continue  # the bank has it after all
        kind = str(item.get("type") or "").strip().lower()
        result.gap_questions.append({"topic": topic, "question": question,
                                     "type": kind if kind in ("free_text", "toggle") else "free_text"})
        known.append(question)
    seen: set[str] = set()
    for item in _as_list(data.get("additions")):
        if not isinstance(item, dict):
            continue
        qid = str(item.get("id", "")).strip()
        if qid not in allowed:
            if qid:
                result.dropped_ids.append(qid)
            continue
        if qid in seen or len(result.additions) >= MAX_ADDITIONS:
            continue
        seen.add(qid)
        result.additions.append({
            "id": qid,
            "topic": _clean(item.get("topic"), MAX_TOPIC, scrub) or "context",
            "reason": _clean(item.get("reason"), MAX_REASON, scrub),
        })
    return result


def _as_list(value) -> list:
    return value if isinstance(value, list) else []
