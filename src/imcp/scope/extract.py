"""Answers from the IM's merchant material, with our model (/source-scope-answers).

The IM shares whatever they have from the merchant: notes, a call summary or transcript, an email
or a document. It is sent to our model for this run only, and never stored or logged. The model
answers the questions in the IM's sheet, may answer other bank questions the material answers
directly, and lists new questions that no bank question covers. Everything it returns is checked
here: unknown IDs are dropped, answers are put in the question's format, and new questions that
repeat a bank question (or one already in the sheet) are dropped.
"""

import re
from dataclasses import asdict, dataclass, field

from imcp.db import enums as E
from imcp.db.models import Question
from imcp.llm import ModelError, parse_json_object
from imcp.scope.text import one_line, same_question, scrub_contacts, scrub_name
from imcp.scope.topics import ChatModel

MAX_MATERIAL_CHARS = 150_000
MAX_ANSWER = 500
MAX_EVIDENCE = 200
MAX_QUESTION = 300
MAX_REASON = 160
MAX_NEW = 8
MAX_OTHER_BANK = 15
MODEL_TIMEOUT = 240  # seconds: long material takes the model a while
SAME_QUESTION = 0.85  # similarity at which a "new" question is really one we already have
CONFIDENCE = ("high", "medium", "low")
NEW_SUBSECTIONS = {"discovery": E.Subsection.discovery, "features_functionality": E.Subsection.features_functionality}
TRUE_WORDS = {"true", "yes", "y", "in scope", "1"}
FALSE_WORDS = {"false", "no", "n", "not in scope", "out of scope", "0"}

SYSTEM_PROMPT = """You help an Adyen implementation manager (IM) fill in the scoping question sheet for a merchant project.
You get material the IM has from the merchant (call notes, a call summary or transcript, emails or documents),
the questions in the IM's sheet, and the other questions in our question bank.

Answer from the material only:
- Answer each question in the IM's sheet that the material answers. Leave out questions it doesn't answer and
  anything that is still undecided. Never guess.
- Answer one of the other bank questions only when the material answers it directly.
- The material may list answers by question ID (for example from a call-notes tool given our questions). Use those
  IDs, and treat 'not discussed' as no answer.
- Use the question's format. toggle: TRUE or FALSE (TRUE means yes, or in scope). single_choice: exactly one of its
  options. multi_choice: one or more of its options, joined with " | ". number: a number. free_text: a short answer in
  your own words, at most 25 words.
- For each answer give the label of the material it came from, a short evidence note (at most 20 words, in your own
  words: no quotes, no people's names, no email addresses or phone numbers) and a confidence: high if the material
  says it directly, medium if it clearly implies it, low if you inferred it.

Then list new questions: things the material raises that matter for scoping the integration (a question the IM asked,
or a need or constraint the merchant raised) and that no question in either list covers, even in other words.
Write each as a general scoping question an IM could ask any merchant, with no names or details of this merchant.
Give its type (and options for a choice), the answer from the material if there is one, who raised it (im or merchant),
its subsection (discovery or features_functionality), the ID of the closest bank question if one is related, and why it
is new in at most 15 words. At most 8. Don't repeat the new questions already in the sheet.

Answer with one JSON object and nothing else:
{"answers": [{"id": "ID-0000", "answer": "...", "source": "label of the material", "evidence": "...", "confidence": "high"}],
 "new_questions": [{"question": "...", "type": "free_text", "options": [], "answer": "... or null",
   "source": "label of the material", "raised_by": "merchant", "subsection": "discovery", "closest_id": "ID-0000 or null",
   "reason": "..."}]}

Use question IDs exactly as listed. Never invent an ID. If nothing fits, return empty lists."""


@dataclass
class Material:
    label: str
    kind: str
    text: str


@dataclass
class Extraction:
    status: str  # ok | unavailable
    model: str | None = None
    answers: list[dict] = field(default_factory=list)  # id, answer, source, evidence, confidence, problem
    new_questions: list[dict] = field(default_factory=list)
    dropped: dict = field(default_factory=dict)  # counts of what was thrown away, by reason
    note: str | None = None

    def summary(self) -> dict:
        """What to keep in the run's trace: counts only, no answers or material."""
        return {"status": self.status, "model": self.model, "answers": len(self.answers),
                "new_questions": len(self.new_questions), "dropped": self.dropped, "note": self.note}


def question_lines(questions: list[Question]) -> str:
    """One line per question: id | type | question | options."""
    lines = []
    for q in questions:
        options = f" | options: {'; '.join(q.options)}" if q.options else ""
        lines.append(f"{q.question_id} | {E.QuestionType(q.type).value} | {one_line(q.text, 400)}{options}")
    return "\n".join(lines)


def _match_option(value: str, options: list[str]) -> str | None:
    wanted = value.strip().casefold()
    return next((o for o in options if o.strip().casefold() == wanted), None)


def _other(options: list[str]) -> str | None:
    return next((o for o in options if o.strip().casefold() == "other"), None)


FILLER = {"and", "or", "both", "also", "plus"}


def _options_in(text: str, options: list[str]) -> tuple[list[str], list[str]]:
    """The listed options named in a multi-choice answer (longest first, so 'Buy online, pick up in store'
    isn't split at its comma), and whatever else is left over."""
    found, rest = [], text
    for option in sorted(options, key=len, reverse=True):
        pattern = re.compile(r"(?<!\w)" + re.escape(option.strip()) + r"(?!\w)", re.IGNORECASE)
        if option.strip() and pattern.search(rest):
            found.append(option)
            rest = pattern.sub(" ", rest)
    leftovers = []
    for part in re.split(r"[|;,/]|\band\b|\bor\b", rest, flags=re.IGNORECASE):
        part = part.strip(" .:-()").strip()
        if part and part.casefold() not in FILLER and re.search(r"\w", part):
            leftovers.append(part)
    return found, leftovers


def normalize_answer(q: Question, raw) -> tuple[str | None, str | None]:
    """The answer in the question's format, and a note when it doesn't quite fit (it is kept anyway)."""
    if raw is None or (isinstance(raw, str) and not raw.strip()) or raw == []:
        return None, None
    kind = E.QuestionType(q.type)
    if kind is E.QuestionType.toggle:
        if isinstance(raw, bool):
            return ("TRUE" if raw else "FALSE"), None
        word = one_line(raw, 40).casefold().rstrip(".")
        if word in TRUE_WORDS:
            return "TRUE", None
        if word in FALSE_WORDS:
            return "FALSE", None
        return None, None  # a toggle answered with anything else isn't an answer
    if kind is E.QuestionType.single_choice:
        text = one_line(raw[0] if isinstance(raw, list) and raw else raw, MAX_ANSWER)
        if (match := _match_option(text, q.options)) is not None:
            return match, None
        if (other := _other(q.options)) is not None:
            return f"{other}: {text}", None
        return text, "not one of the listed options"
    if kind is E.QuestionType.multi_choice:
        texts = [one_line(i, MAX_ANSWER) for i in raw] if isinstance(raw, list) else [one_line(raw, MAX_ANSWER)]
        chosen, extra = [], []
        for text in texts:
            found, rest = _options_in(text, q.options)
            chosen += [o for o in found if o not in chosen]
            extra += rest
        ordered = [o for o in q.options if o in chosen]
        problem = None
        if extra:
            other = _other(q.options)
            if other is not None:
                ordered = [o for o in ordered if o != other] + [f"{other}: {', '.join(extra)}"]
            else:
                ordered += extra
                problem = "not all of it is one of the listed options"
        return (" | ".join(ordered) or None), problem
    if kind is E.QuestionType.number:
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            return (str(int(raw)) if float(raw).is_integer() else str(raw)), None
        text = one_line(raw, MAX_ANSWER)
        if re.fullmatch(r"[-+]?[\d,]+(\.\d+)?", text):
            return text.replace(",", ""), None
        return text, None  # e.g. "about 2 million": kept as written
    return one_line(raw, MAX_ANSWER), None


def _labels(materials: list[Material]) -> dict[str, str]:
    return {m.label.casefold(): m.label for m in materials}


def _source(value, labels: dict[str, str], fallback: str) -> str:
    return labels.get(one_line(value, 120).casefold(), fallback)


def extract_answers(model: ChatModel | None, materials: list[Material], sheet_questions: list[Question],
                    other_questions: list[Question], existing_new: list[str], merchant_name: str | None = None,
                    sanitize: bool = True) -> Extraction:
    """
    sheet_questions  the bank questions in the IM's sheet: the ones to answer
    other_questions  the rest of the active bank: answered only when the material answers them directly
    existing_new     the wording of new questions already in the sheet, so they aren't suggested again
    """
    if model is None:
        return Extraction(status="unavailable", note="Our model isn't configured (MODEL_BASE_URL, MODEL_NAME).")
    material_text = "\n\n".join(f'### {m.label} ({m.kind})\n"""\n{m.text.strip()}\n"""' for m in materials)
    user = (
        f"Questions in the IM's sheet (id | type | question | options):\n{question_lines(sheet_questions) or '(none)'}\n\n"
        "Other bank questions. Answer these only if the material answers them directly "
        f"(id | type | question | options):\n{question_lines(other_questions) or '(none)'}\n\n"
        "New questions already in the sheet (don't list these again):\n"
        + ("\n".join(f"- {one_line(t, MAX_QUESTION)}" for t in existing_new) or "(none)")
        + f"\n\nMaterial:\n{material_text}"
    )
    try:
        reply = model.chat([{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}],
                           max_tokens=4000, timeout=MODEL_TIMEOUT)
        data = parse_json_object(reply)
    except ModelError as exc:
        return Extraction(status="unavailable", model=model.model, note=f"Our model didn't answer: {exc}.")

    clean = lambda text: scrub_contacts(text) if sanitize else text  # noqa: E731
    labels = _labels(materials)
    fallback = materials[0].label if len(materials) == 1 else "material"
    in_sheet = {q.question_id: q for q in sheet_questions}
    others = {q.question_id: q for q in other_questions}
    result = Extraction(status="ok", model=model.model)
    dropped = {"unknown_id": 0, "repeated_id": 0, "not_an_answer": 0, "other_bank_limit": 0,
               "repeats_a_question": 0, "new_limit": 0}
    seen: set[str] = set()
    other_count = 0
    for item in _as_list(data.get("answers")):
        if not isinstance(item, dict):
            continue
        qid = one_line(item.get("id"), 20)
        q = in_sheet.get(qid) or others.get(qid)
        if q is None:
            dropped["unknown_id"] += 1
            continue
        if qid in seen:
            dropped["repeated_id"] += 1
            continue
        value, problem = normalize_answer(q, item.get("answer"))
        if value is None:
            dropped["not_an_answer"] += 1
            continue
        if qid in others:
            if other_count >= MAX_OTHER_BANK:
                dropped["other_bank_limit"] += 1
                continue
            other_count += 1
        seen.add(qid)
        confidence = one_line(item.get("confidence"), 10).casefold()
        result.answers.append({
            "id": qid,
            "in_sheet": qid in in_sheet,
            "answer": clean(value),
            "source": _source(item.get("source"), labels, fallback),
            "evidence": clean(one_line(item.get("evidence"), MAX_EVIDENCE)),
            "confidence": confidence if confidence in CONFIDENCE else "medium",
            "problem": problem,
        })

    known_texts = [q.text for q in sheet_questions] + [q.text for q in other_questions] + list(existing_new)
    for item in _as_list(data.get("new_questions")):
        if not isinstance(item, dict):
            continue
        text = clean(scrub_name(one_line(item.get("question"), MAX_QUESTION), merchant_name))
        if not text:
            continue
        if any(same_question(text, known, SAME_QUESTION) for known in known_texts):
            dropped["repeats_a_question"] += 1
            continue
        if len(result.new_questions) >= MAX_NEW:
            dropped["new_limit"] += 1
            continue
        known_texts.append(text)
        kind = one_line(item.get("type"), 20).casefold()
        kind = kind if kind in {t.value for t in E.QuestionType} else "free_text"
        options = [one_line(o, 80) for o in _as_list(item.get("options")) if one_line(o, 80)]
        if kind in ("single_choice", "multi_choice") and len(options) < 2:
            kind, options = "free_text", []
        if kind not in ("single_choice", "multi_choice"):
            options = []
        answer = item.get("answer")
        answer = clean(one_line(answer, MAX_ANSWER)) if answer not in (None, "", "null") else None
        closest = one_line(item.get("closest_id"), 20)
        raised_by = one_line(item.get("raised_by"), 10).casefold()
        subsection = NEW_SUBSECTIONS.get(one_line(item.get("subsection"), 40).casefold(), E.Subsection.discovery)
        result.new_questions.append({
            "question": text,
            "type": kind,
            "options": options,
            "answer": answer,
            "source": _source(item.get("source"), labels, fallback),
            "raised_by": raised_by if raised_by in ("im", "merchant") else "other",
            "subsection": subsection.value,
            "closest_id": closest if closest in in_sheet or closest in others else None,
            "reason": clean(scrub_name(one_line(item.get("reason"), MAX_REASON), merchant_name)),
        })
    result.dropped = {k: v for k, v in dropped.items() if v}
    return result


def _as_list(value) -> list:
    return value if isinstance(value, list) else []


def as_dict(extraction: Extraction) -> dict:
    return asdict(extraction)
