from types import SimpleNamespace

from imcp.db import enums as E
from imcp.proposal.answers import feature_rows, in_scope, pick_answers


def q(qid, text, type_="free_text", subsection="discovery", priority=1):
    return SimpleNamespace(question_id=qid, text=text, type=E.QuestionType(type_), subsection=E.Subsection(subsection),
                           priority=priority)


BANK = {x.question_id: x for x in [
    q("ID-0083", "Project Background", subsection="introduction"),
    q("ID-0084", "Project Goals & Objectives", subsection="introduction"),
    q("ID-0001", "Which regions are in scope?"),
    q("ID-0002", "Current PSP?", priority=2),
    q("ID-0003", "Is 3DS in scope?", "toggle", "features_functionality"),
    q("ID-0004", "Tokenization", "toggle", "features_functionality"),
    q("ID-0005", "Which payment methods?", "multi_choice", "features_functionality"),
    q("ID-0006", "Is MOTO in scope?", "toggle", "features_functionality", priority=1),
]}

IDS = ["ID-0083", "ID-0084", "ID-0001", "ID-0002", "ID-0003", "ID-0004", "ID-0005", "ID-0006", "ID-9999", "NEW-0001", "", "ID-0001"]
COLUMNS = {
    "answer": ["Moving from a legacy PSP", "Launch in Q1", "UK and NL", "Acme PSP", "yes", "No", "iDEAL | Cards", "", "x", "Partly by insurer", "", "dup"],
    "status": ["", "confirmed", "suggested", "rejected", "", "", "suggested", "", "", "", "", ""],
    "source": ["", "Call summary", "Call summary", "Call summary", "", "", "Email", "", "", "", "", ""],
    "question": ["", "", "", "", "", "", "", "", "", "Can one job be paid by two parties?", "", ""],
}


def test_pick_answers_applies_the_rules():
    track = pick_answers("Project Scope", IDS, COLUMNS, BANK)
    by_id = {a.id: a for a in track.answers}
    assert by_id["ID-0083"].origin == "own" and by_id["ID-0083"].subsection == "introduction"
    assert by_id["ID-0084"].origin == "own"  # confirmed: the IM's own, even with a source
    assert by_id["ID-0001"].origin == "suggested" and by_id["ID-0001"].answer == "UK and NL"  # the duplicate row is ignored
    assert "ID-0002" not in by_id and track.skipped_rejected_ids == ["ID-0002"]
    assert by_id["ID-0005"].origin == "suggested"  # a source and not confirmed
    assert "ID-0006" not in by_id and track.open_p1_ids == ["ID-0006"]  # unanswered P1
    assert track.not_loaded == ["ID-9999"]
    new = by_id["NEW-0001"]
    assert (new.question, new.subsection, new.type, new.origin) == ("Can one job be paid by two parties?", "discovery", "free_text", "own")
    assert track.suggested_ids == ["ID-0001", "ID-0005"]
    assert [a.id for a in track.by_subsection("discovery")] == ["ID-0001", "NEW-0001"]


def test_rejected_p1_counts_as_open():
    columns = {"answer": ["yes"], "status": ["rejected"]}
    track = pick_answers("T", ["ID-0006"], columns, BANK)
    assert track.open_p1_ids == ["ID-0006"] and track.skipped_rejected_ids == ["ID-0006"] and track.answers == []


def test_feature_rows_tick_toggles_and_show_text():
    track = pick_answers("Project Scope", IDS, COLUMNS, BANK)
    rows = {r["id"]: r for r in feature_rows(track)}
    assert rows["ID-0003"]["in_scope"] is True and rows["ID-0003"]["text"] == ""
    assert rows["ID-0004"]["in_scope"] is False and rows["ID-0004"]["text"] == ""  # shown even when toggled off
    assert rows["ID-0005"]["in_scope"] is None and rows["ID-0005"]["text"] == "iDEAL | Cards"
    assert "ID-0006" not in rows  # unanswered rows are left out
    assert rows["ID-0003"]["feature"] == "Is 3DS in scope?"


def test_a_toggle_with_a_written_answer_shows_the_text():
    track = pick_answers("T", ["ID-0003"], {"answer": ["Only for EU cards"]}, BANK)
    [row] = feature_rows(track)
    assert row["in_scope"] is None and row["text"] == "Only for EU cards"


def test_toggle_answers_read_yes_or_no_in_the_document():
    bank = {**BANK, "ID-0007": q("ID-0007", "Do you need to migrate tokens?", "toggle", "discovery")}
    track = pick_answers("T", ["ID-0007", "ID-0001"], {"answer": ["TRUE", "UK"]}, bank)
    assert [a.to_dict()["answer"] for a in track.answers] == ["Yes", "UK"]
    assert track.answers[0].answer == "TRUE"  # the sheet's value is kept for the search text and the trace


def test_in_scope_values():
    mk = lambda v: SimpleNamespace(answer=v)  # noqa: E731
    assert in_scope(mk("Yes")) is True and in_scope(mk(" TRUE ")) is True and in_scope(mk("✓")) is True
    assert in_scope(mk("no")) is False and in_scope(mk("Out of scope")) is False
    assert in_scope(mk("maybe later")) is None


def test_missing_columns_are_treated_as_empty():
    track = pick_answers("T", ["ID-0001", "ID-0003"], {"answer": ["Benelux"]}, BANK)
    assert [a.id for a in track.answers] == ["ID-0001"] and track.open_p1_ids == ["ID-0003"]
