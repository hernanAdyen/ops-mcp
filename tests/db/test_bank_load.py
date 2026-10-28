from fastapi.testclient import TestClient
from sqlalchemy import func, select

from imcp.app.main import create_app
from imcp.bank.load import load_bank
from imcp.bank.parse import parse_bank_csv
from imcp.config import AppSettings
from imcp.db import enums as E
from imcp.db.models import BankLoadRun, Question, QuestionHistory
from tests.db.conftest import session_on
from tests.test_bank_parse import HEADER_V4, make_csv, row, row4

BANK = make_csv(
    row(qid="ID-0001", question="What regions are in scope?", enum="free_text"),
    row(qid="ID-0002", enum="multi_choice", options="iOS | Android | Web", question="User platforms",
        notes="Ask per app"),
    row(qid="ID-0003", question="Is 3DS in scope?"),
)


def load(session, text=BANK, apply=True):
    return load_bank(session, parse_bank_csv(text), source_ref="test.csv", apply=apply)


def history(session, qid):
    return session.scalars(select(QuestionHistory).where(QuestionHistory.question_id == qid)
                           .order_by(QuestionHistory.id)).all()


def test_dry_run_writes_nothing(session):
    report = load(session, apply=False)
    assert report.applied is False and report.run_id is None
    assert report.new == ["ID-0001", "ID-0002", "ID-0003"] and report.counts["active_after"] == 3
    assert session.scalar(select(func.count()).select_from(Question)) == 0
    assert session.scalar(select(func.count()).select_from(BankLoadRun)) == 0


def test_first_load_inserts_and_records_the_run(session):
    report = load(session)
    assert report.applied and report.counts["new"] == 3 and report.counts["invalid"] == 0
    q = session.get(Question, "ID-0002")
    assert q.type == E.QuestionType.multi_choice and q.options == ["iOS", "Android", "Web"]
    assert q.notes == "Ask per app" and q.status == E.QuestionStatus.active
    run = session.get(BankLoadRun, report.run_id)
    assert (run.status, run.seen, run.inserted, run.updated, run.invalid) == (E.RunStatus.succeeded, 3, 3, 0, 0)
    assert run.finished_at is not None and run.report["new"] == report.new


def test_loading_the_same_bank_again_changes_nothing(session):
    load(session)
    report = load(session)
    assert report.counts["unchanged"] == 3
    assert report.new == report.changed == report.deactivated == report.reactivated == []
    assert history(session, "ID-0001") == []


def test_changes_are_kept_in_history(session):
    load(session)
    changed = make_csv(
        row(qid="ID-0001", question="Which regions are in scope?", enum="free_text", channels="ECOM, IPP"),
        row(qid="ID-0002", enum="multi_choice", options="iOS | Android | Web", question="User platforms",
            notes="Ask per app"),
        row(qid="ID-0003", question="Is 3DS in scope?"),
    )
    report = load(session, changed)
    assert report.changed == [{"id": "ID-0001", "fields": ["text", "channels"]}]
    assert session.get(Question, "ID-0001").text == "Which regions are in scope?"
    [h] = history(session, "ID-0001")
    assert h.old["text"] == "What regions are in scope?" and h.new["text"] == "Which regions are in scope?"
    assert h.bank_load_run_id is not None


def test_missing_ids_are_deactivated_and_come_back(session):
    load(session)
    without_3 = make_csv(
        row(qid="ID-0001", question="What regions are in scope?", enum="free_text"),
        row(qid="ID-0002", enum="multi_choice", options="iOS | Android | Web", question="User platforms",
            notes="Ask per app"),
    )
    report = load(session, without_3)
    assert report.deactivated == ["ID-0003"] and report.counts["active_after"] == 2
    assert session.get(Question, "ID-0003").status == E.QuestionStatus.deactivated
    report = load(session)  # the row is back
    assert report.reactivated == ["ID-0003"] and report.counts["active_after"] == 3
    assert session.get(Question, "ID-0003").status == E.QuestionStatus.active
    assert [h.new["status"] for h in history(session, "ID-0003")] == ["deactivated", "active"]


def test_purpose_and_baseline_are_stored_and_a_change_is_in_history(session):
    load(session)
    with_columns = make_csv(
        row4(qid="ID-0001", question="What regions are in scope?", enum="free_text",
             purpose="Sets the regions the integration must support.", baseline="Y"),
        row4(qid="ID-0002", enum="multi_choice", options="iOS | Android | Web", question="User platforms",
             notes="Ask per app"),
        row4(qid="ID-0003", question="Is 3DS in scope?"),
        header=HEADER_V4,
    )
    report = load(session, with_columns)
    assert report.changed == [{"id": "ID-0001", "fields": ["purpose", "baseline"]}]
    assert report.counts["baseline"] == 1 and report.counts["unchanged"] == 2
    q = session.get(Question, "ID-0001")
    assert q.purpose == "Sets the regions the integration must support." and q.baseline is True
    [h] = history(session, "ID-0001")
    assert (h.old["baseline"], h.new["baseline"]) == (False, True) and h.old["purpose"] is None
    assert load(session, with_columns).counts["unchanged"] == 3  # same again: nothing changes


def test_a_retired_row_is_deactivated_in_place_and_comes_back_when_cleared(session):
    load(session)
    retired = make_csv(
        row4(qid="ID-0001", question="What regions are in scope?", enum="free_text"),
        row4(qid="ID-0002", enum="multi_choice", options="iOS | Android | Web", question="User platforms",
             notes="Ask per app"),
        row4(qid="ID-0003", question="Is 3DS in scope?", status="retired"),
        row4(qid="ID-0004", question="Never loaded", status="retired"),  # a new ID marked retired isn't loaded
        header=HEADER_V4,
    )
    report = load(session, retired)
    assert report.retired == ["ID-0003", "ID-0004"] and report.deactivated == ["ID-0003"] and report.new == []
    assert report.counts["retired"] == 2 and report.counts["active_after"] == 2
    assert session.get(Question, "ID-0003").status == E.QuestionStatus.deactivated
    assert session.get(Question, "ID-0004") is None
    report = load(session, retired)  # still retired: nothing more happens
    assert report.deactivated == [] and report.retired == ["ID-0003", "ID-0004"]
    report = load(session)  # the status is cleared (the plain bank has no status column)
    assert report.reactivated == ["ID-0003"] and session.get(Question, "ID-0003").status == E.QuestionStatus.active


def test_invalid_rows_are_skipped_and_loaded_questions_keep_their_last_good_version(session):
    load(session)
    broken = make_csv(
        row(qid="ID-0001", question="What regions are in scope?", enum="string"),  # invalid now
        row(qid="ID-0002", enum="multi_choice", options="iOS | Android | Web", question="User platforms",
            notes="Ask per app"),
        row(qid="ID-0003", question="Is 3DS in scope?"),
        row(qid="ID-0004", enum="single_choice", question="New but broken"),  # invalid, never loaded
    )
    report = load(session, broken)
    assert [(i["id"], i["kept_previous_version"]) for i in report.invalid] == [("ID-0001", True), ("ID-0004", False)]
    assert report.deactivated == [] and report.new == []
    assert session.get(Question, "ID-0001").type == E.QuestionType.free_text  # unchanged
    assert session.get(Question, "ID-0004") is None
    assert session.get(BankLoadRun, report.run_id).invalid == 2


def test_fatal_file_problem_changes_nothing(session):
    report = load(session, "question,priority\nHello,1\n")
    assert report.fatal and report.applied is False
    assert session.scalar(select(func.count()).select_from(BankLoadRun)) == 0


# --- API --------------------------------------------------------------------------------------

SETTINGS = AppSettings(DB_USER="imcp", DB_PASSWORD="pw", DB_NAME="imcp")


def api(connection):
    app = create_app(SETTINGS, db_check=lambda: {"ok": True}, session_factory=lambda: session_on(connection))
    return TestClient(app)


def test_api_dry_run_then_apply(connection):
    client = api(connection)
    dry = client.post("/bank/loads", json={"csv": BANK, "source_ref": "bank.csv"}).json()
    assert dry["applied"] is False and dry["counts"]["new"] == 3
    check = session_on(connection)
    assert check.scalar(select(func.count()).select_from(Question)) == 0

    done = client.post("/bank/loads", json={"csv": BANK, "source_ref": "bank.csv", "apply": True}).json()
    assert done["applied"] is True and done["run_id"]
    assert check.scalar(select(func.count()).select_from(Question)) == 3
    assert check.get(BankLoadRun, done["run_id"]).source_ref == "bank.csv"


def test_api_reports_fatal_problems(connection):
    res = api(connection).post("/bank/loads", json={"csv": "", "apply": True})
    assert res.status_code == 200 and res.json()["fatal"] == "the file is empty"
