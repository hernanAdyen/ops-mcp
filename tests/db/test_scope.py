import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from imcp.app.main import create_app
from imcp.bank.load import load_bank
from imcp.bank.parse import parse_bank_csv
from imcp.config import AppSettings
from imcp.db import enums as E
from imcp.db.models import Generation, Merchant, Opportunity, Question
from imcp.scope.candidates import Tags, in_range, tag_matches
from imcp.scope.runs import PlanRequest, RecordRequest, RunError, StartRequest, plan_run, record_run, start_run
from tests.db.conftest import session_on
from tests.fakes import FakeModel
from tests.test_bank_parse import make_csv, row
from tests.test_sheet_plan import FakeTab

SETTINGS = AppSettings(
    DB_USER="imcp", DB_PASSWORD="pw", DB_NAME="imcp",
    QUESTION_BANK_URL="https://docs.google.com/spreadsheets/d/MASTER",
    FEEDBACK_FORM_URL="https://docs.google.com/forms/d/e/FORM/viewform?entry.1={generation_id}",
)

BANK = make_csv(
    row(qid="ID-0001", question="Project Background", enum="free_text", subsection="Introduction", priority="1",
        channels="", pillars="", category=""),
    row(qid="ID-0002", question="Is Tokenization in scope?", channels="ECOM, IPP", pillars="DIGITAL, PFS, UC",
        category="PAYIN", priority="2"),
    row(qid="ID-0003", question="Do you need to migrate tokens?", channels="ECOM, IPP", pillars="DIGITAL, PFS, UC",
        category="PAYIN", priority="3", subsection="Discovery"),
    row(qid="ID-0004", question="Primary driver for Capital?", channels="", pillars="PFS", category="CAPITAL",
        priority="1", subsection="Discovery"),
    row(qid="ID-0005", question="Daily CashOut limit?", enum="number", channels="", pillars="PFS",
        category="CASHOUT", priority="1"),
    row(qid="ID-0006", question="Terminal form factor", enum="multi_choice", options="Countertop | Portable",
        channels="IPP", pillars="UC", category="PAYIN", priority="1"),
)
CAPITAL = Tags(pillars=[E.Pillar.PFS], categories=[E.Category.CAPITAL])
TOKENS = FakeModel({"topics": ["token migration"], "uncovered_topics": ["loyalty"],
                    "additions": [{"id": "ID-0003", "topic": "token migration", "reason": "Notes mention moving tokens"}]})
COLUMN = ["id", "ID-0001", "ID-0002", "ID-0003", "ID-0004", "ID-0005", "ID-0006"]


def loaded(session):
    load_bank(session, parse_bank_csv(BANK), source_ref="bank.csv", apply=True)
    return session


def ids(questions):
    return [q.question_id for q in questions]


# --- tag query --------------------------------------------------------------------------------

def test_tag_rule(session):
    loaded(session)
    assert ids(tag_matches(session, CAPITAL)) == ["ID-0001", "ID-0004"]  # intro has no tags: applies to everyone
    tags = Tags(channels=[E.Channel.ECOM, E.Channel.MOTO], categories=[E.Category.PAYIN])
    assert ids(tag_matches(session, tags)) == ["ID-0001", "ID-0003", "ID-0002"]  # by subsection, then ID


def test_priorities_and_subsections_limit_everything(session):
    loaded(session)
    tags = Tags(categories=[E.Category.PAYIN], priorities=[1, 2],
                subsections=[E.Subsection.introduction, E.Subsection.features_functionality])
    assert ids(tag_matches(session, tags)) == ["ID-0001", "ID-0002", "ID-0006"]
    assert ids(in_range(session, tags)) == ["ID-0001", "ID-0002", "ID-0005", "ID-0006"]


def test_deactivated_questions_are_never_offered(session):
    loaded(session).get(Question, "ID-0002").status = E.QuestionStatus.deactivated
    session.flush()
    assert "ID-0002" not in ids(in_range(session, Tags()))


# --- start ------------------------------------------------------------------------------------

def test_start_returns_a_summary_and_the_topic_additions(session):
    out = start_run(loaded(session), SETTINGS, TOKENS, StartRequest(tags=CAPITAL, context="They migrate tokens."))
    assert out["tag_matches"] == {"count": 2, "by_subsection": {"Introduction": 1, "Discovery": 1}, "by_priority": {"P1": 2}}
    assert out["topic_matching"]["status"] == "ok" and out["topic_matching"]["uncovered_topics"] == ["loyalty"]
    assert out["topic_matching"]["additions"] == [{"id": "ID-0003", "question": "Do you need to migrate tokens?",
                                                   "priority": 3, "subsection": "Discovery", "topic": "token migration",
                                                   "reason": "Notes mention moving tokens"}]
    assert out["total_questions"] == 3 and out["bank"]["master_sheet_url"].endswith("/MASTER")


def test_start_shows_the_model_the_scope_and_offers_only_what_the_tags_missed(session):
    model = FakeModel({"additions": []})
    start_run(loaded(session), SETTINGS, model, StartRequest(tags=CAPITAL, context="notes"))
    already, others = model.calls[0][1]["content"].split("Other questions, the only ones you may add")
    assert "ID-0001 |" in already and "ID-0004 |" in already  # read-only: what's covered
    assert "ID-0003 |" in others and "ID-0001 |" not in others and "ID-0004 |" not in others


def test_the_notes_are_never_stored(session):
    out = start_run(loaded(session), SETTINGS, TOKENS, StartRequest(tags=CAPITAL, context="SECRET merchant notes"))
    gen = session.get(Generation, out["draft_id"])
    assert "SECRET" not in str(gen.trace) and gen.trace["stage"] == "draft"


def test_start_without_context_or_model_still_works(session):
    loaded(session)
    assert start_run(session, SETTINGS, None, StartRequest(tags=CAPITAL))["topic_matching"]["status"] == "skipped"
    out = start_run(session, SETTINGS, None, StartRequest(tags=CAPITAL, context="notes"))
    assert out["topic_matching"]["status"] == "unavailable" and out["total_questions"] == 2


def test_start_needs_a_loaded_bank(session):
    with pytest.raises(RunError) as err:
        start_run(session, SETTINGS, None, StartRequest())
    assert err.value.status == 409


# --- plan -------------------------------------------------------------------------------------

def started(session, model=TOKENS):
    return start_run(loaded(session), SETTINGS, model, StartRequest(tags=CAPITAL, context="They migrate tokens."))["draft_id"]


def plan(session, run_id, **kw):
    return plan_run(session, run_id, PlanRequest(tab_sheet_id=7, column_count=12, id_column=COLUMN, **kw))


def sheet_after(result):
    """Column A and found_by after playing the plan's batch on a simulated sheet."""
    tab = FakeTab(COLUMN, width=12, tab=7).apply(result["requests"])
    return list(zip(tab.column(0), tab.column(12)))


def test_plan_merges_tags_and_topics_and_groups_by_section(session):
    run_id = started(session)
    out = plan(session, run_id)
    assert out["rows_kept"] == 3 and out["rows_deleted"] == 3
    assert sheet_after(out) == [("id", "found_by"), ("Introduction", None), ("ID-0001", "tags"),
                                ("Discovery", None), ("ID-0004", "tags"), ("ID-0003", "topic: token migration")]
    assert [s["section"] for s in out["sections"]] == ["Introduction", "Discovery"]
    assert session.get(Generation, run_id).trace["stage"] == "planned"


def test_plan_applies_the_ims_changes(session):
    run_id = started(session)
    out = plan(session, run_id, remove_ids=["ID-0003", "ID-0002"], add_ids=["ID-0006"])
    assert out["removed_ids"] == ["ID-0003"] and out["not_in_scope"] == ["ID-0002"] and out["added_ids"] == ["ID-0006"]
    assert sheet_after(out) == [("id", "found_by"), ("Introduction", None), ("ID-0001", "tags"),
                                ("Discovery", None), ("ID-0004", "tags"),
                                ("Features & Functionality", None), ("ID-0006", "added by you")]


def test_plan_refuses_a_bad_id_column(session):
    with pytest.raises(RunError) as err:
        plan_run(session, started(session), PlanRequest(tab_sheet_id=7, column_count=12, id_column=["ID-0001"]))
    assert err.value.status == 422


def test_plan_rejects_unknown_ids_before_any_edit(session):
    run_id = started(session)
    with pytest.raises(RunError) as err:
        plan(session, run_id, add_ids=["ID-0999"])
    assert err.value.status == 422 and err.value.detail["ids"] == ["ID-0999"]
    assert session.get(Generation, run_id).trace["stage"] == "draft"


def test_plan_notes_sheet_questions_that_are_not_loaded(session):
    out = plan_run(session, started(session), PlanRequest(tab_sheet_id=7, column_count=12,
                                                          id_column=COLUMN + ["ID-0145"]))
    assert out["in_sheet_not_loaded"] == ["ID-0145"]


def test_unknown_run(session):
    with pytest.raises(RunError) as err:
        plan(session, "00000000-0000-0000-0000-000000000000")
    assert err.value.status == 404
    with pytest.raises(RunError):
        plan(session, "not-a-uuid")


# --- record -----------------------------------------------------------------------------------

def record(session, run_id, **kw):
    base = dict(merchant_name="  Example   Co ", sheet_id="1AbCdEfGhIjK",
                sheet_url="https://docs.google.com/spreadsheets/d/1AbCdEfGhIjK",
                sheet_question_ids=["id", "ID-0001", "ID-0004", "ID-0003"])
    return record_run(session, SETTINGS, run_id, RecordRequest(**{**base, **kw}))


def test_record_needs_a_plan_first(session):
    with pytest.raises(RunError) as err:
        record(session, started(session))
    assert err.value.status == 409


def test_record_creates_merchant_opportunity_and_summary(session):
    run_id = started(session)
    plan(session, run_id)
    out = record(session, run_id)
    assert out["ok"] and out["questions"] == 3 and out["found_by"] == {"tags": 2, "topic": 1}
    assert out["by_subsection"] == {"Introduction": 1, "Discovery": 2}
    assert out["feedback_url"].endswith("entry.1=" + run_id)
    merchant = session.scalar(select(Merchant))
    assert (merchant.name, merchant.normalized_name) == ("Example   Co", "example co")
    opp = session.scalar(select(Opportunity).where(Opportunity.alias == "1AbCdEfGhIjK"))
    assert opp.pillars == [E.Pillar.PFS] and opp.categories == [E.Category.CAPITAL]
    gen = session.get(Generation, run_id)
    assert gen.opportunity_id == opp.opportunity_id and gen.trace["stage"] == "recorded"
    assert gen.trace["topic_matching"]["topics"] == ["token migration"]


def test_record_ignores_the_section_headings(session):
    run_id = started(session)
    plan(session, run_id)
    out = record(session, run_id, sheet_question_ids=["id", "Introduction", "ID-0001", "Discovery", "ID-0004", "ID-0003"])
    assert out["ok"] and out["questions"] == 3


def test_record_reports_mismatches(session):
    run_id = started(session)
    plan(session, run_id)
    out = record(session, run_id, sheet_question_ids=["id", "ID-0001", "ID-0002"])
    assert out["ok"] is False
    assert out["mismatches"] == {"missing_from_sheet": ["ID-0003", "ID-0004"], "in_sheet_but_not_selected": ["ID-0002"],
                                  "out_of_order": [], "suggested_additions_missing": []}


def test_record_reports_rows_out_of_order(session):
    """The read-back check also catches a layout gone wrong, like the filtered sort of 2026-10-25."""
    run_id = started(session)
    plan(session, run_id)
    out = record(session, run_id, sheet_question_ids=["id", "ID-0001", "ID-0003", "ID-0004"])
    assert out["ok"] is False and out["mismatches"]["out_of_order"] == ["ID-0003", "ID-0004"]


def test_plan_keeps_the_tabs_filter(session):
    flt = {"range": {"sheetId": 7, "startRowIndex": 0, "endRowIndex": 7, "startColumnIndex": 0, "endColumnIndex": 12},
           "filterSpecs": [{"columnIndex": 6, "filterCriteria": {"hiddenValues": ["2", "3"]}}]}
    out = plan(session, started(session), basic_filter=flt)
    assert out["filter"] == "kept" and out["requests"][0] == {"clearBasicFilter": {"sheetId": 7}}
    assert sheet_after(out) == [("id", "found_by"), ("Introduction", None), ("ID-0001", "tags"),
                                ("Discovery", None), ("ID-0004", "tags"), ("ID-0003", "topic: token migration")]
    assert out["requests"][-1]["setBasicFilter"]["filter"]["range"]["endRowIndex"] == 6


def test_same_merchant_name_is_one_merchant(session):
    first, second = started(session), start_run(session, SETTINGS, None, StartRequest(tags=CAPITAL))["draft_id"]
    for run_id, sheet in ((first, "1AbCdEfGhIjK"), (second, "2ZyXwVuTsRqP")):
        plan(session, run_id)
        record(session, run_id, sheet_id=sheet, merchant_name="EXAMPLE co" if run_id == second else "Example Co")
    assert len(session.scalars(select(Merchant)).all()) == 1 and len(session.scalars(select(Opportunity)).all()) == 2


def test_a_recorded_run_cannot_be_replanned(session):
    run_id = started(session)
    plan(session, run_id)
    record(session, run_id)
    with pytest.raises(RunError) as err:
        plan(session, run_id)
    assert err.value.status == 409


# --- API --------------------------------------------------------------------------------------

def api(connection, model=TOKENS):
    app = create_app(SETTINGS, db_check=lambda: {"ok": True}, session_factory=lambda: session_on(connection), model=model)
    return TestClient(app)


def test_api_full_flow(connection):
    loaded(session_on(connection))
    client = api(connection)
    start = client.post("/scope/runs", json={"tags": {"pillars": ["PFS"], "categories": ["CAPITAL"]},
                                             "context": "They migrate tokens.", "merchant_name": "Example Co"}).json()
    run_id = start["draft_id"]
    plan_out = client.post(f"/scope/runs/{run_id}/sheet-plan",
                           json={"tab_sheet_id": 7, "column_count": 12, "id_column": COLUMN}).json()
    assert plan_out["rows_kept"] == 3
    out = client.post(f"/scope/runs/{run_id}/record", json={
        "merchant_name": "Example Co", "sheet_id": "1AbCdEfGhIjK", "sheet_url": "https://docs.google.com/x",
        "sheet_question_ids": ["id", "ID-0001", "ID-0004", "ID-0003"]}).json()
    assert out["ok"] and session_on(connection).get(Generation, run_id).trace["stage"] == "recorded"


def test_api_errors_carry_a_message(connection):
    client = api(connection)
    res = client.post("/scope/runs", json={})
    assert res.status_code == 409 and "isn't loaded" in res.json()["detail"]["error"]
    assert client.post("/scope/runs", json={"tags": {"channels": ["POS"]}}).status_code == 422


def test_health_can_check_the_model(connection):
    body = api(connection).get("/health", params={"check_model": "true"}).json()
    assert body["model"] == {"ok": True, "model": "fake-model", "latency_ms": 1}
    body = api(connection, model=None).get("/health", params={"check_model": "true"}).json()
    assert body["model"]["ok"] is False
