"""Which Adyen doc pages go into the graph, and what we know about each.

Two inputs, both pure text:

- The docs index (`llms.txt` on docs.adyen.com): one line per page,
  `- [Title](https://docs.adyen.com/path.md): one-sentence description`, under `##` headings.
  Read once per load and never stored. Only the URL, title and description of each page are kept.
- The rules CSV (`data/graph/adyen-doc-pages.csv`): path prefixes with include yes/no, an optional
  depth limit and the tags the pages get. The longest matching prefix wins.

Nothing here touches the network or the database.
"""

import csv
import re
from dataclasses import dataclass, field
from io import StringIO
from urllib.parse import urlsplit

from imcp.db import enums as E

TAG_ENUMS = {"channels": E.Channel, "pillars": E.Pillar, "categories": E.Category, "platforms": E.Platform}
RULE_COLUMNS = ("prefix", "include", "max_depth", "channels", "pillars", "categories", "platforms", "note")
ENTRY = re.compile(r"^\s*[-*]\s*\[(?P<title>[^\]]*)\]\((?P<url>[^)\s]+)\)\s*(?::\s*(?P<description>.*))?$")


class RulesError(ValueError):
    """The rules CSV can't be used. The message says which row and why."""


@dataclass(frozen=True)
class Rule:
    prefix: str
    include: bool
    max_depth: int | None
    tags: dict[str, list[str]]
    note: str = ""


@dataclass(frozen=True)
class IndexEntry:
    url: str  # canonical: https, no .md, no trailing slash, no fragment or query
    path: str
    title: str
    description: str
    section: str  # the `##` heading it sits under


@dataclass(frozen=True)
class Page:
    url: str
    path: str
    title: str
    description: str
    tags: dict[str, list[str]]
    rule: str  # the prefix that selected it


@dataclass
class Selection:
    pages: list[Page] = field(default_factory=list)
    no_description: list[str] = field(default_factory=list)  # selected by the rules, but the index has no description
    excluded: int = 0
    duplicates: int = 0


def canonical_url(raw: str) -> str:
    parts = urlsplit(raw.strip())
    path = parts.path
    if path.endswith(".md"):
        path = path[:-3]
    path = path.rstrip("/") or "/"
    return f"https://{parts.netloc.lower()}{path}"


def parse_rules(text: str) -> list[Rule]:
    reader = csv.DictReader(StringIO(text))
    missing = [c for c in RULE_COLUMNS if c not in (reader.fieldnames or [])]
    if missing:
        raise RulesError(f"the rules file is missing the column(s): {', '.join(missing)}")
    rules: list[Rule] = []
    seen: set[str] = set()
    for n, row in enumerate(reader, start=2):
        prefix = (row["prefix"] or "").strip()
        if not prefix.startswith("/"):
            raise RulesError(f"row {n}: the prefix must start with '/' (got {prefix!r})")
        prefix = prefix.rstrip("/") or "/"
        if prefix in seen:
            raise RulesError(f"row {n}: the prefix {prefix} appears twice")
        seen.add(prefix)
        include_raw = (row["include"] or "").strip().lower()
        if include_raw not in ("yes", "no"):
            raise RulesError(f"row {n}: include must be yes or no (got {include_raw!r})")
        depth_raw = (row["max_depth"] or "").strip()
        max_depth = None
        if depth_raw:
            if not depth_raw.isdigit():
                raise RulesError(f"row {n}: max_depth must be a whole number (got {depth_raw!r})")
            max_depth = int(depth_raw)
        tags: dict[str, list[str]] = {}
        for name, enum_cls in TAG_ENUMS.items():
            values = [v.strip() for v in (row[name] or "").split(";") if v.strip()]
            bad = [v for v in values if v not in enum_cls.__members__]
            if bad:
                raise RulesError(f"row {n}: unknown {name} value(s) {', '.join(bad)}")
            tags[name] = values
        rules.append(Rule(prefix, include_raw == "yes", max_depth, tags, (row.get("note") or "").strip()))
    if not rules:
        raise RulesError("the rules file has no rules")
    return rules


def parse_index(text: str) -> list[IndexEntry]:
    """Every page entry in the index. A page listed twice keeps its first entry."""
    entries: list[IndexEntry] = []
    seen: set[str] = set()
    section = ""
    for line in text.splitlines():
        if line.startswith("#"):
            section = line.lstrip("#").strip()
            continue
        m = ENTRY.match(line)
        if not m:
            continue
        url = canonical_url(m["url"])
        if url in seen:
            continue
        seen.add(url)
        entries.append(IndexEntry(
            url=url, path=urlsplit(url).path, title=m["title"].strip(),
            description=(m["description"] or "").strip(), section=section,
        ))
    return entries


def _matches(prefix: str, path: str) -> bool:
    return prefix == "/" or path == prefix or path.startswith(prefix + "/")


def rule_for(path: str, rules: list[Rule]) -> Rule | None:
    """The rule whose prefix matches the path, longest prefix first."""
    best = None
    for r in rules:
        if _matches(r.prefix, path) and (best is None or len(r.prefix) > len(best.prefix)):
            best = r
    return best


def _depth_below(prefix: str, path: str) -> int:
    rest = path if prefix == "/" else path[len(prefix):]
    return len([p for p in rest.split("/") if p])


def select_pages(entries: list[IndexEntry], rules: list[Rule], host: str = "docs.adyen.com") -> Selection:
    """The pages the rules include, with their tags. Pages on another host are ignored."""
    out = Selection()
    seen: set[str] = set()
    for e in entries:
        if urlsplit(e.url).netloc != host:
            continue
        rule = rule_for(e.path, rules)
        if rule is None or not rule.include:
            out.excluded += 1
            continue
        if rule.max_depth is not None and _depth_below(rule.prefix, e.path) > rule.max_depth:
            out.excluded += 1
            continue
        if e.url in seen:
            out.duplicates += 1
            continue
        seen.add(e.url)
        if not e.description or not e.title:
            out.no_description.append(e.url)
            continue
        out.pages.append(Page(e.url, e.path, e.title, e.description, rule.tags, rule.prefix))
    return out
