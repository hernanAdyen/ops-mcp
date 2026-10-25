from imcp.db import enums as E
from imcp.db.models import Question
from imcp.llm import ModelError
from imcp.scope.extract import MAX_NEW, MAX_OTHER_BANK, Material, extract_answers, normalize_answer, question_lines
from tests.fakes import FakeModel


def q(qid, text, kind="free_text", options=(), subsection="discovery", priority=1):
    return Question(question_id=qid, text=text, type=E.QuestionType(kind), options=list(options),
                    subsection=E.Subsection(subsection), priority=priority)


SHEET = [
    q("ID-0001", "What regions are in scope?"),
    q("ID-0037", "Tipping", "toggle", subsection="features_functionality"),
    q("ID-0050", "What is your capture strategy?", "multi_choice",
      ["Immediate capture", "Delayed automatic capture", "Manual capture"]),
    q("ID-0069", "Primary network connection from store?", "single_choice", ["Ethernet", "Wi-Fi", "Cellular"]),
]
OTHERS = [q("ID-0096", "Will reports be downloaded manually, or do you need automated ingestion?", "single_choice",
            ["Manual download", "Automated ingestion"])]
NOTES = [Material("Call summary, Oct 24", "summary", "US only. No tipping. Vans use cellular. Daily SFTP report.")]


def run(reply, **kw):
    model = FakeModel(reply)
    args = dict(materials=NOTES, sheet_questions=SHEET, other_questions=OTHERS, existing_new=[])
    args.update(kw)
    return extract_answers(model, **args), model


def test_the_prompt_has_the_sheet_the_rest_of_the_bank_and_the_material():
    _, model = run({"answers": [], "new_questions": []}, existing_new=["How are insurance jobs paid?"])
    system, user = model.calls[0]
    assert "Never guess" in system["content"] and "no people's names" in system["content"]
    sheet_part, rest = user["content"].split("Other bank questions")
    assert "ID-0069 | single_choice | Primary network connection from store? | options: Ethernet; Wi-Fi; Cellular" in sheet_part
    assert "ID-0096" in rest and "ID-0096" not in sheet_part
    assert "- How are insurance jobs paid?" in rest
    assert '### Call summary, Oct 24 (summary)\n"""\nUS only.' in rest


def test_answers_are_put_in_the_question_format_and_checked():
    reply = {"answers": [
        {"id": "ID-0001", "answer": "United States only", "source": "Call summary, Oct 24", "evidence": "US only",
         "confidence": "high"},
        {"id": "ID-0037", "answer": "no", "source": "call summary, oct 24", "evidence": "No tipping", "confidence": "HIGH"},
        {"id": "ID-0069", "answer": "cellular", "source": "?", "evidence": "vans", "confidence": "sure"},
        {"id": "ID-0050", "answer": "Manual capture", "source": "x", "evidence": "after the job"},
        {"id": "ID-0096", "answer": "Automated ingestion", "source": "Call summary, Oct 24", "evidence": "SFTP"},
        {"id": "ID-9999", "answer": "made up"},
        {"id": "ID-0001", "answer": "again"},
        {"id": "ID-0037", "answer": "maybe"},
    ]}
    result, _ = run(reply)
    got = {a["id"]: a for a in result.answers}
    assert result.status == "ok" and list(got) == ["ID-0001", "ID-0037", "ID-0069", "ID-0050", "ID-0096"]
    assert got["ID-0037"]["answer"] == "FALSE" and got["ID-0037"]["confidence"] == "high"
    assert got["ID-0037"]["source"] == "Call summary, Oct 24"  # matched case-insensitively
    assert got["ID-0069"]["answer"] == "Cellular" and got["ID-0069"]["confidence"] == "medium"
    assert got["ID-0069"]["source"] == "Call summary, Oct 24"  # one piece of material: unknown labels map to it
    assert got["ID-0096"]["in_sheet"] is False and got["ID-0001"]["in_sheet"] is True
    assert result.dropped == {"unknown_id": 1, "repeated_id": 2}


def test_toggles_that_arent_yes_or_no_are_not_answers():
    result, _ = run({"answers": [{"id": "ID-0037", "answer": "not decided yet"}]})
    assert result.answers == [] and result.dropped == {"not_an_answer": 1}


def test_choice_answers_outside_the_options_are_kept_with_a_note():
    value, problem = normalize_answer(SHEET[3], "4G router")
    assert value == "4G router" and problem == "not one of the listed options"
    other = q("ID-0102", "Cross channel flows?", "multi_choice",
              ["Buy online, pick up in store", "Buy online, return in store", "Other", "None"])
    assert normalize_answer(other, "buy online, pick up in store and curbside") == \
        ("Buy online, pick up in store | Other: curbside", None)


def test_other_bank_answers_are_limited():
    others = [q(f"ID-{i:04d}", f"Question {i}") for i in range(200, 230)]
    reply = {"answers": [{"id": o.question_id, "answer": "yes"} for o in others]}
    result, _ = run(reply, other_questions=others)
    assert len(result.answers) == MAX_OTHER_BANK and result.dropped == {"other_bank_limit": 30 - MAX_OTHER_BANK}


def test_new_questions_are_generic_checked_and_not_repeats():
    reply = {"new_questions": [
        {"question": "Can Safelite split one job between an insurer and the customer?", "type": "toggle",
         "answer": "yes", "source": "Call summary, Oct 24", "raised_by": "merchant", "subsection": "discovery",
         "closest_id": "ID-0050", "reason": "Safelite insurance jobs"},
        {"question": "What regions are in scope?", "type": "free_text"},  # a bank question
        {"question": "How are insurance jobs paid?", "type": "free_text"},  # already new in the sheet
        {"question": "Which fleet billing do you use?", "type": "single_choice", "options": ["Invoice"],
         "closest_id": "ID-7777", "raised_by": "someone", "subsection": "elsewhere"},
    ]}
    result, _ = run(reply, merchant_name="Safelite", existing_new=["How are insurance jobs paid?"])
    first, second = result.new_questions
    assert first["question"] == "Can the merchant split one job between an insurer and the customer?"
    assert first["reason"] == "the merchant insurance jobs" and first["closest_id"] == "ID-0050"
    assert first["type"] == "toggle" and first["answer"] == "yes" and first["raised_by"] == "merchant"
    assert second["type"] == "free_text" and second["options"] == []  # a choice needs two options
    assert second["closest_id"] is None and second["raised_by"] == "other" and second["subsection"] == "discovery"
    assert result.dropped == {"repeats_a_question": 2}


def test_at_most_eight_new_questions():
    topics = ["loyalty points", "gift cards", "insurance billing", "fleet invoices", "chargebacks", "kiosks",
              "subscriptions", "marketplaces", "currency hedging", "store credit", "warranty claims", "layaway"]
    reply = {"new_questions": [{"question": f"How do you handle {t}?"} for t in topics]}
    result, _ = run(reply)
    assert len(result.new_questions) == MAX_NEW and result.dropped == {"new_limit": 12 - MAX_NEW}


def test_contact_details_are_scrubbed_when_sanitizing():
    reply = {"answers": [{"id": "ID-0001", "answer": "US; contact jordan@example.com", "evidence": "call +1 614 555 0100"}]}
    on, _ = run(reply)
    assert on.answers[0]["answer"] == "US; contact [email]" and on.answers[0]["evidence"] == "call [phone]"
    off, _ = run(reply, sanitize=False)
    assert "jordan@example.com" in off.answers[0]["answer"]


def test_no_model_or_a_failure_is_unavailable():
    assert extract_answers(None, NOTES, SHEET, OTHERS, []).status == "unavailable"
    result, _ = run(ModelError("could not reach the model (ConnectError)"))
    assert result.status == "unavailable" and "ConnectError" in result.note


def test_the_summary_keeps_counts_only():
    reply = {"answers": [{"id": "ID-0001", "answer": "US only"}], "new_questions": [{"question": "Brand new topic?"}]}
    result, _ = run(reply)
    assert result.summary() == {"status": "ok", "model": "fake-model", "answers": 1, "new_questions": 1,
                                "dropped": {}, "note": None}


def test_question_lines():
    assert question_lines([SHEET[1]]) == "ID-0037 | toggle | Tipping"


def test_extraction_asks_for_a_long_timeout():
    _, model = run({"answers": []})
    assert model.timeouts == [240]


def test_answers_listed_by_id_are_used():
    _, model = run({"answers": []})
    assert "treat 'not discussed' as no answer" in model.calls[0][0]["content"]
