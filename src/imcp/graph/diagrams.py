"""The owner's curated flow diagrams, from a CSV: title, url, description and tags.

Columns: title, url, description, channels, pillars, categories, platforms, note. The url is a public
https link to a PNG, JPEG or GIF, or a Google Drive share link to one (the file shared with "anyone
with the link"): Docs fetches the image itself, so it has to be reachable from the public internet. A
Drive link is turned into the direct image link Docs can fetch. Tags are
semicolon-separated bank values; empty means "applies to everyone". The URL must be a public
https link to a PNG, JPEG or GIF (Google Docs can't insert SVG). Loaded like the doc pages:
one `flow_diagram` asset node per row, embedded from title + description.
"""

import csv
from io import StringIO
import re
from urllib.parse import parse_qs, urlsplit

from imcp.db import enums as E
from imcp.graph.assets import AssetLoadReport, load_assets
from imcp.graph.docs_index import TAG_ENUMS, Page, RulesError

DIAGRAM_COLUMNS = ("title", "url", "description", "channels", "pillars", "categories", "platforms", "note")
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif")
DRIVE_HOSTS = ("drive.google.com", "docs.google.com")


def drive_image_url(url: str) -> str | None:
    """The direct image link for a Google Drive share link (file/d/<id>/view, open?id=<id>, uc?id=<id>);
    None when the link isn't a Drive file link."""
    parts = urlsplit(url)
    if parts.netloc.lower() not in DRIVE_HOSTS:
        return None
    match = re.match(r"^/file/d/([A-Za-z0-9_-]{10,})", parts.path)
    file_id = match.group(1) if match else next(iter(parse_qs(parts.query).get("id", [])), None)
    if not file_id or not re.fullmatch(r"[A-Za-z0-9_-]{10,}", file_id):
        return None
    return f"https://drive.google.com/uc?export=view&id={file_id}"
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
        drive = drive_image_url(url)
        if drive is not None:
            url, parts = drive, urlsplit(drive)  # the direct link Docs can fetch; the file must be shared with anyone
        elif parts.netloc.lower() in DRIVE_HOSTS:
            raise RulesError(f"row {n}: this Drive link isn't a file link (expected .../file/d/<id>/view or ?id=<id>)")
        elif not parts.path.lower().endswith(IMAGE_SUFFIXES):
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
