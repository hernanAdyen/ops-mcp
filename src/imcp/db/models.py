"""Database tables (SQLAlchemy 2 ORM). Agreed on 2026-10-24.

Areas:
  Question bank   question, question_history, bank_load_run
  Opportunities   merchant, opportunity
  Graph           node, asset, asset_check, edge
  Evidence        source, instance, instance_link
  Runs            ingestion_run, generation
"""

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from imcp.db import enums as E

NAMING = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = sa.MetaData(naming_convention=NAMING)


def pg_enum(py_enum: type, name: str) -> sa.Enum:
    """Native Postgres enum that stores the enum's values."""
    return sa.Enum(py_enum, name=name, values_callable=lambda e: [m.value for m in e])


def enum_array(py_enum: type, name: str) -> ARRAY:
    return ARRAY(pg_enum(py_enum, name))


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()"))


def created_at() -> Mapped[datetime]:
    return mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def updated_at() -> Mapped[datetime]:
    return mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False
    )


EMPTY_ARRAY = sa.text("'{}'")
EMPTY_JSON = sa.text("'{}'::jsonb")
EMPTY_LIST = sa.text("'[]'::jsonb")


# --------------------------------------------------------------------------- question bank


class BankLoadRun(Base):
    """One manual load of the question bank, with what changed and what was rejected."""

    __tablename__ = "bank_load_run"
    run_id: Mapped[uuid.UUID] = uuid_pk()
    started_at: Mapped[datetime] = created_at()
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    source_ref: Mapped[str | None] = mapped_column(sa.Text)  # e.g. the sheet link
    status: Mapped[E.RunStatus] = mapped_column(pg_enum(E.RunStatus, "run_status"), server_default="running")
    seen: Mapped[int] = mapped_column(sa.Integer, server_default="0")
    inserted: Mapped[int] = mapped_column(sa.Integer, server_default="0")
    updated: Mapped[int] = mapped_column(sa.Integer, server_default="0")
    deactivated: Mapped[int] = mapped_column(sa.Integer, server_default="0")
    invalid: Mapped[int] = mapped_column(sa.Integer, server_default="0")
    report: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_JSON)


class Question(Base):
    """A question from the curated question bank. Empty tag lists mean 'applies to everyone'."""

    __tablename__ = "question"
    question_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)  # from the bank's question_id column
    text: Mapped[str] = mapped_column(sa.Text, nullable=False)
    type: Mapped[E.QuestionType] = mapped_column(pg_enum(E.QuestionType, "question_type"), nullable=False)
    # Allowed answers for choice questions, in display order ("A | B | C" in the sheet)
    options: Mapped[list[str]] = mapped_column(ARRAY(sa.Text), server_default=EMPTY_ARRAY, nullable=False)
    notes: Mapped[str | None] = mapped_column(sa.Text)  # guidance for the IM, not part of the question
    purpose: Mapped[str | None] = mapped_column(sa.Text)  # what the answer accomplishes, one line
    # In every scope whatever the tags (within the IM's priorities and subsections)
    baseline: Mapped[bool] = mapped_column(sa.Boolean, server_default=sa.false(), nullable=False)
    priority: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    subsection: Mapped[E.Subsection] = mapped_column(pg_enum(E.Subsection, "subsection"), nullable=False)
    channels: Mapped[list[E.Channel]] = mapped_column(enum_array(E.Channel, "channel"), server_default=EMPTY_ARRAY, nullable=False)
    pillars: Mapped[list[E.Pillar]] = mapped_column(enum_array(E.Pillar, "pillar"), server_default=EMPTY_ARRAY, nullable=False)
    categories: Mapped[list[E.Category]] = mapped_column(enum_array(E.Category, "category"), server_default=EMPTY_ARRAY, nullable=False)
    platforms: Mapped[list[E.Platform]] = mapped_column(enum_array(E.Platform, "platform"), server_default=EMPTY_ARRAY, nullable=False)
    status: Mapped[E.QuestionStatus] = mapped_column(
        pg_enum(E.QuestionStatus, "question_status"), server_default="active", nullable=False
    )
    content_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    first_seen_at: Mapped[datetime] = created_at()
    last_seen_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()

    __table_args__ = (
        sa.CheckConstraint("priority BETWEEN 1 AND 3", name="priority_range"),
        sa.CheckConstraint(
            "(type IN ('single_choice', 'multi_choice')) = (cardinality(options) > 0)", name="options_match_type"
        ),
        sa.Index(None, "channels", postgresql_using="gin"),
        sa.Index(None, "pillars", postgresql_using="gin"),
        sa.Index(None, "categories", postgresql_using="gin"),
        sa.Index(None, "platforms", postgresql_using="gin"),
    )


class QuestionHistory(Base):
    """Earlier versions of a question, so rewording never loses history."""

    __tablename__ = "question_history"
    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    question_id: Mapped[str] = mapped_column(sa.ForeignKey("question.question_id", ondelete="CASCADE"), nullable=False, index=True)
    bank_load_run_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("bank_load_run.run_id"))
    changed_at: Mapped[datetime] = created_at()
    old: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    new: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


# --------------------------------------------------------------------------- opportunities


class Merchant(Base):
    __tablename__ = "merchant"
    merchant_id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(sa.Text, nullable=False, unique=True)
    created_at: Mapped[datetime] = created_at()


class Opportunity(Base):
    """One deal. The alias is what we can actually see: the question bank sheet ID or proposal doc ID."""

    __tablename__ = "opportunity"
    opportunity_id: Mapped[uuid.UUID] = uuid_pk()
    merchant_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("merchant.merchant_id"), nullable=False, index=True)
    alias: Mapped[str] = mapped_column(sa.Text, nullable=False, unique=True)
    channels: Mapped[list[E.Channel]] = mapped_column(enum_array(E.Channel, "channel"), server_default=EMPTY_ARRAY, nullable=False)
    pillars: Mapped[list[E.Pillar]] = mapped_column(enum_array(E.Pillar, "pillar"), server_default=EMPTY_ARRAY, nullable=False)
    categories: Mapped[list[E.Category]] = mapped_column(enum_array(E.Category, "category"), server_default=EMPTY_ARRAY, nullable=False)
    platforms: Mapped[list[E.Platform]] = mapped_column(enum_array(E.Platform, "platform"), server_default=EMPTY_ARRAY, nullable=False)
    # The project tracks from /ops-create-scope: [{"name", "channels", "pillars", "categories", "platforms",
    # "priorities", "subsections"}], one per tab of the scope sheet, in tab order. The tags above are their union.
    tracks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=EMPTY_LIST, nullable=False)
    created_at: Mapped[datetime] = created_at()


# --------------------------------------------------------------------------- graph


class Node(Base):
    """A canonical thing in the graph (requirement, product, question, asset, ...)."""

    __tablename__ = "node"
    node_id: Mapped[uuid.UUID] = uuid_pk()
    type: Mapped[E.NodeType] = mapped_column(pg_enum(E.NodeType, "node_type"), nullable=False)
    canonical_key: Mapped[str] = mapped_column(sa.Text, nullable=False)  # unique per type
    label: Mapped[str] = mapped_column(sa.Text, nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text)  # text that gets embedded, with the label
    attrs: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_JSON, nullable=False)
    question_id: Mapped[str | None] = mapped_column(sa.ForeignKey("question.question_id"), unique=True)
    status: Mapped[E.Lifecycle] = mapped_column(pg_enum(E.Lifecycle, "lifecycle"), server_default="proposed", nullable=False)
    merged_into: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("node.node_id"))
    valid_from: Mapped[datetime] = created_at()
    valid_to: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # Any size: the embedding model is a setting and each model has its own size. `embedding_model`
    # says which made it, and a search only compares nodes made by the query's model. Searched
    # exactly (no index) for v1.
    embedding: Mapped[list[float] | None] = mapped_column(Vector())
    embedding_model: Mapped[str | None] = mapped_column(sa.Text)
    embedded_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()

    __table_args__ = (
        sa.UniqueConstraint("type", "canonical_key"),
        # Lets the asset table guarantee it only points at asset nodes.
        sa.UniqueConstraint("node_id", "type"),
        sa.CheckConstraint("(type = 'question') = (question_id IS NOT NULL)", name="question_link"),
        sa.CheckConstraint("(status = 'merged') = (merged_into IS NOT NULL)", name="merged_into_set"),
        sa.CheckConstraint("(embedding IS NULL) = (embedding_model IS NULL)", name="embedding_model_recorded"),
    )


class Asset(Base):
    """Details of an asset node: a doc page, flow diagram or image."""

    __tablename__ = "asset"
    node_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    node_type: Mapped[E.NodeType] = mapped_column(pg_enum(E.NodeType, "node_type"), server_default="asset", nullable=False)
    kind: Mapped[E.AssetKind] = mapped_column(pg_enum(E.AssetKind, "asset_kind"), nullable=False)
    url: Mapped[str | None] = mapped_column(sa.Text)
    title: Mapped[str | None] = mapped_column(sa.Text)
    mime_type: Mapped[str | None] = mapped_column(sa.Text)
    notes: Mapped[str | None] = mapped_column(sa.Text)
    last_checked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    last_http_status: Mapped[int | None] = mapped_column(sa.SmallInteger)
    deprecated: Mapped[bool] = mapped_column(sa.Boolean, server_default=sa.false(), nullable=False)

    __table_args__ = (
        sa.ForeignKeyConstraint(["node_id", "node_type"], ["node.node_id", "node.type"], ondelete="CASCADE"),
        sa.CheckConstraint("node_type = 'asset'", name="is_asset_node"),
    )


class AssetCheck(Base):
    """History of checks that an asset's link still works and isn't deprecated."""

    __tablename__ = "asset_check"
    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    node_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("asset.node_id", ondelete="CASCADE"), nullable=False, index=True)
    checked_at: Mapped[datetime] = created_at()
    http_status: Mapped[int | None] = mapped_column(sa.SmallInteger)
    deprecated: Mapped[bool] = mapped_column(sa.Boolean, server_default=sa.false(), nullable=False)
    note: Mapped[str | None] = mapped_column(sa.Text)


class Edge(Base):
    """A typed relationship with evidence counts. Confidence is calculated from the counts at query time."""

    __tablename__ = "edge"
    edge_id: Mapped[uuid.UUID] = uuid_pk()
    src: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("node.node_id"), nullable=False)
    type: Mapped[E.EdgeType] = mapped_column(pg_enum(E.EdgeType, "edge_type"), nullable=False)
    dst: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("node.node_id"), nullable=False, index=True)
    condition: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_JSON, nullable=False)
    origin: Mapped[E.EdgeOrigin] = mapped_column(pg_enum(E.EdgeOrigin, "edge_origin"), nullable=False)
    prior_good: Mapped[float] = mapped_column(sa.Float, server_default="1", nullable=False)
    prior_bad: Mapped[float] = mapped_column(sa.Float, server_default="1", nullable=False)
    accepted: Mapped[int] = mapped_column(sa.Integer, server_default="0", nullable=False)
    rejected: Mapped[int] = mapped_column(sa.Integer, server_default="0", nullable=False)
    distinct_opportunities: Mapped[int] = mapped_column(sa.Integer, server_default="0", nullable=False)
    pinned: Mapped[bool] = mapped_column(sa.Boolean, server_default=sa.false(), nullable=False)
    status: Mapped[E.Lifecycle] = mapped_column(pg_enum(E.Lifecycle, "lifecycle"), server_default="proposed", nullable=False)
    valid_from: Mapped[datetime] = created_at()
    valid_to: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    last_evidence_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()

    __table_args__ = (
        sa.UniqueConstraint("src", "type", "dst", "condition"),
        sa.CheckConstraint("src <> dst", name="no_self_loop"),
        sa.CheckConstraint("accepted >= 0 AND rejected >= 0 AND prior_good > 0 AND prior_bad > 0", name="counts_valid"),
        sa.Index(None, "src", "type"),
    )


# --------------------------------------------------------------------------- evidence


class Source(Base):
    """Where evidence came from: a pointer only, never the content (no transcripts are stored)."""

    __tablename__ = "source"
    source_id: Mapped[uuid.UUID] = uuid_pk()
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("opportunity.opportunity_id"), index=True)
    type: Mapped[E.SourceType] = mapped_column(pg_enum(E.SourceType, "source_type"), nullable=False)
    chat_kind: Mapped[E.ChatKind | None] = mapped_column(pg_enum(E.ChatKind, "chat_kind"))
    ref: Mapped[str] = mapped_column(sa.Text, nullable=False)  # doc ID + section, Gong call ID + time, bank row
    content_hash: Mapped[str | None] = mapped_column(sa.Text)
    ingested_at: Mapped[datetime] = created_at()

    __table_args__ = (sa.CheckConstraint("(type = 'chat') = (chat_kind IS NOT NULL)", name="chat_kind_for_chat"),)


class IngestionRun(Base):
    __tablename__ = "ingestion_run"
    run_id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[str] = mapped_column(sa.Text, nullable=False)  # e.g. proposal, chat_candidates
    status: Mapped[E.RunStatus] = mapped_column(pg_enum(E.RunStatus, "run_status"), server_default="running", nullable=False)
    started_at: Mapped[datetime] = created_at()
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    extractor_version: Mapped[str | None] = mapped_column(sa.Text)
    model: Mapped[str | None] = mapped_column(sa.Text)
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_JSON, nullable=False)


class Instance(Base):
    """One extracted question or response, with who said it, where, and its review state."""

    __tablename__ = "instance"
    instance_id: Mapped[uuid.UUID] = uuid_pk()
    opportunity_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("opportunity.opportunity_id"), nullable=False, index=True)
    source_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("source.source_id"), nullable=False, index=True)
    ingestion_run_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("ingestion_run.run_id"))
    speaker_role: Mapped[E.SpeakerRole] = mapped_column(pg_enum(E.SpeakerRole, "speaker_role"), nullable=False)
    act_type: Mapped[E.ActType] = mapped_column(pg_enum(E.ActType, "act_type"), nullable=False)
    subtype: Mapped[E.InstanceSubtype] = mapped_column(pg_enum(E.InstanceSubtype, "instance_subtype"), nullable=False)
    statement: Mapped[str] = mapped_column(sa.Text, nullable=False)  # normalized, sanitized sentence
    answer_value: Mapped[str | None] = mapped_column(sa.Text)
    excerpt: Mapped[str | None] = mapped_column(sa.Text)  # never from transcripts in v1
    prev_instance_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("instance.instance_id"))
    follows_up_on: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("instance.instance_id"))
    valid_from: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    extraction: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_JSON, nullable=False)
    review_status: Mapped[E.ReviewStatus] = mapped_column(
        pg_enum(E.ReviewStatus, "review_status"), server_default="pending", nullable=False
    )
    reviewed_by: Mapped[str | None] = mapped_column(sa.Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    review_reason: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (
        sa.CheckConstraint(
            "(act_type = 'question') = (subtype IN ('im_discovery', 'merchant_capability_check', 'follow_up', 'validation'))",
            name="subtype_matches_act",
        ),
    )


class InstanceLink(Base):
    """Instance -> node (refers_to) or instance -> edge (asserts, with polarity)."""

    __tablename__ = "instance_link"
    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    instance_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("instance.instance_id", ondelete="CASCADE"), nullable=False, index=True)
    node_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("node.node_id"), index=True)
    edge_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("edge.edge_id"), index=True)
    role: Mapped[E.LinkRole] = mapped_column(pg_enum(E.LinkRole, "link_role"), nullable=False)
    polarity: Mapped[E.Polarity | None] = mapped_column(pg_enum(E.Polarity, "polarity"))

    __table_args__ = (
        sa.CheckConstraint("(node_id IS NULL) <> (edge_id IS NULL)", name="exactly_one_target"),
        sa.CheckConstraint(
            "(role = 'refers_to' AND node_id IS NOT NULL AND polarity IS NULL) OR "
            "(role = 'asserts' AND edge_id IS NOT NULL AND polarity IS NOT NULL)",
            name="role_matches_target",
        ),
    )


# --------------------------------------------------------------------------- runs


class Generation(Base):
    """One run of a command (e.g. /ops-create-scope), for feedback and traceability."""

    __tablename__ = "generation"
    generation_id: Mapped[uuid.UUID] = uuid_pk()
    command: Mapped[str] = mapped_column(sa.Text, nullable=False)
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("opportunity.opportunity_id"), index=True)
    output_ref: Mapped[str | None] = mapped_column(sa.Text)
    tool_version: Mapped[str | None] = mapped_column(sa.Text)
    flags: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_JSON, nullable=False)
    # What the run was asked and what it chose (tags, topics, questions). Never the IM's free text.
    trace: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_JSON, nullable=False)
    created_at: Mapped[datetime] = created_at()
