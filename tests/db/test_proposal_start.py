"""/propose-solution start: answers per track, the research brief from the graph. Needs the test database."""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from imcp.app.main import create_app
from imcp.bank.load import load_bank
from imcp.bank.parse import parse_bank_csv
from imcp.config import AppSettings
from imcp.db import enums as E
from imcp.db.models import Generation, Merchant, Opportunity
from imcp.graph.assets import load_assets
from imcp.graph.diagrams import load_diagrams
from imcp.graph.docs_index import parse_index, parse_rules, select_pages
from imcp.proposal.runs import ProposalStartRequest, TabIn, start_proposal
from imcp.scope.runs import RunError
from tests.db.conftest import session_on
from tests.fakes import FakeEmbedder
from tests.test_bank_parse import make_csv, row

SETTINGS = AppSettings(DB_USER="u", DB_PASSWORD="p", DB_NAME="d", DOCS_INDEX_URL="https://docs.adyen.com/llms.txt")
SHEET = "1ProposalSheetId"

BANK = make_csv(
    row(qid="ID-0083", question="Project Background", enum="free_text", subsection="Introduction"),
    row(qid="ID-0084", question="Project Goals & Objectives", enum="free_text", subsection="Introduction"),
    row(qid="ID-0001", question="Which regions are in scope?", enum="free_text", subsection="Discovery", channels="ECOM"),
    row(qid="ID-0002", question="Which terminals are in use?", enum="free_text", subsection="Discovery", channels="IPP", priority="1"),
    row(qid="ID-0003", question="Tokenization", enum="toggle", subsection="Features & Functionality", channels="ECOM"),
    row(qid="ID-0004", question="Tipping", enum="toggle", subsection="Features & Functionality", channels="IPP"),
    row(qid="ID-0005", question="Which payment methods?", enum="multi_choice", options="Cards | iDEAL",
        subsection="Features & Functionality"),
)

RULES = """prefix,include,max_depth,channels,pillars,categories,platforms,note
/,no,,,,,,
/online-payments,yes,,ECOM,,,,
/point-of-sale,yes,,IPP,,,,
"""
INDEX = """## Docs
- [Tokenization](https://docs.adyen.com/online-payments/tokenization.md): Tokenization of card details and saved payment methods for recurring payments.
- [Tipping](https://docs.adyen.com/point-of-sale/tipping.md): Let shoppers add a tip on the terminal.
- [Refund](https://docs.adyen.com/online-payments/refund.md): Refund a payment to the shopper.
"""
DIAGRAMS = """title,url,description,channels,pillars,categories,platforms,note
Tokenization flow,https://img.example.com/tokens.png,Tokenization of card details and stored payment methods for recurring payments,ECOM,,,,
Terminal tipping flow,https://img.example.com/tipping.png,Tip added on the terminal before payment,IPP,,,,
"""


def tab(name, ids, answers, status=None, source=None, question=None):
    columns = {"answer": ["answer"] + answers}
    if status is not None:
        columns["status"] = ["status"] + status
    if source is not None:
        columns["source"] = ["source"] + source
    if question is not None:
        columns["question"] = ["question"] + question
    return TabIn(name=name, id_column=["id"] + ids, columns=columns)


def setup(session, embedder, with_opportunity=True, tracks=None):
    load_bank(session, parse_bank_csv(BANK), source_ref="t", apply=True)
    sel = select_pages(parse_index(INDEX), parse_rules(RULES))
    load_assets(session, sel.pages, kind=E.AssetKind.doc_page, embedder=embedder, source_ref="r", apply=True)
    load_diagrams(session, embedder, csv_text=DIAGRAMS, source_ref="d", apply=True)
    if with_opportunity:
        m = Merchant(name="Northwind Outfitters", normalized_name="northwind outfitters")
        session.add(m)
        session.flush()
        session.add(Opportunity(merchant_id=m.merchant_id, alias=SHEET, channels=[E.Channel.ECOM, E.Channel.IPP],
                                tracks=tracks or []))
        session.flush()


ONE_TAB = [tab("Project Scope", ["ID-0083", "ID-0084", "ID-0001", "ID-0003", "ID-0005", "ID-0002"],
               ["Moving from a legacy PSP", "Launch online in Q1", "UK and NL", "yes", "Cards | iDEAL", ""],
               status=["", "", "suggested", "", "", ""], source=["", "", "Call summary", "", "", ""])]


def test_start_picks_answers_and_builds_the_brief(session):
    embedder = FakeEmbedder()
    setup(session, embedder)
    out = start_proposal(session, SETTINGS, embedder, ProposalStartRequest(sheet_id=SHEET, tabs=ONE_TAB))
    assert out["merchant"] == "Northwind Outfitters"
    assert out["introduction"] == {"background": "Moving from a legacy PSP", "goals": "Launch online in Q1"}
    [track] = out["tracks"]
    assert track["name"] == "Project Scope"
    assert [d["id"] for d in track["discovery"]] == ["ID-0001"] and track["discovery"][0]["origin"] == "suggested"
    assert [(f["id"], f["in_scope"], f["text"]) for f in track["features"]] == [("ID-0003", True, ""), ("ID-0005", None, "Cards | iDEAL")]
    assert track["suggested_used"] == ["ID-0001"]
    assert track["open_priority_1"] == {"count": 1, "questions": [{"id": "ID-0002", "question": "Which terminals are in use?"}]}
    brief = track["brief"]
    assert brief["doc_pages"][0]["url"] == "https://docs.adyen.com/online-payments/tokenization"
    assert brief["doc_pages"][0]["md_url"].endswith("/tokenization.md")
    assert brief["diagrams"][0]["url"] == "https://img.example.com/tokens.png"
    assert brief["known"] == [] and any("no ingested proposals" in n for n in brief["notes"])
    assert brief["docs_host"] == "docs.adyen.com"
    assert [r["id"] for r in brief["requirements"]] == ["ID-0001", "ID-0003", "ID-0005"]
    assert "technical_considerations" in brief["sections"] and "im_proposal_plan" in out["instructions"]
    gen = session.get(Generation, out["draft_id"])
    trace = gen.trace
    assert trace["stage"] == "draft" and trace["introduction_ids"] == ["ID-0083", "ID-0084"]
    t = trace["tracks"][0]
    assert t["used_ids"] == ["ID-0083", "ID-0084", "ID-0001", "ID-0003", "ID-0005"] and t["suggested_ids"] == ["ID-0001"]
    assert t["open_p1_ids"] == ["ID-0002"] and t["doc_urls"][0].endswith("/tokenization")
    # answers never go into the trace
    stored = json.dumps(trace)
    assert "legacy PSP" not in stored and "UK and NL" not in stored


def test_track_tags_narrow_the_search(session):
    embedder = FakeEmbedder()
    tracks = [{"name": "Online", "channels": ["ECOM"], "pillars": [], "categories": [], "platforms": []},
              {"name": "In-store", "channels": ["IPP"], "pillars": [], "categories": [], "platforms": []}]
    setup(session, embedder, tracks=tracks)
    tabs = [tab("Online", ["ID-0083", "ID-0001", "ID-0003"], ["Background here", "UK", "yes"]),
            tab("In-store", ["ID-0002", "ID-0004"], ["S1F2 terminals", "yes"])]
    out = start_proposal(session, SETTINGS, embedder, ProposalStartRequest(sheet_id=SHEET, tabs=tabs))
    online, store = out["tracks"]
    assert online["brief"]["tags"]["channels"] == ["ECOM"] and store["brief"]["tags"]["channels"] == ["IPP"]
    assert {d["url"] for d in online["brief"]["doc_pages"]} == {"https://docs.adyen.com/online-payments/tokenization",
                                                                "https://docs.adyen.com/online-payments/refund"}
    assert [d["url"] for d in store["brief"]["doc_pages"]] == ["https://docs.adyen.com/point-of-sale/tipping"]
    assert [d["url"] for d in store["brief"]["diagrams"]] == ["https://img.example.com/tipping.png"]
    assert out["introduction"] == {"background": "Background here", "goals": None}


def test_unknown_sheet_needs_the_merchant_name_and_uses_no_tag_filter(session):
    embedder = FakeEmbedder()
    setup(session, embedder, with_opportunity=False)
    with pytest.raises(RunError, match="merchant_name"):
        start_proposal(session, SETTINGS, embedder, ProposalStartRequest(sheet_id=SHEET, tabs=ONE_TAB))
    out = start_proposal(session, SETTINGS, embedder,
                         ProposalStartRequest(sheet_id=SHEET, merchant_name="Contoso", tabs=ONE_TAB))
    assert out["merchant"] == "Contoso" and out["tracks"][0]["brief"]["tags"] == {t: [] for t in ("channels", "pillars", "categories", "platforms")}
    assert len(out["tracks"][0]["brief"]["doc_pages"]) == 3


def test_start_refuses_bad_input(session):
    embedder = FakeEmbedder()
    setup(session, embedder)
    with pytest.raises(RunError, match="'id' header"):
        start_proposal(session, SETTINGS, embedder, ProposalStartRequest(
            sheet_id=SHEET, tabs=[TabIn(name="T", id_column=["ID-0001"], columns={"answer": ["answer", "x"]})]))
    with pytest.raises(RunError, match="whose header is 'answer'"):
        start_proposal(session, SETTINGS, embedder, ProposalStartRequest(
            sheet_id=SHEET, tabs=[TabIn(name="T", id_column=["id", "ID-0001"], columns={"answer": ["status", "x"]})]))
    with pytest.raises(RunError, match="'answer' column"):
        start_proposal(session, SETTINGS, embedder, ProposalStartRequest(
            sheet_id=SHEET, tabs=[TabIn(name="T", id_column=["id", "ID-0001"], columns={"status": ["status", "x"]})]))
    with pytest.raises(RunError, match="same name"):
        start_proposal(session, SETTINGS, embedder, ProposalStartRequest(sheet_id=SHEET, tabs=ONE_TAB + [
            TabIn(name="project scope", id_column=["id"], columns={"answer": ["answer"]})]))
    with pytest.raises(RunError, match="EMBEDDING_MODEL"):
        start_proposal(session, SETTINGS, None, ProposalStartRequest(sheet_id=SHEET, tabs=ONE_TAB))


def test_start_needs_a_loaded_bank(session):
    with pytest.raises(RunError, match="question bank"):
        start_proposal(session, SETTINGS, FakeEmbedder(), ProposalStartRequest(sheet_id=SHEET, tabs=ONE_TAB))


def test_api_start(connection):
    embedder = FakeEmbedder()
    with session_on(connection) as s:
        setup(s, embedder)
        s.commit()
    app = create_app(SETTINGS, db_check=lambda: {"ok": True}, session_factory=lambda: session_on(connection),
                     model=None, embedder=embedder)
    client = TestClient(app)
    res = client.post("/proposal/runs", json={"sheet_id": SHEET, "tabs": [t.model_dump() for t in ONE_TAB]})
    assert res.status_code == 200 and res.json()["tracks"][0]["brief"]["doc_pages"]
    bad = client.post("/proposal/runs", json={"sheet_id": SHEET, "tabs": [{"name": "T", "id_column": ["x"], "columns": {}}]})
    assert bad.status_code == 422
    with session_on(connection) as s:
        assert s.scalar(select(Generation.command).where(Generation.command == "propose-solution")) == "propose-solution"
