"""Answers from the IM's merchant material, with our model (/ops-answer-scope).

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
from imcp.bank.parse import ID_PATTERN
from imcp.scope.text import one_line, same_question, scrub_contacts, scrub_name
from imcp.scope.topics import ChatModel

MAX_MATERIAL_CHARS = 150_000
MAX_ANSWER = 500
MAX_EVIDENCE = 200
MAX_QUESTION = 300
MAX_REASON = 160
MAX_NEW = 8
MAX_OTHER_BANK = 15
MAX_PROSE = 15  # answers the second pass may add
MIN_PROSE_LINES = 2  # lines that aren't ID answers before the second pass is worth a call
MODEL_TIMEOUT = 240  # seconds: long material takes the model a while
SAME_QUESTION = 0.85  # similarity at which a "new" question is really one we already have
CONFIDENCE = ("high", "medium", "low")
NEW_SUBSECTIONS = {"discovery": E.Subsection.discovery, "features_functionality": E.Subsection.features_functionality}
TRUE_WORDS = {"true", "yes", "y", "in scope", "1"}
FALSE_WORDS = {"false", "no", "n", "not in scope", "out of scope", "0"}
# Said about any question, these are no answer: the cell stays empty and the question stays open.
UNDECIDED = {"undecided", "not decided", "not decided yet", "tbd", "tbc", "to be decided", "to be confirmed",
             "not discussed", "not yet discussed", "n/a", "na", "not applicable", "unknown", "unclear", "none given"}

SYSTEM_PROMPT = """You help an Adyen implementation manager (IM) fill in the scoping question sheet for a merchant project.
You get material the IM has from the merchant (call notes, a call summary or transcript, emails or documents),
the questions in the IM's sheet, and the other questions in our question bank.

Answer from the material only:
- Answer each question in the IM's sheet that the material answers. Leave out questions it doesn't answer and
  anything that is still undecided, 'to be confirmed', 'not discussed' or 'not applicable': those are no answer.
  Never guess.
- Answer one of the other bank questions only when the material answers it directly.
- The material may list answers by question ID (for example from a call-notes tool given our questions). Use those
  IDs, and treat 'not discussed' as no answer. Answer every listed ID that has an answer, in every section of the
  sheet (Discovery and Features & Functionality alike).
- The sheet tab you are filling is for one project track (named in the request). Material may be grouped by track
  (headings like 'Track: US'). Take answers for this tab from its own track's section and from notes that are not
  about a particular track. Ignore the sections of other tracks entirely: never put another track's facts in an
  answer, never combine tracks into one answer ('US: ...; France: ...' is wrong), and never answer other bank
  questions from another track's section.
- Before writing a new question, check both lists: if a listed question covers the topic, even in other words
  (for example 'Offline Processing' covers a remark about taking payments offline), answer that question instead.
- Some sheet questions already have a current answer, shown on their line. If the material agrees with it, repeats
  it, or repeats part of it without adding or changing anything (the same meaning, whatever the wording), answer
  with the single word same. Only when the material says something different, or adds something, give the new
  answer in full. If the material doesn't mention it, leave the question out.
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
its subsection (discovery or features_functionality), the ID of the bank question nearest to the topic if there is one
(closest_id), and why it is new in at most 15 words. At most 8. Don't repeat the new questions already in the sheet.

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
    prose_pass: dict = field(default_factory=dict)  # the second pass: status, answers, dropped (counts only)

    def summary(self) -> dict:
        """What to keep in the run's trace: counts only, no answers or material."""
        return {"status": self.status, "model": self.model, "answers": len(self.answers),
                "new_questions": len(self.new_questions), "dropped": self.dropped, "note": self.note,
                "prose_pass": self.prose_pass}


PROSE_PROMPT = """You help an Adyen implementation manager (IM) fill in the scoping question sheet for a merchant project.
A first reading of the material answered the questions it lists by ID. You get the questions that are still
unanswered, and the same material. Your one job: find the questions the material answers in passing, in its
prose, outside any list of IDs.

- Read every paragraph. When a remark clearly answers one of the listed questions, answer that question.
- Answer only questions from the list, and only from the material. Never guess. Leave out anything undecided,
  'to be confirmed', 'not discussed' or 'not applicable', and every question the material doesn't answer.
- A toggle gets TRUE only, and only when the material says the thing is wanted or in scope. Never answer FALSE
  here: a thing the material doesn't mention, rules out for another track, or leaves undecided is no answer.
  Most of the listed questions will have no answer; an empty list is a normal result.
- Use the question's format. toggle: TRUE or FALSE (TRUE means yes, or in scope). single_choice: exactly one of its
  options. multi_choice: one or more of its options, joined with " | ". number: a number. free_text: a short answer in
  your own words, at most 25 words.
- For each answer give the label of the material it came from, a short evidence note (at most 20 words, in your own
  words: no quotes, no people's names, no email addresses or phone numbers) and a confidence: high if the material
  says it directly, medium if it clearly implies it, low if you inferred it.

Answer with one JSON object and nothing else:
{"answers": [{"id": "ID-0000", "answer": "...", "source": "label of the material", "evidence": "...", "confidence": "high"}]}

Use question IDs exactly as listed. If nothing fits, return an empty list."""


def has_prose(materials: list[Material]) -> bool:
    """Whether the material has remarks outside ID answers: the second pass is only worth a call then."""
    lines = 0
    for m in materials:
        for line in m.text.splitlines():
            text = line.strip()
            if len(text) >= 40 and not ID_PATTERN.match(text):
                lines += 1
    return lines >= MIN_PROSE_LINES


def question_lines(questions: list[Question], current: dict[str, str] | None = None) -> str:
    """One line per question: id | type | question | options | purpose (when the bank has one) | current answer
    (when the sheet already has one)."""
    lines = []
    for q in questions:
        options = f" | options: {'; '.join(q.options)}" if q.options else ""
        purpose = f" | purpose: {one_line(q.purpose, 300)}" if q.purpose else ""
        answered = f" | current answer: {one_line(current[q.question_id], MAX_ANSWER)}" \
            if current and current.get(q.question_id) else ""
        lines.append(f"{q.question_id} | {E.QuestionType(q.type).value} | {one_line(q.text, 400)}{options}{purpose}{answered}")
    return "\n".join(lines)


SAME = "same"


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


def _undecided(raw) -> bool:
    return isinstance(raw, str) and one_line(raw, 60).casefold().strip(" .!").rstrip(".") in UNDECIDED


def toggle_value(raw) -> str | None:
    """TRUE/FALSE from a toggle answer: a yes/no word, or a sentence that starts with one ('Yes, web and apps')."""
    if isinstance(raw, bool):
        return "TRUE" if raw else "FALSE"
    text = one_line(raw, 80).casefold().rstrip(".")
    if text in TRUE_WORDS:
        return "TRUE"
    if text in FALSE_WORDS:
        return "FALSE"
    for phrase in sorted(FALSE_WORDS, key=len, reverse=True):  # "not in scope" before "no"
        if re.match(rf"{re.escape(phrase)}(?!\w)", text):
            return "FALSE"
    for phrase in sorted(TRUE_WORDS, key=len, reverse=True):
        if re.match(rf"{re.escape(phrase)}(?!\w)", text):
            return "TRUE"
    return None


def normalize_answer(q: Question, raw) -> tuple[str | None, str | None]:
    """The answer in the question's format, and a note when it doesn't quite fit (it is kept anyway)."""
    if raw is None or (isinstance(raw, str) and not raw.strip()) or raw == [] or _undecided(raw):
        return None, None
    kind = E.QuestionType(q.type)
    if kind is E.QuestionType.toggle:
        return toggle_value(raw), None  # a toggle answered with anything but yes or no isn't an answer
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
                    sanitize: bool = True, track: str | None = None, current: dict[str, str] | None = None) -> Extraction:
    """
    sheet_questions  the bank questions in the IM's sheet: the ones to answer
    other_questions  the rest of the active bank: answered only when the material answers them directly
    existing_new     the wording of new questions already in the sheet, so they aren't suggested again
    track            the tab's title (the project track this run fills), so material grouped by track is read right
    current          the sheet's current answer by question ID, for the questions already answered: the model
                     sees them and answers `same` when the material agrees, so a different wording of the same
                     fact isn't a conflict
    """
    current = {k: v for k, v in (current or {}).items() if v and str(v).strip()}
    if model is None:
        return Extraction(status="unavailable", note="Our model isn't configured (MODEL_BASE_URL, MODEL_NAME).")
    material_text = "\n\n".join(f'### {m.label} ({m.kind})\n"""\n{m.text.strip()}\n"""' for m in materials)
    track_line = (f"This sheet tab is for the project track named {one_line(track, 100)!r}. Use that track's section of "
                  "the material and the notes that apply to the whole project; ignore other tracks' sections.\n\n"
                  if track else "")
    user = (
        track_line
        + "Questions in the IM's sheet (id | type | question | options | purpose: what the answer is for | current answer, "
        "when the sheet already has one):\n"
        f"{question_lines(sheet_questions, current) or '(none)'}\n\n"
        "Other bank questions. Answer these only if the material answers them directly "
        f"(id | type | question | options | purpose):\n{question_lines(other_questions) or '(none)'}\n\n"
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
               "repeats_a_question": 0, "new_limit": 0, "answered_bank_question": 0, "covered_by_bank": 0}
    seen: set[str] = set()
    other_count = 0

    def add_answer(q: Question, value: str, source, evidence, confidence, problem) -> bool:
        nonlocal other_count
        if q.question_id in others:
            if other_count >= MAX_OTHER_BANK:
                dropped["other_bank_limit"] += 1
                return False
            other_count += 1
        seen.add(q.question_id)
        confidence = one_line(confidence, 10).casefold()
        result.answers.append({
            "id": q.question_id,
            "in_sheet": q.question_id in in_sheet,
            "answer": clean(value),
            "source": _source(source, labels, fallback),
            "evidence": clean(one_line(evidence, MAX_EVIDENCE)),
            "confidence": confidence if confidence in CONFIDENCE else "medium",
            "problem": problem,
        })
        return True

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
        raw = item.get("answer")
        if isinstance(raw, str) and raw.strip().casefold() == SAME:
            if qid not in current:  # nothing to agree with
                dropped["not_an_answer"] += 1
                continue
            value, problem = current[qid], None  # the sheet's wording, so the merge sees an agreement
        else:
            value, problem = normalize_answer(q, raw)
            if value is None:
                dropped["not_an_answer"] += 1
                continue
        add_answer(q, value, item.get("source"), item.get("evidence"), item.get("confidence"), problem)

    known_texts = [q.text for q in sheet_questions] + [q.text for q in other_questions] + list(existing_new)
    for item in _as_list(data.get("new_questions")):
        if not isinstance(item, dict):
            continue
        text = clean(scrub_name(one_line(item.get("question"), MAX_QUESTION), merchant_name))
        if not text:
            continue
        # A "new" question whose nearest bank question covers it is an answer to that question, not a new row:
        # the model names the bank question itself (closest_id). Only when the formats fit; else it stays new.
        closest = one_line(item.get("closest_id"), 20)
        covering = in_sheet.get(closest) or others.get(closest)
        if covering is not None:
            raw_answer = item.get("answer")
            if closest in in_sheet and (raw_answer in (None, "", "null") or _undecided(raw_answer)):
                dropped["covered_by_bank"] += 1  # no answer, and the sheet already asks the covering question
                continue
            if closest not in seen:
                value = _answer_for_covering(covering, item)
                if value is not None and add_answer(covering, value, item.get("source"), item.get("reason"), "medium", None):
                    dropped["answered_bank_question"] += 1
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
    # Second pass: the sheet questions still unanswered, against the material's prose. Narrow on purpose:
    # it can only add answers for those questions, so the first pass's answers and formats are untouched.
    unanswered = [q for q in sheet_questions if q.question_id not in seen]
    if unanswered and has_prose(materials):
        result.prose_pass = _prose_pass(model, materials, unanswered, material_text, track_line, add_answer)
    else:
        result.prose_pass = {"status": "skipped", "answers": 0}
    result.dropped = {k: v for k, v in dropped.items() if v}
    return result


def _prose_pass(model, materials: list[Material], unanswered: list[Question], material_text: str, track_line: str,
                add_answer) -> dict:
    """One focused call; returns counts for the trace. A failure leaves the first pass's answers as they are."""
    user = (track_line + "Unanswered questions in the IM's sheet (id | type | question | options | purpose):\n"
            f"{question_lines(unanswered)}\n\nMaterial:\n{material_text}")
    try:
        reply = model.chat([{"role": "system", "content": PROSE_PROMPT}, {"role": "user", "content": user}],
                           max_tokens=3000, timeout=MODEL_TIMEOUT)
        data = parse_json_object(reply)
    except ModelError as exc:
        return {"status": "unavailable", "answers": 0, "note": f"The second reading didn't run: {exc}"}
    allowed = {q.question_id: q for q in unanswered}
    counts = {"status": "ok", "answers": 0,
              "dropped": {"unknown_id": 0, "not_an_answer": 0, "toggle_not_from_prose": 0, "limit": 0}}
    taken: set[str] = set()
    for item in _as_list(data.get("answers")):
        if not isinstance(item, dict):
            continue
        qid = one_line(item.get("id"), 20)
        q = allowed.get(qid)
        if q is None or qid in taken:
            counts["dropped"]["unknown_id"] += 1
            continue
        value, problem = normalize_answer(q, item.get("answer"))
        if value is None:
            counts["dropped"]["not_an_answer"] += 1
            continue
        # A toggle from prose is only ever TRUE, with the remark as evidence: a FALSE here is the model reading
        # silence, "not discussed" or "not for this track" as "no", which the first pass never does.
        confidence = one_line(item.get("confidence"), 10).casefold()
        if E.QuestionType(q.type) is E.QuestionType.toggle and (
                value == "FALSE" or not one_line(item.get("evidence"), MAX_EVIDENCE) or confidence == "low"):
            counts["dropped"]["toggle_not_from_prose"] += 1
            continue
        if counts["answers"] >= MAX_PROSE:
            counts["dropped"]["limit"] += 1
            continue
        taken.add(qid)
        add_answer(q, value, item.get("source"), item.get("evidence"), item.get("confidence"), problem)
        counts["answers"] += 1
    counts["dropped"] = {k: v for k, v in counts["dropped"].items() if v}
    return counts


def _answer_for_covering(q: Question, item: dict) -> str | None:
    """
    The answer a 'new' question gives to the bank question that covers it, in that question's format.
    A toggle takes a yes/no; a free-text question takes the model's reason (what the merchant said) or
    the answer text; a choice question only takes an answer that is one of its options. None when the
    formats don't fit: the question then stays new.
    """
    kind = E.QuestionType(q.type)
    answer = item.get("answer")
    if answer in (None, "", "null") or _undecided(answer):
        return None
    if kind is E.QuestionType.toggle:
        return toggle_value(answer) if one_line(item.get("type"), 20).casefold() == "toggle" else None
    if kind is E.QuestionType.free_text:
        reason = one_line(item.get("reason"), MAX_ANSWER)
        text = reason if reason and toggle_value(answer) is not None else one_line(answer, MAX_ANSWER)
        return text or None
    value, problem = normalize_answer(q, answer)
    return value if value is not None and problem is None else None


def _as_list(value) -> list:
    return value if isinstance(value, list) else []


def as_dict(extraction: Extraction) -> dict:
    return asdict(extraction)
