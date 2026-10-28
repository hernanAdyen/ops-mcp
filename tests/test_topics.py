from imcp.llm import ModelError
from imcp.scope.topics import MAX_ADDITIONS, match_topics, question_lines
from tests.fakes import FakeModel

QUESTIONS = [
    {"id": "ID-0057", "question": "Do you need to migrate tokens?", "priority": 3, "subsection": "Discovery",
     "tags": {"channels": ["ECOM", "IPP"], "categories": ["PAYIN"]}},
    {"id": "ID-0061", "question": "Is 3DS in scope?", "priority": 3, "subsection": "Features & Functionality",
     "tags": {}},
]


def test_no_context_means_no_model_call():
    model = FakeModel({})
    result = match_topics(model, "   ", QUESTIONS)
    assert result.status == "skipped" and model.calls == []


def test_contact_details_in_the_reply_are_scrubbed():
    reply = {"topics": ["token migration"],
             "additions": [{"id": "ID-0057", "topic": "token migration", "reason": "ops lead jordan@example.com wants it, call +1 614 555 0100"}],
             "uncovered_topics": [{"topic": "loyalty", "question": "Email ops@example.com about the points program?", "type": "free_text"}]}
    result = match_topics(FakeModel(reply), "notes", QUESTIONS)
    assert result.additions[0]["reason"] == "ops lead [email] wants it, call [phone]"
    assert result.gap_questions[0]["question"] == "Email [email] about the points program?"
    off = match_topics(FakeModel(reply), "notes", QUESTIONS, sanitize=False)
    assert "jordan@example.com" in off.additions[0]["reason"]


def test_no_model_configured():
    assert match_topics(None, "migrating tokens", QUESTIONS).status == "unavailable"


def test_picks_only_listed_questions():
    reply = {"topics": ["token migration"],
             "additions": [{"id": "ID-0057", "topic": "token migration", "reason": "Notes mention moving tokens"},
                           {"id": "ID-9999", "topic": "made up", "reason": "x"},
                           {"id": "ID-0057", "topic": "duplicate", "reason": "x"}],
             "uncovered_topics": ["loyalty"]}
    result = match_topics(FakeModel(reply), "They are migrating tokens from their current PSP.", QUESTIONS)
    assert result.status == "ok" and result.model == "fake-model"
    assert result.additions == [{"id": "ID-0057", "topic": "token migration", "reason": "Notes mention moving tokens"}]
    assert result.dropped_ids == ["ID-9999"] and result.uncovered_topics == ["loyalty"]


SELECTED = [{"id": "ID-0110", "question": "What is the primary driver for implementing Capital?", "priority": 1,
             "subsection": "Discovery", "tags": {"pillars": ["PFS"], "categories": ["CAPITAL"]}}]


def test_the_prompt_lists_the_notes_the_scope_and_the_other_questions():
    model = FakeModel({"topics": [], "additions": [], "uncovered_topics": []})
    match_topics(model, "Migrating tokens", QUESTIONS, selected=SELECTED)
    system, user = model.calls[0]
    assert system["role"] == "system" and "Never choose a question that is already in the scope" in system["content"]
    assert "follow-up questions needed to scope it" in system["content"]
    already, others = user["content"].split("Other questions, the only ones you may add")
    assert "Migrating tokens" in already
    assert "ID-0110 | P1 | Discovery | What is the primary driver for implementing Capital? | PFS · CAPITAL" in already
    assert "ID-0057 | P3 | Discovery | Do you need to migrate tokens? | ECOM, IPP · PAYIN" in others
    assert "ID-0061 | P3 | Features & Functionality | Is 3DS in scope? | no tags" in others
    assert "ID-0110" not in others


def test_questions_already_in_the_scope_are_never_added():
    reply = {"additions": [{"id": "ID-0110", "topic": "Capital", "reason": "x"},
                           {"id": "ID-0057", "topic": "token migration", "reason": "y"}]}
    result = match_topics(FakeModel(reply), "Capital and tokens", QUESTIONS, selected=SELECTED)
    assert [a["id"] for a in result.additions] == ["ID-0057"] and result.dropped_ids == ["ID-0110"]


def test_merchant_name_is_kept_out_of_topics_and_reasons():
    reply = {"topics": ["Acme tokens"], "additions": [
        {"id": "ID-0057", "topic": "ACME token move", "reason": "acme said they migrate tokens"}]}
    result = match_topics(FakeModel(reply), "Acme is migrating tokens", QUESTIONS, merchant_name="Acme")
    assert result.topics == ["the merchant tokens"]
    assert result.additions[0]["topic"] == "the merchant token move"
    assert "acme" not in result.additions[0]["reason"].lower()


def test_long_or_odd_values_are_cut_down():
    reply = {"topics": "not a list", "additions": [
        {"id": "ID-0057", "topic": "t" * 500, "reason": "r\n" * 500}, "not a dict"]}
    result = match_topics(FakeModel(reply), "notes", QUESTIONS)
    assert result.topics == [] and len(result.additions[0]["topic"]) == 60 and len(result.additions[0]["reason"]) == 160


def test_at_most_fifteen_additions():
    questions = [{"id": f"ID-{i:04d}", "question": f"Q{i}", "priority": 1, "subsection": "Discovery", "tags": {}}
                 for i in range(1, 30)]
    reply = {"additions": [{"id": q["id"], "topic": "t", "reason": "r"} for q in questions]}
    assert len(match_topics(FakeModel(reply), "notes", questions).additions) == MAX_ADDITIONS


def test_model_failure_falls_back_to_tags_only():
    result = match_topics(FakeModel(ModelError("could not reach the model (ConnectError)")), "notes", QUESTIONS)
    assert result.status == "unavailable" and "ConnectError" in result.note


def test_reply_wrapped_in_a_code_fence_is_fine():
    reply = '```json\n{"topics": ["3DS"], "additions": [{"id": "ID-0061", "topic": "3DS", "reason": "SCA"}]}\n```'
    assert match_topics(FakeModel(reply), "notes", QUESTIONS).additions[0]["id"] == "ID-0061"


def test_unparseable_reply_is_unavailable():
    assert match_topics(FakeModel("Sorry, I can't help."), "notes", QUESTIONS).status == "unavailable"


def test_question_lines_are_one_line_each():
    text = question_lines([{**QUESTIONS[0], "question": "Line one\nline two"}])
    assert text == "ID-0057 | P3 | Discovery | Line one line two | ECOM, IPP · PAYIN"
    with_purpose = question_lines([{**QUESTIONS[1], "purpose": "Decides the 3DS\nsetup."}])
    assert with_purpose == "ID-0061 | P3 | Features & Functionality | Is 3DS in scope? | no tags | purpose: Decides the 3DS setup."
