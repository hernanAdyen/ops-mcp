from imcp.db import enums as E
from imcp.db.models import Question
from imcp.scope.call_prompt import call_prompt


def q(qid, text, kind="free_text", options=(), priority=1):
    return Question(question_id=qid, text=text, type=E.QuestionType(kind), options=list(options), priority=priority,
                    subsection=E.Subsection.discovery)


QS = [q("ID-0001", "What regions are in scope?"), q("ID-0037", "Tipping", "toggle", priority=3),
      q("ID-0069", "Primary network connection?", "single_choice", ["Ethernet", "Wi-Fi", "Cellular"]),
      q("ID-0005", "User platforms", "multi_choice", ["iOS", "Android", "Web"])]


def test_priority_one_by_default_with_format_hints_and_new_questions():
    out = call_prompt(QS, [{"id": "NEW-0001", "question": "Do you run a loyalty program?"}])
    lines = out["text"].split("\n\n")[1].splitlines()
    assert lines == ["ID-0001: What regions are in scope?", "ID-0069: Primary network connection? (Ethernet / Wi-Fi / Cellular)",
                     "ID-0005: User platforms (iOS / Android / Web, more than one)", "NEW-0001: Do you run a loyalty program?"]
    assert out["questions"] == 4 and out["left_out"] == 1 and "not discussed" in out["text"]


def test_all_priorities():
    out = call_prompt(QS, priorities=())
    assert out["priorities"] == "all" and "ID-0037: Tipping (yes / no)" in out["text"]


def test_nothing_to_ask():
    assert call_prompt([], priorities=(1,))["text"] is None
