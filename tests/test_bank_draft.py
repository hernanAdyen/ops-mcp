"""The draft of the bank's purpose and baseline columns: our model's output is checked, never trusted."""

from imcp.bank.draft import MAX_PURPOSE, draft_columns, question_lines, to_csv
from imcp.db import enums as E
from imcp.db.models import Question
from imcp.llm import ModelError
from tests.fakes import FakeModel


def q(qid, text, subsection="discovery", priority=1, notes=None, **tags):
    return Question(question_id=qid, text=text, type=E.QuestionType.free_text, options=[], notes=notes,
                    subsection=E.Subsection(subsection), priority=priority, channels=tags.get("channels", []),
                    pillars=[], categories=[], platforms=[])


BANK = [
    q("ID-0001", "What regions are in scope?", "introduction"),
    q("ID-0037", "Tipping", "features_functionality", 2, notes="Terminals only", channels=[E.Channel.IPP]),
    q("ID-0050", "What is your capture strategy?"),
]


def test_question_lines_give_the_model_what_it_needs():
    assert question_lines(BANK[:2]) == (
        "ID-0001 | Introduction | P1 | What regions are in scope? | no tags\n"
        "ID-0037 | Features & Functionality | P2 | Tipping | IPP | notes: Terminals only")


def test_items_are_checked_and_skipped_questions_are_listed():
    reply = {"items": [
        {"id": "ID-0001", "purpose": "Sets the regions\nthe integration  must support.", "baseline": True},
        {"id": "ID-0037", "purpose": "Decides whether terminals need a tipping flow.", "baseline": "N"},
        {"id": "ID-9999", "purpose": "made up", "baseline": False},
        {"id": "ID-0001", "purpose": "again", "baseline": False},
        "not an object",
    ]}
    model = FakeModel(reply)
    result = draft_columns(model, BANK)
    assert result.model == "fake-model" and [i["id"] for i in result.items] == ["ID-0001", "ID-0037", "ID-0050"]
    assert result.items[0] == {"id": "ID-0001", "question": "What regions are in scope?", "baseline": True,
                               "purpose": "Sets the regions the integration must support."}
    assert result.items[1]["baseline"] is False and result.items[2] == {
        "id": "ID-0050", "question": "What is your capture strategy?", "baseline": False, "purpose": ""}
    assert result.missing == ["ID-0050"]
    assert result.dropped == {"unknown_id": 1, "repeated_id": 1, "not_an_object": 1}
    assert result.summary()["baseline"] == 1
    assert "ID-0050 |" in model.calls[0][1]["content"] and model.timeouts == [180]


def test_bad_baseline_and_long_purpose():
    reply = {"items": [{"id": "ID-0001", "purpose": "word " * 200, "baseline": "maybe"}]}
    result = draft_columns(FakeModel(reply), BANK[:1])
    [item] = result.items
    assert item["baseline"] is False and result.dropped == {"bad_baseline": 1}
    assert 0 < len(item["purpose"]) <= MAX_PURPOSE and not item["purpose"].endswith(" ")


def test_batches_and_a_failed_batch_leaves_its_questions_missing():
    class Flaky(FakeModel):
        def chat(self, messages, **kw):
            super().chat(messages, **kw)
            if len(self.calls) == 2:
                raise ModelError("could not reach the model")
            return '{"items": [{"id": "ID-0001", "purpose": "Sets the regions.", "baseline": true}]}'

    model = Flaky({})
    result = draft_columns(model, BANK, batch=1)
    assert len(model.calls) == 3 and result.missing == ["ID-0037", "ID-0050"]
    assert result.notes == ["batch starting at ID-0037 failed: could not reach the model"]
    assert result.items[0]["purpose"] == "Sets the regions."


def test_csv_for_the_owner():
    result = draft_columns(FakeModel({"items": [{"id": "ID-0001", "purpose": "Sets the regions.", "baseline": True}]}),
                           BANK[:2])
    assert to_csv(result) == ("id,question,baseline,purpose\n"
                              "ID-0001,What regions are in scope?,Y,Sets the regions.\n"
                              "ID-0037,Tipping,N,\n")
