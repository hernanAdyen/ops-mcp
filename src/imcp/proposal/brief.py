"""The research brief for one track: what the graph knows, and how to research the rest.

The IM's own model does the research and writes section 3. We give it, per track:
  - the requirements: the answered Discovery and Features questions, as short lines
  - the doc pages and diagrams nearest to the track (tags narrow, the embedding ranks)
  - the designs and considerations the graph knows (from ingested proposals; none until then)
  - the instructions: what each subsection covers, the lengths, and that links must come from
    the brief or sit under the docs host

Documentation links in the proposal only ever come from asset nodes: the server checks the draft
against them (draft.py). Nothing here is stored except the node URLs, in the trace.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from imcp.db import enums as E
from imcp.db.models import Node
from imcp.graph.search import nearest_assets
from imcp.proposal.answers import TrackAnswers, feature_rows

MAX_SEARCH_CHARS = 4000
MAX_DOC_LINKS = 12  # offered to the research step; the document itself takes fewer (max_links)
MAX_DIAGRAMS = 3
KNOWN_TYPES = (E.NodeType.integration_design, E.NodeType.consideration, E.NodeType.product)

SECTIONS = {
    "technical_considerations": (
        "3.x.1 Technical Considerations: what the merchant's situation means for the integration: "
        "authentication and 3DS, tokenization and migration, PCI scope, reporting and reconciliation, "
        "platform or marketplace structure, in-person connectivity. One short paragraph per consideration, "
        "each tied to an answer in the requirements."
    ),
    "integration_design": (
        "3.x.2 Integration Design: the recommended Adyen products and how they fit together for this track "
        "(for example Drop-in or Components with the Sessions flow, Terminal API cloud or local, Adyen for "
        "Platforms with split configurations). Say what the merchant builds and what Adyen provides."
    ),
}

INSTRUCTIONS = (
    "Research with your own tools, starting from the links in this brief (each has a .md version that is "
    "lighter to read), then the rest of the documentation site. Write plain English an implementation manager "
    "would use: short sentences, no marketing. Every statement about Adyen must come from a page you read. "
    "Cite only links from this brief or pages under the documentation host; the server refuses any other link. "
    "Return the draft as JSON for im_proposal_plan: {introduction: {background, goals}, tracks: [{name, "
    "technical_considerations: [paragraphs], integration_design: [paragraphs], links: [urls]}]}. "
    "Paragraphs are plain text, up to 1,200 characters each, at most 8 per subsection. Do not include merchant "
    "contact details or people's names."
)


def search_text(track: TrackAnswers) -> str:
    """The text the track is searched by: its name, the features in scope and the Discovery answers."""
    parts = [track.name]
    for row in feature_rows(track):
        if row["in_scope"] is True or row["text"]:
            parts.append(row["feature"] + (f": {row['text']}" if row["text"] else ""))
    for a in track.by_subsection(E.Subsection.discovery.value):
        parts.append(f"{a.question} {a.answer}")
    return "\n".join(parts)[:MAX_SEARCH_CHARS]


def requirements(track: TrackAnswers) -> list[dict]:
    """[{id, text}] the research is for: features in scope and Discovery answers, in sheet order."""
    out = []
    for a in track.answers:
        if a.subsection == E.Subsection.introduction.value:
            continue
        out.append({"id": a.id, "text": f"{a.question} — {a.answer}"})
    return out


def known_nodes(session: Session, types=KNOWN_TYPES, limit: int = 40) -> list[dict]:
    """Designs, considerations and products the graph knows (active nodes). Empty until proposals are ingested."""
    rows = session.scalars(select(Node).where(Node.type.in_(types), Node.status == E.Lifecycle.active)
                           .order_by(Node.type, Node.label).limit(limit)).all()
    return [{"type": n.type.value, "label": n.label, "description": n.description} for n in rows]


def build_brief(session: Session, embedder, track: TrackAnswers, tags: dict[str, list[str]], *,
                docs_host: str | None) -> dict:
    text = search_text(track)
    doc_pages = nearest_assets(session, embedder, text, kind=E.AssetKind.doc_page, tags=tags, limit=MAX_DOC_LINKS)
    diagrams = nearest_assets(session, embedder, text, kind=E.AssetKind.flow_diagram, tags=tags, limit=MAX_DIAGRAMS)
    known = known_nodes(session)
    notes = []
    if not doc_pages:
        notes.append("The graph has no documentation pages for these tags yet (load them with im_graph_load_docs).")
    if not diagrams:
        notes.append("No flow diagram matches this track; the diagram placeholder will be removed.")
    if not known:
        notes.append("The graph has no ingested proposals yet, so there are no known designs or considerations: "
                     "the research has to cover them.")
    return {
        "track": track.name,
        "tags": tags,
        "requirements": requirements(track),
        "doc_pages": [{"title": d["title"], "url": d["url"], "md_url": d["url"] + ".md", "description": d["description"]}
                      for d in doc_pages],
        "diagrams": [{"title": d["title"], "url": d["url"], "description": d["description"]} for d in diagrams],
        "known": known,
        "sections": SECTIONS,
        "docs_host": docs_host,
        "notes": notes,
    }
