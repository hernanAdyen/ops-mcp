"""Load asset nodes (doc pages, flow diagrams) into the graph.

Like the bank loader: a dry run by default that reports what would change and writes nothing;
with apply=True it makes the changes, embeds what is new or changed, and records an
`ingestion_run`. The caller commits.

An asset node keeps only what points at the asset: its URL (the canonical key), title (label),
one-line description, tags (in attrs) and the embedding of title + description. Never the content.
With sanitize on (the default), the title and description are scrubbed of personal and secret data
(imcp.pii) before anything is stored or embedded: the one gate every page passes through.

Rules:
  new URL                     node + asset inserted (status active) and embedded
  title/description changed   updated and embedded again
  tags changed                updated
  unchanged                   left alone (embedded if it has no embedding from the current model)
  URL no longer selected      asset.deprecated = true, node deactivated (never deleted)
  deprecated URL is back      restored (active) and embedded if needed
"""

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from imcp.db import enums as E
from imcp.db.models import Asset, IngestionRun, Node
from imcp.graph.docs_index import Page
from imcp.llm import ModelError
from imcp.pii import scrub

LIST_CAP = 40  # the report lists at most this many URLs per change, with the totals in counts


@dataclass
class AssetLoadReport:
    applied: bool
    source: str | None
    kind: str
    run_id: str | None = None
    fatal: str | None = None
    counts: dict[str, int] = field(default_factory=dict)
    by_section: dict[str, int] = field(default_factory=dict)  # selected pages per first path part
    new: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    deprecated: list[str] = field(default_factory=list)
    restored: list[str] = field(default_factory=list)
    no_description: list[str] = field(default_factory=list)
    lists_capped_at: int = LIST_CAP

    def to_dict(self) -> dict:
        d = asdict(self)
        for key in ("new", "changed", "deprecated", "restored", "no_description"):
            d[key] = d[key][:LIST_CAP]
        return d


def embed_text(label: str, description: str | None) -> str:
    return f"{label}\n{description or ''}".strip()


def _section(path: str) -> str:
    parts = [p for p in path.split("/") if p]
    return parts[0] if parts else "/"


def _attrs(page: Page) -> dict:
    return {"tags": page.tags, "section": _section(page.path), "rule": page.rule}


def load_assets(session: Session, pages: list[Page], *, kind: E.AssetKind, embedder, source_ref: str | None,
                apply: bool, no_description: list[str] | None = None, sanitize: bool = True) -> AssetLoadReport:
    report = AssetLoadReport(applied=apply, source=source_ref, kind=kind.value,
                             no_description=list(no_description or []))
    if sanitize:
        pages = [replace(pg, title=scrub(pg.title), description=scrub(pg.description or "")) for pg in pages]
    for p in pages:
        report.by_section[_section(p.path)] = report.by_section.get(_section(p.path), 0) + 1

    existing: dict[str, tuple[Node, Asset]] = {
        node.canonical_key: (node, asset)
        for node, asset in session.execute(
            select(Node, Asset).join(Asset, Asset.node_id == Node.node_id).where(Asset.kind == kind)
        ).all()
    }
    wanted = {p.url: p for p in pages}
    model_name = embedder.model if embedder is not None else None

    to_embed: list[Node] = []
    embed_count = 0  # what a dry run would embed (new pages have no node yet to put in to_embed)
    unchanged = 0
    for url, page in wanted.items():
        if url not in existing:
            report.new.append(url)
            embed_count += 1
            if apply:
                node = Node(type=E.NodeType.asset, canonical_key=url, label=page.title, description=page.description,
                            attrs=_attrs(page), status=E.Lifecycle.active)
                session.add(node)
                session.flush()
                session.add(Asset(node_id=node.node_id, kind=kind, url=url, title=page.title))
                to_embed.append(node)
            continue
        node, asset = existing[url]
        text_changed = node.label != page.title or (node.description or "") != page.description
        tags_changed = (node.attrs or {}).get("tags") != page.tags
        was_deprecated = asset.deprecated or node.status != E.Lifecycle.active
        if was_deprecated:
            report.restored.append(url)
        elif text_changed or tags_changed:
            report.changed.append(url)
        else:
            unchanged += 1
        needs_embedding = text_changed or node.embedding is None or node.embedding_model != model_name
        embed_count += needs_embedding
        if apply:
            node.label, node.description, node.attrs = page.title, page.description, _attrs(page)
            node.status, node.valid_to = E.Lifecycle.active, None
            asset.title, asset.url, asset.deprecated = page.title, url, False
            if needs_embedding:
                to_embed.append(node)

    for url, (node, asset) in existing.items():
        if url in wanted or asset.deprecated:
            continue
        report.deprecated.append(url)
        if apply:
            asset.deprecated = True
            node.status, node.valid_to = E.Lifecycle.deactivated, datetime.now(timezone.utc)

    report.counts = {
        "selected": len(pages), "new": len(report.new), "changed": len(report.changed), "unchanged": unchanged,
        "restored": len(report.restored), "deprecated": len(report.deprecated),
        "no_description": len(report.no_description), "to_embed": embed_count,
        "active_after": len(wanted),
    }

    if not apply:
        return report
    if to_embed and embedder is None:
        report.fatal = "EMBEDDING_MODEL (and a base URL) must be set to load assets."
        report.applied = False
        return report

    run = IngestionRun(kind=f"assets:{kind.value}", model=model_name, status=E.RunStatus.running)
    session.add(run)
    session.flush()
    try:
        _embed(to_embed, embedder)
    except ModelError as exc:
        # The caller rolls back when applied is False, so nothing of this load is kept.
        report.fatal = f"Embedding failed: {exc}. Nothing was changed."
        report.applied = False
        return report
    run.status, run.finished_at = E.RunStatus.succeeded, datetime.now(timezone.utc)
    run.stats = {"source": source_ref, **report.counts, "by_section": report.by_section}
    report.run_id = str(run.run_id)
    session.flush()
    return report


def _embed(nodes: list[Node], embedder) -> None:
    if not nodes:
        return
    vectors = embedder.embed([embed_text(n.label, n.description) for n in nodes])
    now = datetime.now(timezone.utc)
    for node, vector in zip(nodes, vectors):
        node.embedding, node.embedding_model, node.embedded_at = vector, embedder.model, now
