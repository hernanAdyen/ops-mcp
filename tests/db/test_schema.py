import math

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from imcp.db import enums as E
from imcp.db.models import (
    EMBEDDING_DIM, Asset, Base, Edge, Instance, InstanceLink, Merchant, Node, Opportunity, Question, Source,
)


def fails(session, *objs, error=(IntegrityError, DBAPIError)):
    """Assert that saving these objects is rejected by the database."""
    with pytest.raises(error):
        with session.begin_nested():
            session.add_all(objs)
            session.flush()


def question(qid="Q1", **kw):
    base = dict(question_id=qid, text="Is Tokenization in scope?", type=E.QuestionType.toggle, priority=2,
                subsection=E.Subsection.features_functionality, content_hash="h")
    return Question(**{**base, **kw})


def node(kind=E.NodeType.requirement, key="tokenization", **kw):
    return Node(type=kind, canonical_key=key, label=key, **kw)


# --- migrations -------------------------------------------------------------------------------

def test_models_and_migrations_match(engine):
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], diff


def test_migration_downgrades_and_upgrades_cleanly(engine, alembic_cfg):
    cfg = alembic_cfg
    command.downgrade(cfg, "base")
    with engine.connect() as conn:
        assert conn.execute(text("select count(*) from pg_tables where schemaname='public' and tablename='node'")).scalar() == 0
    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        assert conn.execute(text("select count(*) from pg_tables where schemaname='public' and tablename='node'")).scalar() == 1


# --- question bank ----------------------------------------------------------------------------

def test_question_tags_and_filter_rule(session):
    session.add_all([
        question("Q1", channels=[E.Channel.ECOM], pillars=[E.Pillar.PFS]),
        question("Q2", channels=[E.Channel.IPP], pillars=[E.Pillar.UC]),
        question("Q3"),  # no tags: applies to everyone
        question("Q4", channels=[E.Channel.MOTO], pillars=[E.Pillar.PFS]),
    ])
    session.flush()
    # OR within a dimension, AND across dimensions, empty = applies to everyone
    rows = session.execute(text("""
        select question_id from question
        where (cardinality(channels) = 0 or channels && cast(:channels as channel[]))
          and (cardinality(pillars)  = 0 or pillars  && cast(:pillars as pillar[]))
        order by question_id"""), {"channels": ["ECOM", "IPP"], "pillars": ["PFS"]}).scalars().all()
    assert rows == ["Q1", "Q3"]


def test_invalid_tag_value_is_rejected(session):
    fails(session, question("Q9", channels=["POS"]), error=(IntegrityError, DBAPIError, LookupError))


def test_priority_must_be_1_to_3(session):
    fails(session, question("Q9", priority=4))


def test_only_choice_questions_have_options(session):
    fails(session, question("Q9", type=E.QuestionType.single_choice))  # choice without options
    fails(session, question("Q9", options=["Yes", "No"]))  # toggle with options
    session.add(question("Q9", type=E.QuestionType.multi_choice, options=["iOS", "Android"], notes="Ask per app"))
    session.flush()
    assert session.get(Question, "Q9").options == ["iOS", "Android"]


# --- graph ------------------------------------------------------------------------------------

def test_node_key_unique_per_type(session):
    session.add(node())
    session.flush()
    fails(session, node())
    session.add(node(E.NodeType.capability))  # same key, different type: fine
    session.flush()


def test_question_nodes_must_link_a_question(session):
    fails(session, node(E.NodeType.question, key="q-tokenization"))
    session.add(question("Q1"))
    session.flush()
    session.add(node(E.NodeType.question, key="Q1", question_id="Q1"))
    session.flush()


def test_merged_nodes_need_a_target(session):
    fails(session, node(status=E.Lifecycle.merged))


def test_asset_only_for_asset_nodes(session):
    req = node()
    session.add(req)
    session.flush()
    fails(session, Asset(node_id=req.node_id, kind=E.AssetKind.doc_page))
    doc = node(E.NodeType.asset, key="https://docs.adyen.com/online-payments/build-your-integration")
    session.add(doc)
    session.flush()
    session.add(Asset(node_id=doc.node_id, kind=E.AssetKind.flow_diagram, url=doc.canonical_key))
    session.flush()


def test_edges_unique_and_no_self_loops(session):
    a, b = node(key="a"), node(E.NodeType.product, key="drop-in")
    session.add_all([a, b])
    session.flush()
    session.add(Edge(src=a.node_id, type=E.EdgeType.satisfied_by, dst=b.node_id, origin=E.EdgeOrigin.derived))
    session.flush()
    fails(session, Edge(src=a.node_id, type=E.EdgeType.satisfied_by, dst=b.node_id, origin=E.EdgeOrigin.derived))
    fails(session, Edge(src=a.node_id, type=E.EdgeType.implies, dst=a.node_id, origin=E.EdgeOrigin.derived))
    # same pair, different condition: allowed
    session.add(Edge(src=a.node_id, type=E.EdgeType.satisfied_by, dst=b.node_id, origin=E.EdgeOrigin.derived,
                     condition={"answer": "yes"}))
    session.flush()


def test_embedding_search_full_size(session):
    def unit(i):
        v = [0.0] * EMBEDDING_DIM
        v[i] = 1.0
        return v

    near = [0.0] * EMBEDDING_DIM
    near[0], near[1] = 0.9, math.sqrt(1 - 0.81)
    session.add_all([
        node(key="x", embedding=unit(0), embedding_model="qwen3-embedding-8b"),
        node(key="y", embedding=unit(1), embedding_model="qwen3-embedding-8b"),
        node(key="z", embedding=near, embedding_model="qwen3-embedding-8b"),
    ])
    session.flush()
    ranked = session.execute(
        select(Node.canonical_key).order_by(Node.embedding.cosine_distance(unit(0))).limit(2)
    ).scalars().all()
    assert ranked == ["x", "z"]


def test_embedding_needs_model_and_right_size(session):
    fails(session, node(key="m", embedding=[0.0] * EMBEDDING_DIM))  # no model recorded
    fails(session, node(key="s", embedding=[0.0] * 10, embedding_model="m"),
          error=(IntegrityError, DBAPIError, ValueError))


# --- evidence ---------------------------------------------------------------------------------

def _opportunity(session):
    m = Merchant(name="Example Co", normalized_name="example co")
    session.add(m)
    session.flush()
    o = Opportunity(merchant_id=m.merchant_id, alias="sheet-123", channels=[E.Channel.ECOM])
    s = Source(type=E.SourceType.chat, chat_kind=E.ChatKind.transcript, ref="pasted 2026-10-24")
    session.add_all([o, s])
    session.flush()
    s.opportunity_id = o.opportunity_id
    return o, s


def test_chat_sources_need_a_kind(session):
    fails(session, Source(type=E.SourceType.chat, ref="x"))
    fails(session, Source(type=E.SourceType.proposal, chat_kind=E.ChatKind.brief, ref="x"))


def test_instance_subtype_must_match_act(session):
    o, s = _opportunity(session)
    ok = Instance(opportunity_id=o.opportunity_id, source_id=s.source_id, speaker_role=E.SpeakerRole.merchant,
                  act_type=E.ActType.question, subtype=E.InstanceSubtype.merchant_capability_check,
                  statement="Is Apple Pay supported in Drop-in?")
    session.add(ok)
    session.flush()
    fails(session, Instance(opportunity_id=o.opportunity_id, source_id=s.source_id, speaker_role=E.SpeakerRole.im,
                            act_type=E.ActType.question, subtype=E.InstanceSubtype.im_solution, statement="x"))


def test_instance_links_target_one_thing(session):
    o, s = _opportunity(session)
    a, b = node(key="apple-pay"), node(E.NodeType.product, key="drop-in")
    session.add_all([a, b])
    session.flush()
    e = Edge(src=b.node_id, type=E.EdgeType.supports, dst=a.node_id, origin=E.EdgeOrigin.derived)
    i = Instance(opportunity_id=o.opportunity_id, source_id=s.source_id, speaker_role=E.SpeakerRole.im,
                 act_type=E.ActType.response, subtype=E.InstanceSubtype.im_capability_statement,
                 statement="Apple Pay is supported in Drop-in")
    session.add_all([e, i])
    session.flush()
    session.add(InstanceLink(instance_id=i.instance_id, edge_id=e.edge_id, role=E.LinkRole.asserts,
                             polarity=E.Polarity.supports))
    session.add(InstanceLink(instance_id=i.instance_id, node_id=b.node_id, role=E.LinkRole.refers_to))
    session.flush()
    fails(session, InstanceLink(instance_id=i.instance_id, node_id=b.node_id, edge_id=e.edge_id,
                                role=E.LinkRole.asserts, polarity=E.Polarity.supports))
    fails(session, InstanceLink(instance_id=i.instance_id, edge_id=e.edge_id, role=E.LinkRole.asserts))
