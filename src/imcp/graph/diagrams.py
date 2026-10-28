"""The owner's curated flow diagrams, from a CSV: title, url, description and tags.

Columns: title, url, description, channels, pillars, categories, platforms, note. Tags are
semicolon-separated bank values; empty means "applies to everyone". The URL must be a public
https link to a PNG, JPEG or GIF (Google Docs can't insert SVG). Loaded like the doc pages:
one `flow_diagram` asset node per row, embedded from title + description.
"""

import csv
from io import StringIO
from urllib.parse import urlsplit

from imcp.db import enums as E
from imcp.graph.assets import AssetLoadReport, load_assets
from imcp.graph.docs_index import TAG_ENUMS, Page, RulesError

DIAGRAM_COLUMNS = ("title", "url", "description", "channels", "pillars", "categories", "platforms", "note")
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif")
SOURCE_RULE = "diagrams"


def parse_diagrams_csv(text: str) -> list[Page]:
    reader = csv.DictReader(StringIO(text))
    missing = [c for c in DIAGRAM_COLUMNS if c not in (reader.fieldnames or [])]
    if missing:
        raise RulesError(f"the diagrams file is missing the column(s): {', '.join(missing)}")
    pages: list[Page] = []
    seen: set[str] = set()
    for n, row in enumerate(reader, start=2):
        title = (row["title"] or "").strip()
        url = (row["url"] or "").strip()
        description = (row["description"] or "").strip()
        if not (title and url and description):
            raise RulesError(f"row {n}: title, url and description are all needed")
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.netloc:
            raise RulesError(f"row {n}: the url must be a public https link (got {url!r})")
        if not parts.path.lower().endswith(IMAGE_SUFFIXES):
            raise RulesError(f"row {n}: the url must point at a PNG, JPEG or GIF (Docs can't insert other formats)")
        if url in seen:
            raise RulesError(f"row {n}: the url appears twice")
        seen.add(url)
        tags: dict[str, list[str]] = {}
        for name, enum_cls in TAG_ENUMS.items():
            values = [v.strip() for v in (row[name] or "").split(";") if v.strip()]
            bad = [v for v in values if v not in enum_cls.__members__]
            if bad:
                raise RulesError(f"row {n}: unknown {name} value(s) {', '.join(bad)}")
            tags[name] = values
        pages.append(Page(url=url, path=parts.path, title=title, description=description, tags=tags, rule=SOURCE_RULE))
    if not pages:
        raise RulesError("the diagrams file has no rows")
    return pages


def load_diagrams(session, embedder, *, csv_text: str, source_ref: str | None, apply: bool,
                  sanitize: bool = True) -> AssetLoadReport:
    pages = parse_diagrams_csv(csv_text)
    return load_assets(session, pages, kind=E.AssetKind.flow_diagram, embedder=embedder,
                       source_ref=source_ref, apply=apply, sanitize=sanitize)
