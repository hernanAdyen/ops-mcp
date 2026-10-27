"""Find the assets (doc pages, diagrams) closest to a text.

Tags narrow first (a page with no value for a tag applies to everyone), then the embedding ranks.
Only nodes embedded by the same model as the query are compared. Exact search, no index.
"""

from sqlalchemy import Float, String, cast, func, literal_column, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session

from imcp.db import enums as E
from imcp.db.models import Asset, Node
from imcp.graph.docs_index import TAG_ENUMS

EMPTY_JSON_LIST = literal_column("'[]'::jsonb")


def _tag_filter(name: str, values: list[str]):
    """attrs->tags->name is missing or empty, or shares a value with `values`."""
    column = func.coalesce(Node.attrs["tags"][name], EMPTY_JSON_LIST)
    return (func.jsonb_array_length(column) == 0) | func.jsonb_exists_any(column, cast(values, ARRAY(String)))


def nearest_assets(session: Session, embedder, text: str, *, kind: E.AssetKind | None = None,
                   tags: dict[str, list[str]] | None = None, limit: int = 10) -> list[dict]:
    """[{url, title, description, kind, tags, distance}], nearest first."""
    [query] = embedder.embed([text])
    distance = Node.embedding.cosine_distance(query)
    stmt = (
        select(Node, Asset, cast(distance, Float).label("distance"))
        .join(Asset, Asset.node_id == Node.node_id)
        .where(Node.type == E.NodeType.asset, Node.status == E.Lifecycle.active, Asset.deprecated.is_(False),
               Node.embedding.is_not(None), Node.embedding_model == embedder.model)
    )
    if kind is not None:
        stmt = stmt.where(Asset.kind == kind)
    for name, values in (tags or {}).items():
        if name not in TAG_ENUMS:
            raise ValueError(f"unknown tag {name}")
        if values:
            stmt = stmt.where(_tag_filter(name, [str(v) for v in values]))
    rows = session.execute(stmt.order_by(distance).limit(limit)).all()
    return [
        {"url": asset.url, "title": node.label, "description": node.description, "kind": asset.kind.value,
         "tags": (node.attrs or {}).get("tags", {}), "distance": round(float(d), 4)}
        for node, asset, d in rows
    ]
