"""Loading doc pages into the graph, and searching them. Needs the test database."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from imcp.app.main import create_app
from imcp.config import AppSettings
from imcp.db import enums as E
from imcp.db.models import Asset, IngestionRun, Node
from imcp.graph import load_docs
from imcp.graph.assets import load_assets
from imcp.graph.docs_index import Page, parse_index, parse_rules, select_pages
from imcp.graph.load_docs import load_doc_pages
from imcp.graph.search import nearest_assets
from imcp.llm import ModelError
from imcp.scope.runs import RunError
from tests.db.conftest import session_on
from tests.fakes import FakeEmbedder

RULES = """prefix,include,max_depth,channels,pillars,categories,platforms,note
/,no,,,,,,
/online-payments,yes,,ECOM,DIGITAL,PAYIN,PSP,
/point-of-sale,yes,,IPP,UC,PAYIN,PSP,
/reporting,yes,,,,REPORTING_RECONCILIATION,,
"""

INDEX = """## Online payments
- [Tokenization](https://docs.adyen.com/online-payments/tokenization.md): Store card details for recurring payments.
- [Refund](https://docs.adyen.com/online-payments/refund.md): Refund a payment to the shopper.
## In-person payments
- [Tipping](https://docs.adyen.com/point-of-sale/tipping.md): Let shoppers add a tip on the terminal.
## Reporting
- [Settlement details](https://docs.adyen.com/reporting/settlement-reconciliation.md): Reconcile settlement batches with reports.
- [Errors](https://docs.adyen.com/errors.md): Not selected by the rules.
"""

# The index's host decides which pages count (pages on other hosts are ignored), so the test index
# must sit on the same host as the pages. Nothing is fetched: the tests pass the text in.
SETTINGS = AppSettings(DB_USER="u", DB_PASSWORD="p", DB_NAME="d", DOCS_INDEX_URL="https://docs.adyen.com/llms.txt")


def pages(index=INDEX, rules=RULES):
    return select_pages(parse_index(index), parse_rules(rules))


def load(session, embedder, index=INDEX, rules=RULES, apply=True):
    sel = pages(index, rules)
    return load_assets(session, sel.pages, kind=E.AssetKind.doc_page, embedder=embedder, source_ref="rules.csv",
                       apply=apply, no_description=sel.no_description)


def count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def test_dry_run_reports_and_writes_nothing(session):
    embedder = FakeEmbedder()
    report = load(session, embedder, apply=False)
    assert report.applied is False and report.run_id is None
    assert report.counts["new"] == 4 and report.counts["to_embed"] == 4 and report.counts["selected"] == 4
    assert report.by_section == {"online-payments": 2, "point-of-sale": 1, "reporting": 1}
    assert count(session, Node) == 0 and count(session, IngestionRun) == 0
    assert embedder.calls == []  # a dry run costs no embedding calls


def test_apply_inserts_nodes_assets_embeddings_and_a_run(session):
    embedder = FakeEmbedder()
    report = load(session, embedder)
    assert report.applied and report.counts["new"] == 4 and len(report.new) == 4
    node = session.scalar(select(Node).where(Node.canonical_key == "https://docs.adyen.com/online-payments/tokenization"))
    assert node.type == E.NodeType.asset and node.status == E.Lifecycle.active
    assert node.label == "Tokenization" and node.description == "Store card details for recurring payments."
    assert node.attrs == {"tags": {"channels": ["ECOM"], "pillars": ["DIGITAL"], "categories": ["PAYIN"], "platforms": ["PSP"]},
                          "section": "online-payments", "rule": "/online-payments"}
    assert node.embedding is not None and len(list(node.embedding)) == FakeEmbedder.dim
    assert node.embedding_model == "fake-embedding" and node.embedded_at is not None
    asset = session.get(Asset, node.node_id)
    assert (asset.kind, asset.url, asset.title, asset.deprecated) == (E.AssetKind.doc_page, node.canonical_key, "Tokenization", False)
    run = session.get(IngestionRun, report.run_id)
    assert run.kind == "assets:doc_page" and run.status == E.RunStatus.succeeded and run.model == "fake-embedding"
    assert run.stats["new"] == 4 and run.stats["by_section"]["reporting"] == 1
    assert embedder.calls == [["Tokenization\nStore card details for recurring payments.",
                               "Refund\nRefund a payment to the shopper.",
                               "Tipping\nLet shoppers add a tip on the terminal.",
                               "Settlement details\nReconcile settlement batches with reports."]]


def test_loading_again_changes_nothing_and_embeds_nothing(session):
    embedder = FakeEmbedder()
    load(session, embedder)
    report = load(session, embedder)
    assert report.counts["unchanged"] == 4 and report.counts["to_embed"] == 0
    assert report.new == report.changed == report.deprecated == report.restored == []
    assert len(embedder.calls) == 1 and count(session, IngestionRun) == 2


def test_changed_description_is_updated_and_embedded_again(session):
    embedder = FakeEmbedder()
    load(session, embedder)
    changed = INDEX.replace("Store card details for recurring payments.", "Save payment details as tokens.")
    report = load(session, embedder, index=changed)
    assert report.changed == ["https://docs.adyen.com/online-payments/tokenization"] and report.counts["to_embed"] == 1
    assert embedder.calls[-1] == ["Tokenization\nSave payment details as tokens."]
    node = session.scalar(select(Node).where(Node.canonical_key == report.changed[0]))
    assert node.description == "Save payment details as tokens."


def test_changed_tags_update_without_embedding(session):
    embedder = FakeEmbedder()
    load(session, embedder)
    report = load(session, embedder, rules=RULES.replace("/online-payments,yes,,ECOM,", "/online-payments,yes,,ECOM;MOTO,"))
    assert len(report.changed) == 2 and report.counts["to_embed"] == 0
    node = session.scalar(select(Node).where(Node.canonical_key == "https://docs.adyen.com/online-payments/refund"))
    assert node.attrs["tags"]["channels"] == ["ECOM", "MOTO"]


def test_a_new_embedding_model_embeds_everything_again(session):
    load(session, FakeEmbedder())

    class Other(FakeEmbedder):
        model = "other-embedding"

    other = Other()
    report = load(session, other)
    assert report.counts["unchanged"] == 4 and report.counts["to_embed"] == 4 and len(other.calls) == 1
    assert {m for m in session.scalars(select(Node.embedding_model))} == {"other-embedding"}


def test_pages_that_drop_out_are_deprecated_not_deleted_and_come_back(session):
    embedder = FakeEmbedder()
    load(session, embedder)
    without_tipping = INDEX.replace("- [Tipping](https://docs.adyen.com/point-of-sale/tipping.md): Let shoppers add a tip on the terminal.\n", "")
    report = load(session, embedder, index=without_tipping)
    assert report.deprecated == ["https://docs.adyen.com/point-of-sale/tipping"] and count(session, Node) == 4
    node = session.scalar(select(Node).where(Node.canonical_key == report.deprecated[0]))
    assert node.status == E.Lifecycle.deactivated and node.valid_to is not None and session.get(Asset, node.node_id).deprecated
    again = load(session, embedder, index=without_tipping)
    assert again.deprecated == [] and again.counts["active_after"] == 3
    back = load(session, embedder)
    assert back.restored == ["https://docs.adyen.com/point-of-sale/tipping"] and back.counts["to_embed"] == 0
    session.refresh(node)
    assert node.status == E.Lifecycle.active and node.valid_to is None and not session.get(Asset, node.node_id).deprecated


def test_missing_descriptions_are_reported_not_loaded(session):
    index = INDEX + "- [Bare](https://docs.adyen.com/online-payments/bare.md)\n"
    report = load(session, FakeEmbedder(), index=index)
    assert report.no_description == ["https://docs.adyen.com/online-payments/bare"] and report.counts["new"] == 4


def test_embedding_failure_leaves_nothing_behind(session):
    report = load(session, FakeEmbedder(fail=ModelError("the embedding model returned HTTP 503")))
    assert report.applied is False and "HTTP 503" in report.fatal
    # The caller rolls back when applied is False; the run row is part of what gets rolled back.
    session.rollback()
    assert count(session, Node) == 0 and count(session, IngestionRun) == 0


def test_report_lists_are_capped(session):
    many = "\n".join(f"- [Page {i}](https://docs.adyen.com/reporting/p{i}.md): Report number {i}." for i in range(60))
    report = load(session, FakeEmbedder(), index=many)
    d = report.to_dict()
    assert report.counts["new"] == 60 and len(d["new"]) == 40 and d["lists_capped_at"] == 40


# --- search -------------------------------------------------------------------------------------

def test_search_ranks_by_embedding_within_tags(session):
    embedder = FakeEmbedder()
    load(session, embedder)
    found = nearest_assets(session, embedder, "recurring payments with stored card details")
    assert found[0]["url"] == "https://docs.adyen.com/online-payments/tokenization"
    assert set(found[0]) == {"url", "title", "description", "kind", "tags", "distance"}
    # IPP keeps the IPP page and the reporting page (no channel tag: applies to everyone), drops the ECOM pages
    only_ipp = nearest_assets(session, embedder, "recurring payments with stored card details", tags={"channels": ["IPP"]})
    assert {f["url"] for f in only_ipp} == {"https://docs.adyen.com/point-of-sale/tipping",
                                           "https://docs.adyen.com/reporting/settlement-reconciliation"}
    # a page with no value for a tag applies to everyone: reporting has no channel
    moto = nearest_assets(session, embedder, "settlement reports", tags={"channels": ["MOTO"]})
    assert [f["url"] for f in moto] == ["https://docs.adyen.com/reporting/settlement-reconciliation"]
    assert nearest_assets(session, embedder, "anything", kind=E.AssetKind.flow_diagram) == []
    assert nearest_assets(session, embedder, "anything", limit=2).__len__() == 2
    with pytest.raises(ValueError):
        nearest_assets(session, embedder, "x", tags={"colour": ["red"]})


def test_search_skips_deprecated_pages_and_other_models(session):
    embedder = FakeEmbedder()
    load(session, embedder)
    load(session, embedder, index=INDEX.replace("- [Tipping](https://docs.adyen.com/point-of-sale/tipping.md): Let shoppers add a tip on the terminal.\n", ""))
    assert all(f["url"] != "https://docs.adyen.com/point-of-sale/tipping" for f in nearest_assets(session, embedder, "tip on the terminal"))

    class Other(FakeEmbedder):
        model = "other-embedding"

    assert nearest_assets(session, Other(), "tip on the terminal") == []


# --- the whole load, through the app ------------------------------------------------------------

def test_load_doc_pages_fetches_the_index_and_needs_settings(session):
    fetched = []

    def fetch(url):
        fetched.append(url)
        return INDEX

    report = load_doc_pages(session, SETTINGS, FakeEmbedder(), rules_csv=RULES, source_ref="r.csv", apply=False, fetch=fetch)
    assert fetched == ["https://docs.adyen.com/llms.txt"] and report.counts["excluded_by_rules"] == 1
    assert report.counts["index_entries"] == 5
    with pytest.raises(RunError) as err:
        load_doc_pages(session, SETTINGS, FakeEmbedder(), rules_csv="prefix,include\n", source_ref=None, apply=False, fetch=fetch)
    assert err.value.status == 422 and "rules file" in err.value.detail["error"]
    no_url = AppSettings(DB_USER="u", DB_PASSWORD="p", DB_NAME="d")
    with pytest.raises(RunError, match="DOCS_INDEX_URL"):
        load_doc_pages(session, no_url, FakeEmbedder(), rules_csv=RULES, source_ref=None, apply=False, fetch=fetch)
    with pytest.raises(RunError, match="EMBEDDING_MODEL"):
        load_doc_pages(session, SETTINGS, None, rules_csv=RULES, source_ref=None, apply=True, fetch=fetch)
    with pytest.raises(RunError, match="No page in the index matched"):
        load_doc_pages(session, SETTINGS, FakeEmbedder(), rules_csv=RULES, source_ref=None, apply=False, fetch=lambda u: "# empty\n")


def test_graph_load_api_runs_as_a_job(connection, monkeypatch):
    monkeypatch.setattr(load_docs, "fetch_text", lambda url, timeout=60: INDEX)
    embedder = FakeEmbedder()
    app = create_app(SETTINGS, db_check=lambda: {"ok": True}, session_factory=lambda: session_on(connection),
                     model=None, embedder=embedder)
    client = TestClient(app)
    dry = client.post("/graph/loads/docs", json={"rules_csv": RULES, "source_ref": "r.csv"}, params={"wait": 30}).json()
    assert dry["pending"] is False and dry["applied"] is False and dry["counts"]["new"] == 4
    applied = client.post("/graph/loads/docs", json={"rules_csv": RULES, "apply": True}, params={"wait": 30}).json()
    assert applied["applied"] is True and applied["run_id"]
    with session_on(connection) as s:
        assert count(s, Node) == 4
    bad = client.post("/graph/loads/docs", json={"rules_csv": "prefix,include\n"}, params={"wait": 30})
    assert bad.status_code == 422 and "rules file" in bad.json()["detail"]["error"]
    assert client.get("/graph/jobs/00000000-0000-0000-0000-000000000000").status_code == 404
