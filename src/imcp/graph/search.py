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


def _nearest(session: Session, model: str, vector: list[float], *, kind: E.AssetKind | None,
             tags: dict[str, list[str]] | None, limit: int) -> list[dict]:
    distance = Node.embedding.cosine_distance(vector)
    stmt = (
        select(Node, Asset, cast(distance, Float).label("distance"))
        .join(Asset, Asset.node_id == Node.node_id)
        .where(Node.type == E.NodeType.asset, Node.status == E.Lifecycle.active, Asset.deprecated.is_(False),
               Node.embedding.is_not(None), Node.embedding_model == model)
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


def nearest_assets(session: Session, embedder, text: str, *, kind: E.AssetKind | None = None,
                   tags: dict[str, list[str]] | None = None, limit: int = 10) -> list[dict]:
    """[{url, title, description, kind, tags, distance}], nearest first."""
    [query] = embedder.embed([text])
    return _nearest(session, embedder.model, query, kind=kind, tags=tags, limit=limit)


def nearest_assets_for(session: Session, embedder, texts: list[str], *, kind: E.AssetKind | None = None,
                       tags: dict[str, list[str]] | None = None, per_text: int = 3, limit: int = 12) -> list[dict]:
    """
    One search per text (a requirement each), merged: a page found by several requirements keeps its
    best distance and lists every text it matched in `for` (their positions in `texts`). All texts are
    embedded in one call. Ranked by best distance, nearest first, at most `limit` pages.
    """
    if not texts:
        return []
    vectors = embedder.embed(texts)
    found: dict[str, dict] = {}
    for i, vector in enumerate(vectors):
        for hit in _nearest(session, embedder.model, vector, kind=kind, tags=tags, limit=per_text):
            kept = found.get(hit["url"])
            if kept is None:
                found[hit["url"]] = {**hit, "for": [i]}
            else:
                kept["for"].append(i)
                kept["distance"] = min(kept["distance"], hit["distance"])
    ranked = sorted(found.values(), key=lambda h: (h["distance"], -len(h["for"])))
    return ranked[:limit]
