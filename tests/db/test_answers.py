import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from imcp.app.main import create_app
from imcp.db import enums as E
from imcp.db.models import Generation, Instance, Source
from imcp.scope.additions import ADDITIONS_LABEL
from imcp.scope.answers import AnswersRecordRequest, AnswersStartRequest, record_answers, start_answers
from imcp.scope.runs import RunError, StartRequest, start_run
from tests.db.conftest import session_on
from tests.db.test_scope import CAPITAL, COLUMN, SETTINGS, TOKENS, loaded, plan, record
from tests.fakes import FakeModel
from tests.test_sheet_plan import FakeTab

HEADER = ["id", "enum", "question", "options", "answer", "notes", "priority", "subsection", "channels", "pillars",
          "category", "platform"]
SHEET_ID = "1AbCdEfGhIjK"
QUEUE_ON = SETTINGS.model_copy(update={"FLAG_CANDIDATE_QUEUE": True})
CALL = "Call summary, Oct 24"
MATERIAL = "SECRET-MATERIAL: they are moving processors, need tokens migrated, insurer pays most of each job."
REPLY = {
    "answers": [
        {"id": "ID-0001", "answer": "Moving off their current processor", "source": CALL, "evidence": "moving processors",
         "confidence": "high"},
        {"id": "ID-0003", "answer": "yes", "source": CALL, "evidence": "tokens must move", "confidence": "high"},
        {"id": "ID-0006", "answer": "Portable", "source": CALL, "evidence": "technicians in vans", "confidence": "medium"},
    ],
    "new_questions": [
        {"question": "Can one job be paid partly by an insurer and partly by the customer?", "type": "toggle",
         "answer": "TRUE", "source": CALL, "raised_by": "merchant", "subsection": "discovery",
         "closest_id": "ID-0003", "reason": "insurance jobs have two payers"},
    ],
}


def scope_sheet(session, model=None, settings=SETTINGS, **plan_kw):
    """A sheet made by /create-scope (CAPITAL tags, plus token migration by topic), as a fake tab."""
    run_id = start_run(loaded(session), settings, model or TOKENS,
                       StartRequest(tags=CAPITAL, context="They migrate tokens."))["draft_id"]
    planned = plan(session, run_id, header_row=HEADER, **plan_kw)
    tab = FakeTab(COLUMN, width=12, tab=7)
    tab.rows[0] = list(HEADER)
    tab.apply(planned["requests"])
    record(session, run_id, sheet_question_ids=[v or "" for v in tab.column(0)], sheet_id=SHEET_ID)
    return tab, planned


def column(tab, name):
    i = tab.rows[0].index(name)
    return [str(r[i]) if r[i] is not None else "" for r in tab.rows]


def start_request(tab, **kw):
    header = [h for h in tab.rows[0] if h is not None]
    columns = {n: column(tab, n) for n in ("answer", "source", "confidence", "status", "ai_note") if n in header}
    body = dict(sheet_id=SHEET_ID, tab_sheet_id=7, column_count=len(tab.rows[0]), row_count=len(tab.rows),
                header_row=header, id_column=[v or "" for v in tab.column(0)], columns=columns,
                material=[{"label": CALL, "kind": "summary", "text": MATERIAL}])
    body.update(kw)
    return AnswersStartRequest(**body)


def run_answers(session, tab, settings=SETTINGS, reply=REPLY, share=True, **kw):
    out = start_answers(session, settings, FakeModel(reply), start_request(tab, **kw))
    tab.apply(out["requests"])
    rec = record_answers(session, settings, out["draft_id"], AnswersRecordRequest(
        sheet_url=f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit", id_column=[v or "" for v in tab.column(0)],
        share_new_questions=share))
    return out, rec


def test_answers_fill_the_sheet_and_suggest_additions(session):
    tab, _ = scope_sheet(session)
    out, rec = run_answers(session, tab)
    s = out["summary"]
    assert s["filled"] == 2 and s["conflicts"] == [] and s["review_columns_added"] == ["source", "confidence", "status", "ai_note"]
    assert s["added_from_bank"] == [{"id": "ID-0006", "question": "Terminal form factor", "answer": "Portable"}]
    assert s["new_questions"][0]["id"] == "NEW-0001" and s["model"] == "fake-model"
    answer = tab.rows[0].index("answer")
    by_id = {r[0]: r for r in tab.rows if r[0]}
    assert by_id["ID-0001"][answer] == "Moving off their current processor" and by_id["ID-0003"][answer] == "TRUE"
    assert by_id["ID-0004"][answer] is None  # nothing in the material for it
    assert tab.column(0)[-3:] == [None, "ID-0006", "NEW-0001"] and tab.rows[-3][2] == ADDITIONS_LABEL
    assert rec["ok"] and rec["filled"] == 2 and rec["added"] == {"from_bank": 1, "new_questions": 1}
    assert rec["open_priority_1"] == {"count": 1, "first": [{"id": "ID-0004", "question": "Primary driver for Capital?"}]}
    assert rec["queue"] == {"on": False, "shared": True, "sent": 0} and session.scalars(select(Instance)).all() == []
    assert rec["feedback_url"].endswith("entry.1=" + out["draft_id"])


def test_the_material_and_answers_are_never_stored(session):
    tab, _ = scope_sheet(session)
    out, _ = run_answers(session, tab, settings=QUEUE_ON)
    stored = json.dumps([g.trace for g in session.scalars(select(Generation))])
    stored += json.dumps([[i.statement, i.answer_value, i.extraction] for i in session.scalars(select(Instance))])
    stored += json.dumps([s.ref for s in session.scalars(select(Source))])
    assert "SECRET-MATERIAL" not in stored and "Moving off their current processor" not in stored
    trace = session.get(Generation, out["draft_id"]).trace
    assert trace["material"][0]["kind"] == "summary" and len(trace["material"][0]["sha256"]) == 64
    assert trace["stage"] == "recorded" and trace["merchant_name"] is None


def test_new_questions_go_to_the_queue_when_it_is_on(session):
    tab, _ = scope_sheet(session)
    _, rec = run_answers(session, tab, settings=QUEUE_ON)
    [inst] = session.scalars(select(Instance)).all()
    assert rec["queue"] == {"on": True, "shared": True, "sent": 1}
    assert inst.statement == "Can one job be paid partly by an insurer and partly by the customer?"
    assert inst.answer_value is None and inst.review_status == E.ReviewStatus.pending
    assert inst.speaker_role == E.SpeakerRole.merchant and inst.act_type == E.ActType.question
    assert inst.extraction["sheet_ref"] == "NEW-0001" and inst.extraction["im_status"] == "suggested"
    assert inst.extraction["closest_id"] == "ID-0003" and inst.extraction["type"] == "toggle"
    source = session.get(Source, inst.source_id)
    assert source.chat_kind == E.ChatKind.brief and SHEET_ID in source.ref


def test_a_second_run_sees_what_the_im_did_and_keeps_their_answers(session):
    tab, _ = scope_sheet(session)
    run_answers(session, tab, settings=QUEUE_ON)
    status, question, answer = (tab.rows[0].index(n) for n in ("status", "question", "answer"))
    new_row = next(r for r in tab.rows if r[0] == "NEW-0001")
    new_row[question] = "Can a single job have two payers, such as an insurer and the customer?"
    new_row[status] = "confirmed"
    capital = next(r for r in tab.rows if r[0] == "ID-0004")
    capital[answer] = "TRUE"  # typed by the IM (a toggle in the test bank)
    reply = {"answers": [{"id": "ID-0004", "answer": "no", "source": "Call 2"},
                         {"id": "ID-0003", "answer": "TRUE", "source": "Call 2"}],
             "new_questions": [{"question": "Do fleet customers pay monthly invoices by bank transfer?", "source": "Call 2"}]}
    out, rec = run_answers(session, tab, settings=QUEUE_ON, reply=reply,
                           new_rows=[{"id": "NEW-0001", "question": new_row[question]}],
                           material=[{"label": "Call 2", "kind": "notes", "text": "second call"}])
    s = out["summary"]
    assert s["im_review_seen"] == {"confirmed": 1} and s["review_columns_added"] == []
    assert s["conflicts"] == [{"id": "ID-0004", "question": "Primary driver for Capital?", "yours": "TRUE",
                               "found": "FALSE", "source": "Call 2"}]
    assert s["agreed_with_yours"] == 1 and capital[answer] == "TRUE"
    assert tab.column(0)[-3:] == ["ID-0006", "NEW-0001", "NEW-0002"]
    assert [r[question] for r in tab.rows].count(ADDITIONS_LABEL) == 1
    first = next(i for i in session.scalars(select(Instance)) if i.extraction["sheet_ref"] == "NEW-0001")
    assert first.extraction["im_status"] == "confirmed" and first.extraction["im_wording"].startswith("Can a single job")
    assert rec["queue"]["sent"] == 1


def test_removed_new_questions_are_noted(session):
    tab, _ = scope_sheet(session)
    run_answers(session, tab, settings=QUEUE_ON)
    tab.rows = [r for r in tab.rows if r[0] != "NEW-0001"]  # the IM deleted the row
    out = start_answers(session, QUEUE_ON, FakeModel({"answers": []}), start_request(tab))
    assert out["summary"]["im_review_seen"] == {"removed": 1}
    [inst] = session.scalars(select(Instance)).all()
    assert inst.extraction["im_status"] == "removed"


def test_columns_must_be_passed_as_read(session):
    tab, _ = scope_sheet(session)
    req = start_request(tab, columns={"answer": ["notes", ""]})
    with pytest.raises(RunError) as err:
        start_answers(session, SETTINGS, FakeModel(REPLY), req)
    assert err.value.status == 422 and "whose header is 'answer'" in err.value.detail["error"]
    run_answers(session, tab)
    with pytest.raises(RunError) as err:  # the review columns exist now, so they must come too
        start_answers(session, SETTINGS, FakeModel(REPLY), start_request(tab, columns={"answer": column(tab, "answer")}))
    assert "source, confidence, status, ai_note" in err.value.detail["error"]


def test_a_sheet_we_dont_know_needs_the_merchant_name(session):
    loaded(session)
    tab = FakeTab(["id", "ID-0001"], width=12, tab=7)
    tab.rows[0] = list(HEADER)
    with pytest.raises(RunError) as err:
        start_answers(session, SETTINGS, FakeModel(REPLY), start_request(tab))
    assert err.value.status == 422
    out = start_answers(session, SETTINGS, FakeModel(REPLY), start_request(tab, merchant_name="Example Co"))
    rec = record_answers(session, SETTINGS, out["draft_id"], AnswersRecordRequest(
        sheet_url="u", id_column=[v or "" for v in tab.apply(out["requests"]).column(0)]))
    assert rec["filled"] == 1


def test_no_model_answer_means_nothing_is_written(session):
    tab, _ = scope_sheet(session)
    before = len(session.scalars(select(Generation)).all())
    with pytest.raises(RunError) as err:
        start_answers(session, SETTINGS, None, start_request(tab))
    assert err.value.status == 503 and "Nothing was written" in err.value.detail["error"]
    assert len(session.scalars(select(Generation)).all()) == before


def test_material_size_is_limited():
    with pytest.raises(ValueError):
        AnswersStartRequest(sheet_id=SHEET_ID, tab_sheet_id=7, column_count=13, row_count=5, header_row=HEADER,
                            id_column=["id"], material=[{"label": "a", "text": "x" * 100_000},
                                                        {"label": "b", "text": "x" * 60_000}])


# --- topic gaps in /create-scope ----------------------------------------------------------------

LOYALTY = FakeModel({"topics": ["loyalty"], "additions": [],
                     "uncovered_topics": [{"topic": "loyalty", "question": "Do you run a loyalty or rewards program?",
                                           "type": "toggle"}]})


def test_topic_gaps_become_suggested_additions(session):
    out = start_run(loaded(session), SETTINGS, LOYALTY, StartRequest(tags=CAPITAL, context="They want loyalty points"))
    assert out["topic_matching"]["gap_questions"] == [{"id": "NEW-0001", "topic": "loyalty",
                                                       "question": "Do you run a loyalty or rewards program?"}]
    planned = plan(session, out["draft_id"], header_row=HEADER)
    assert planned["suggested_additions"] == {"label_row": 6, "rows": 1}
    tab = FakeTab(COLUMN, width=12, tab=7)
    tab.rows[0] = list(HEADER)
    tab.apply(planned["requests"])
    assert tab.column(0)[-2:] == [None, "NEW-0001"] and tab.rows[-2][2] == ADDITIONS_LABEL
    assert tab.rows[-1][2] == "Do you run a loyalty or rewards program?" and tab.rows[-1][12] == "topic gap: loyalty"
    assert tab.rows[-1][6] is None  # no priority, so a priority filter never hides it
    rec = record(session, out["draft_id"], sheet_question_ids=[v or "" for v in tab.column(0)])
    assert rec["ok"] and rec["suggested_additions"] == 1 and rec["queue"] == {"on": False, "shared": False, "sent": 0}
    prompt = rec["call_prompt"]
    assert prompt["priorities"] == [1] and prompt["text"].startswith("Answer these scoping questions")
    assert "ID-0001: Project Background" in prompt["text"] and "NEW-0001: Do you run a loyalty" in prompt["text"]


def test_topic_gaps_can_be_dropped_and_are_queued_when_on(session):
    out = start_run(loaded(session), QUEUE_ON, LOYALTY, StartRequest(tags=CAPITAL, context="They want loyalty points"))
    dropped = plan(session, out["draft_id"], header_row=HEADER, remove_ids=["NEW-0001"])
    assert dropped["removed_ids"] == ["NEW-0001"] and dropped["suggested_additions"] is None
    kept = plan(session, out["draft_id"], header_row=HEADER)
    tab = FakeTab(COLUMN, width=12, tab=7)
    tab.rows[0] = list(HEADER)
    tab.apply(kept["requests"])
    from imcp.scope.runs import RecordRequest, record_run
    rec = record_run(session, QUEUE_ON, out["draft_id"], RecordRequest(
        merchant_name="Example Co", sheet_id=SHEET_ID, sheet_url="u", sheet_question_ids=[v or "" for v in tab.column(0)],
        share_new_questions=True))
    [inst] = session.scalars(select(Instance)).all()
    assert rec["queue"] == {"on": True, "shared": True, "sent": 1} and inst.extraction["topic"] == "loyalty"
    assert inst.speaker_role == E.SpeakerRole.im and session.get(Source, inst.source_id).chat_kind == E.ChatKind.notes
    assert "loyalty points" not in json.dumps(session.get(Generation, out["draft_id"]).trace)  # the notes aren't kept


def test_api_answers_flow(connection):
    app = create_app(settings=SETTINGS, db_check=lambda: {"ok": True}, session_factory=lambda: session_on(connection),
                     model=FakeModel(REPLY))
    client = TestClient(app)
    tab, _ = scope_sheet(session_on(connection))
    started = client.post("/answers/runs", json=start_request(tab).model_dump())
    assert started.status_code == 200, started.text
    body = started.json()
    tab.apply(body["requests"])
    rec = client.post(f"/answers/runs/{body['draft_id']}/record",
                      json={"sheet_url": "u", "id_column": [v or "" for v in tab.column(0)]}).json()
    assert rec["ok"] and rec["filled"] == 2
    assert client.post("/answers/runs/not-a-uuid/record", json={"sheet_url": "u", "id_column": ["id"]}).status_code == 404


def test_nothing_is_queued_without_the_ims_consent(session):
    tab, _ = scope_sheet(session)
    out, rec = run_answers(session, tab, settings=QUEUE_ON, share=False)
    assert out["summary"]["review_queue_on"] is True
    assert rec["queue"] == {"on": True, "shared": False, "sent": 0} and session.scalars(select(Instance)).all() == []


def test_api_answers_as_a_job(connection):
    import threading

    gate = threading.Event()

    class SlowModel(FakeModel):
        def chat(self, messages, **kw):
            gate.wait(5)
            return super().chat(messages, **kw)

    app = create_app(settings=SETTINGS, db_check=lambda: {"ok": True}, session_factory=lambda: session_on(connection),
                     model=SlowModel(REPLY))
    client = TestClient(app)
    tab, _ = scope_sheet(session_on(connection))
    started = client.post("/answers/jobs?wait=0.1", json=start_request(tab).model_dump()).json()
    assert started["pending"] is True
    gate.set()
    done = client.get(f"/answers/jobs/{started['job_id']}?wait=5").json()
    assert done["pending"] is False and done["summary"]["filled"] == 2 and done["requests"]
    assert client.get("/answers/jobs/00000000-0000-0000-0000-000000000000?wait=0").status_code == 404


def test_api_job_errors_come_back_when_asked(connection):
    app = create_app(settings=SETTINGS, db_check=lambda: {"ok": True}, session_factory=lambda: session_on(connection),
                     model=None)
    client = TestClient(app)
    tab, _ = scope_sheet(session_on(connection))
    res = client.post("/answers/jobs?wait=5", json=start_request(tab).model_dump())
    assert res.status_code == 503 and "Nothing was written" in res.text
