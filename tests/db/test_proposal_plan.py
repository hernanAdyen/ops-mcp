"""/propose-solution plan and record. Needs the test database."""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from imcp.app.main import create_app
from imcp.db import enums as E
from imcp.db.models import Generation, Opportunity, Source
from imcp.proposal.doc_plan import TICK
from imcp.proposal.draft import Draft
from imcp.proposal.runs import PlanRequest, ProposalStartRequest, RecordRequest, plan_proposal, record_proposal, start_proposal
from imcp.scope.runs import RunError
from tests.db.conftest import session_on
from tests.db.test_proposal_start import ONE_TAB, SETTINGS, SHEET, setup, tab
from tests.fake_doc import FakeDoc
from tests.fakes import FakeEmbedder
from tests.test_doc_plan import master

DRAFT = {
    "introduction": {"background": ["Northwind sells outdoor gear online."], "goals": "Go live in Q1."},
    "tracks": [{
        "name": "Project Scope",
        "technical_considerations": ["Tokens must be migrated before go-live.", "3DS2 applies to EU cards."],
        "integration_design": ["Drop-in with the Sessions flow."],
        "links": ["https://docs.adyen.com/online-payments/tokenization.md", "https://docs.adyen.com/online-payments/3d-secure"],
    }],
}


def started(session, embedder, tabs=ONE_TAB, **kw):
    out = start_proposal(session, SETTINGS, embedder, ProposalStartRequest(sheet_id=SHEET, tabs=tabs, **kw))
    return out["draft_id"]


def test_plan_fills_the_copy_from_the_draft_and_the_graph(session):
    embedder = FakeEmbedder()
    setup(session, embedder)
    draft_id = started(session, embedder)
    doc = master()
    out = plan_proposal(session, SETTINGS, draft_id, PlanRequest(tabs=ONE_TAB, draft=Draft(**DRAFT), outline=doc.outline()))
    doc.apply(out["requests"])
    text = doc.text()
    assert "{{" not in text
    paras = {p["text"]: p for p in doc.paragraphs()}
    assert "Northwind Outfitters Solution Proposal" in paras and "2.1 Project Scope" in paras
    assert "Northwind sells outdoor gear online." in paras and "Go live in Q1." in paras
    assert paras["Which regions are in scope?"]["bold"] and "UK and NL" in paras
    assert doc.tables()[2] == [["Feature & Functionality", "In Scope"], ["Tokenization", TICK], ["Which payment methods?", "Cards | iDEAL"]]
    assert "Tokens must be migrated before go-live." in paras and "Drop-in with the Sessions flow." in paras
    # links: the draft's first (a known page), then a docs-host page we don't know, then the brief fills up
    [planned_track] = out["tracks"]
    assert [l["url"] for l in planned_track["links"]][:2] == ["https://docs.adyen.com/online-payments/tokenization",
                                                             "https://docs.adyen.com/online-payments/3d-secure"]
    assert planned_track["links"][1]["title"] == "docs.adyen.com/online-payments/3d-secure"
    assert len(planned_track["links"]) <= 8 and paras["Tokenization"]["links"] == {"https://docs.adyen.com/online-payments/tokenization": "Tokenization"}
    assert planned_track["diagram"] == {"url": "https://img.example.com/tokens.png", "title": "Tokenization flow"}
    assert any(p["images"] == ["https://img.example.com/tokens.png"] for p in doc.paragraphs())
    trace = session.get(Generation, draft_id).trace
    assert trace["stage"] == "planned" and trace["plan"]["feature_rows"] == 2 and trace["plan"]["diagram_urls"][0].endswith("tokens.png")
    assert "Tokens must be migrated" not in json.dumps(trace)  # the draft is never stored


def test_intro_falls_back_to_the_sheet_answers(session):
    embedder = FakeEmbedder()
    setup(session, embedder)
    draft_id = started(session, embedder)
    draft = {**DRAFT, "introduction": {}}
    doc = master()
    out = plan_proposal(session, SETTINGS, draft_id, PlanRequest(tabs=ONE_TAB, draft=Draft(**draft), outline=doc.outline()))
    doc.apply(out["requests"])
    texts = [p["text"] for p in doc.paragraphs()]
    assert "Moving from a legacy PSP" in texts and "Launch online in Q1" in texts


def test_plan_refuses_bad_drafts_and_mismatched_tabs(session):
    embedder = FakeEmbedder()
    setup(session, embedder)
    draft_id = started(session, embedder)
    outline = master().outline()
    bad_link = {**DRAFT, "tracks": [{**DRAFT["tracks"][0], "links": ["https://example.com/blog"]}]}
    with pytest.raises(RunError, match="aren't documentation pages we know"):
        plan_proposal(session, SETTINGS, draft_id, PlanRequest(tabs=ONE_TAB, draft=Draft(**bad_link), outline=outline))
    wrong_track = {**DRAFT, "tracks": [{**DRAFT["tracks"][0], "name": "Other"}]}
    with pytest.raises(RunError, match="isn't in this run"):
        plan_proposal(session, SETTINGS, draft_id, PlanRequest(tabs=ONE_TAB, draft=Draft(**wrong_track), outline=outline))
    long = {**DRAFT, "tracks": [{**DRAFT["tracks"][0], "integration_design": ["x" * 1300]}]}
    with pytest.raises(RunError, match="limit is 1200"):
        plan_proposal(session, SETTINGS, draft_id, PlanRequest(tabs=ONE_TAB, draft=Draft(**long), outline=outline))
    token = {**DRAFT, "tracks": [{**DRAFT["tracks"][0], "integration_design": ["Use {{Track}} here"]}]}
    with pytest.raises(RunError, match="template token"):
        plan_proposal(session, SETTINGS, draft_id, PlanRequest(tabs=ONE_TAB, draft=Draft(**token), outline=outline))
    other_tabs = [tab("Other", ["ID-0001"], ["x"])]
    with pytest.raises(RunError, match="same tabs as at start"):
        plan_proposal(session, SETTINGS, draft_id, PlanRequest(tabs=other_tabs, draft=Draft(**DRAFT), outline=outline))
    with pytest.raises(RunError, match="no /propose-solution run"):
        plan_proposal(session, SETTINGS, "00000000-0000-0000-0000-000000000000", PlanRequest(tabs=ONE_TAB, draft=Draft(**DRAFT), outline=outline))


def test_two_tracks_fill_the_template_and_add_a_block(session):
    embedder = FakeEmbedder()
    tracks = [{"name": "Online", "channels": ["ECOM"], "pillars": [], "categories": [], "platforms": []},
              {"name": "In-store", "channels": ["IPP"], "pillars": [], "categories": [], "platforms": []}]
    setup(session, embedder, tracks=tracks)
    tabs = [tab("Online", ["ID-0083", "ID-0001", "ID-0003"], ["Background here", "UK", "yes"]),
            tab("In-store", ["ID-0002", "ID-0004"], ["S1F2 terminals", "yes"])]
    draft_id = started(session, embedder, tabs=tabs)
    draft = {"introduction": {"background": ["Two tracks."], "goals": []},
             "tracks": [{"name": "Online", "technical_considerations": ["Online point."], "integration_design": ["Drop-in."],
                         "links": ["https://docs.adyen.com/online-payments/tokenization"]},
                        {"name": "In-store", "technical_considerations": ["Store point."], "integration_design": ["Terminal API."],
                         "links": ["https://docs.adyen.com/point-of-sale/tipping"]}]}
    doc = master()
    out = plan_proposal(session, SETTINGS, draft_id, PlanRequest(tabs=tabs, draft=Draft(**draft), outline=doc.outline()))
    doc.apply(out["requests"])
    assert "{{" not in doc.text()
    h2 = [p["text"] for p in doc.paragraphs() if p["style"] == "HEADING_2"]
    assert h2 == ["1.4 Project Background", "1.5 Project Goals & Objectives", "2.1 Online Scope", "2.2 In-store Scope",
                  "3.1 Online Solution", "3.2 In-store Solution"]
    assert [t["name"] for t in out["tracks"]] == ["Online", "In-store"]
    assert out["tracks"][1]["diagram"]["url"] == "https://img.example.com/tipping.png"
    assert out["summary"]["tracks"] == 2 and out["summary"]["blocks_added"] == 2
    texts = [p["text"] for p in doc.paragraphs()]
    assert "Store point." in texts and "Terminal API." in texts and "Tipping" in texts


def test_record_finishes_the_run_and_points_at_the_document(session):
    embedder = FakeEmbedder()
    setup(session, embedder)
    draft_id = started(session, embedder)
    with pytest.raises(RunError, match="Plan the document first"):
        record_proposal(session, SETTINGS, draft_id, RecordRequest(doc_id="1DocIdXXXXXX", doc_url="https://docs.google.com/document/d/1DocIdXXXXXX/edit"))
    plan_proposal(session, SETTINGS, draft_id, PlanRequest(tabs=ONE_TAB, draft=Draft(**DRAFT), outline=master().outline()))
    rec = record_proposal(session, SETTINGS, draft_id, RecordRequest(doc_id="1DocIdXXXXXX", doc_url="https://docs.google.com/document/d/1DocIdXXXXXX/edit"))
    assert rec["ok"] and rec["merchant"] == "Northwind Outfitters"
    [t] = rec["tracks"]
    assert t["suggested_used"] == ["ID-0001"] and t["open_priority_1"]["questions"][0]["id"] == "ID-0002" and t["diagram"] is True
    assert rec["plan"]["links_used"] and rec["leftover_tokens"] == []
    gen = session.get(Generation, draft_id)
    assert gen.trace["stage"] == "recorded" and gen.output_ref.endswith("/edit")
    [src] = session.scalars(select(Source).where(Source.type == E.SourceType.proposal)).all()
    assert src.ref == "doc:1DocIdXXXXXX" and src.opportunity_id == gen.opportunity_id
    with pytest.raises(RunError, match="already recorded"):
        record_proposal(session, SETTINGS, draft_id, RecordRequest(doc_id="1DocIdXXXXXX", doc_url="x"))


def test_record_creates_the_deal_for_an_unknown_sheet(session):
    embedder = FakeEmbedder()
    setup(session, embedder, with_opportunity=False)
    draft_id = started(session, embedder, merchant_name="Contoso")
    plan_proposal(session, SETTINGS, draft_id, PlanRequest(tabs=ONE_TAB, draft=Draft(**DRAFT), outline=master().outline()))
    rec = record_proposal(session, SETTINGS, draft_id, RecordRequest(doc_id="1DocIdYYYYYY", doc_url="https://docs.google.com/document/d/1DocIdYYYYYY/edit"))
    assert rec["merchant"] == "Contoso"
    opp = session.scalar(select(Opportunity).where(Opportunity.alias == SHEET))
    assert opp is not None and session.get(Generation, draft_id).trace["merchant_name"] is None


def test_api_plan_and_record(connection):
    embedder = FakeEmbedder()
    with session_on(connection) as s:
        setup(s, embedder)
        s.commit()
    app = create_app(SETTINGS, db_check=lambda: {"ok": True}, session_factory=lambda: session_on(connection),
                     model=None, embedder=embedder)
    client = TestClient(app)
    tabs = [t.model_dump() for t in ONE_TAB]
    draft_id = client.post("/proposal/runs", json={"sheet_id": SHEET, "tabs": tabs}).json()["draft_id"]
    outline = [e.model_dump() for e in master().outline()]
    res = client.post(f"/proposal/runs/{draft_id}/doc-plan", json={"tabs": tabs, "draft": DRAFT, "outline": outline})
    assert res.status_code == 200 and res.json()["requests"]
    bad = client.post(f"/proposal/runs/{draft_id}/doc-plan", json={"tabs": tabs, "draft": {"tracks": []}, "outline": outline})
    assert bad.status_code == 422
    rec = client.post(f"/proposal/runs/{draft_id}/record", json={"doc_id": "1DocIdZZZZZZ", "doc_url": "https://docs.google.com/document/d/1DocIdZZZZZZ/edit"})
    assert rec.status_code == 200 and rec.json()["ok"]
