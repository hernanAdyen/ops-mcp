"""The Docs batch that fills a proposal copy. A pure function over the outline and the content.

The master is a single-tab Google Doc with {{tokens}} where content goes:
  {{Merchant Name}}                      on the cover and in the header (replaced everywhere)
  {{Project Background}} {{Project Goals}}   1.4 and 1.5
  one track block: a heading "2.x {{Track}} Scope" with Discovery (a Question | Answer table with a
  header row and one empty body row, or a {{Discovery}} paragraph) and the Features &
  Functionality table (a header row and exactly one empty body row), and a heading
  "3.x {{Track}} Solution" with {{Technical Considerations}}, {{Integration Design}},
  {{Flow Diagrams}} and {{Documentation}}.

Every edit that uses an index is computed from the outline and applied from the end of the
document backwards, so earlier indexes stay valid; replaceAllText runs last because it changes
lengths. The IM's Claude relays the batch unchanged.
"""

from dataclasses import dataclass, field

from imcp.proposal.outline import Outline, Paragraph, Table, utf16_len
from imcp.scope.runs import DEFAULT_TRACK, RunError

TOKENS = {
    "merchant": ("{{Merchant Name}}",),
    "background": ("{{Project Background}}",),
    "goals": ("{{Project Goals}}", "{{Project Goals & Objectives}}"),
    "track": ("{{Track}}", "{{Project Track}}", "{{Track Name}}"),
    "discovery": ("{{Discovery}}",),
    "considerations": ("{{Technical Considerations}}",),
    "design": ("{{Integration Design}}",),
    "diagrams": ("{{Flow Diagrams}}",),
    "documentation": ("{{Documentation}}",),
}
FEATURES_HEADING = "features & functionality"
DISCOVERY_HEADING = "discovery"
TABLE_HEADERS = {  # the words the two header cells must contain
    FEATURES_HEADING: ("feature", "scope"),
    DISCOVERY_HEADING: ("question", "answer"),
}
TICK, BOX = "☑", "☐"  # ☑ ☐
IMAGE_WIDTH_PT = 440
BULLETS = "BULLET_DISC_CIRCLE_SQUARE"
EMPTY_CELL = 2  # an empty table cell spans two indexes: its marker and its newline


@dataclass
class Group:
    """Requests that belong to one place in the document, applied together."""

    anchor: int
    requests: list[dict] = field(default_factory=list)


def _bad(message: str) -> RunError:
    return RunError(422, f"The document doesn't match the proposal master: {message}")


def find_token(outline: Outline, key: str, *, after: int = -1) -> Paragraph:
    """The paragraph that is exactly this token (any of its spellings), after the outline position `after`."""
    for spelling in TOKENS[key]:
        found = [p for p in outline.token_paragraphs(spelling) if p.index > after]
        if found:
            return found[0]
    raise _bad(f"the paragraph {TOKENS[key][0]} is missing (it must be a paragraph of its own).")


def _heading(outline: Outline, words: str, *, after: int = -1) -> Paragraph | None:
    return next((p for p in outline.paragraphs if p.index > after and p.heading_level is not None
                 and words in p.text.casefold()), None)


def _check_table(table: Table, name: str, headers: tuple[str, str]) -> Table:
    if len(table.rows) != 2 or any(len(r.cells) != 2 for r in table.rows):
        raise _bad(f"the {name} table must have two columns, a header row and exactly one empty row.")
    header = [c.text.casefold() for c in table.rows[0].cells]
    if headers[0] not in header[0] or headers[1] not in header[1]:
        raise _bad(f"the {name} table's header row must read '{headers[0].title()}' and '{headers[1].title()}' (or contain those words).")
    body = table.rows[1]
    if any(c.text.strip() or c.e - c.s != EMPTY_CELL for c in body.cells):
        raise _bad(f"the {name} table's body row must be empty.")
    return table


def features_table(outline: Outline, *, after: int = -1) -> Table:
    heading = _heading(outline, FEATURES_HEADING, after=after)
    if heading is None:
        raise _bad("the 'Features & Functionality' heading is missing.")
    table = outline.table_after(heading)
    if table is None:
        raise _bad("there is no table under the 'Features & Functionality' heading.")
    return _check_table(table, "Features & Functionality", TABLE_HEADERS[FEATURES_HEADING])


def discovery_table(outline: Outline, *, after: int = -1) -> Table | None:
    """The Discovery table (Question | Answer) under the Discovery heading, or None when the master
    uses a {{Discovery}} paragraph instead."""
    heading = _heading(outline, DISCOVERY_HEADING, after=after)
    if heading is None:
        return None
    table = outline.table_after(heading)
    if table is None:
        return None
    return _check_table(table, "Discovery", TABLE_HEADERS[DISCOVERY_HEADING])


def _replace_paragraph(p: Paragraph, text: str) -> list[dict]:
    """Replace the token with text (which may hold newlines = new paragraphs), keeping the paragraph's newline."""
    reqs = []
    if p.e - 1 > p.s:
        reqs.append({"deleteContentRange": {"range": {"startIndex": p.s, "endIndex": p.e - 1}}})
    if text:
        reqs.append({"insertText": {"location": {"index": p.s}, "text": text}})
    return reqs


def _delete_paragraph(p: Paragraph) -> list[dict]:
    """Empty the paragraph but keep its newline: Docs refuses to delete the newline before a table, and an
    empty paragraph under the heading is harmless."""
    if p.e - 1 <= p.s:
        return []
    return [{"deleteContentRange": {"range": {"startIndex": p.s, "endIndex": p.e - 1}}}]


def _style(start: int, end: int, style: dict, fields: str) -> dict:
    return {"updateTextStyle": {"range": {"startIndex": start, "endIndex": end}, "textStyle": style, "fields": fields}}


def plain_paragraphs(p: Paragraph, paragraphs: list[str]) -> Group:
    """Paragraphs of plain text in place of the token; the paragraph is removed when there are none."""
    if not paragraphs:
        return Group(p.s, _delete_paragraph(p))
    text = "\n".join(paragraphs)
    reqs = _replace_paragraph(p, text)
    reqs.append(_style(p.s, p.s + utf16_len(text), {"bold": False, "italic": False}, "bold,italic"))
    return Group(p.s, reqs)


def discovery(p: Paragraph, answers: list[dict]) -> Group:
    """Question (bold) and answer (plain) pairs, in sheet order."""
    if not answers:
        return Group(p.s, _delete_paragraph(p))
    lines, bold = [], []
    at = p.s
    for a in answers:
        q, ans = " ".join(a["question"].split()), " ".join(a["answer"].split())
        lines += [q, ans]
        bold.append((at, at + utf16_len(q)))
        at += utf16_len(q) + 1 + utf16_len(ans) + 1
    text = "\n".join(lines)
    reqs = _replace_paragraph(p, text)
    reqs.append(_style(p.s, p.s + utf16_len(text), {"bold": False}, "bold"))
    reqs += [_style(s, e, {"bold": True}, "bold") for s, e in bold]
    return Group(p.s, reqs)


def fill_table(table: Table, rows: list[tuple[str, str]]) -> Group:
    """
    Fill a two-column table: one row per item. The master's one empty body row is reused; the others
    are inserted below it (each new empty row spans 1 + 2 cells x 2 = 5), then every cell is filled
    from the last row backwards so computed indexes stay valid.
    """
    if not rows:
        return Group(table.s, [])
    body = table.rows[1]
    row_span = 1 + EMPTY_CELL * len(body.cells)
    reqs = [{"insertTableRow": {"tableCellLocation": {"tableStartLocation": {"index": table.s}, "rowIndex": 1, "columnIndex": 0},
                                "insertBelow": True}} for _ in rows[1:]]
    for j in range(len(rows) - 1, -1, -1):
        row_start = body.s + row_span * j
        left, right = (" ".join(cell.split()) for cell in rows[j])
        if right:
            reqs.append({"insertText": {"location": {"index": row_start + 4}, "text": right}})
        if left:
            reqs.append({"insertText": {"location": {"index": row_start + 2}, "text": left}})
    return Group(table.s, reqs)


def features(table: Table, rows: list[dict]) -> Group:
    """The Features & Functionality table: feature | tick, box or text."""
    return fill_table(table, [
        (r["feature"], TICK if r["in_scope"] is True else BOX if r["in_scope"] is False else r["text"]) for r in rows
    ])


def discovery_rows(table: Table, answers: list[dict]) -> Group:
    """The Discovery table: question | answer."""
    return fill_table(table, [(a["question"], a["answer"]) for a in answers])


def diagram(p: Paragraph, image: dict | None) -> Group:
    """The flow diagram image with its title under it, or the placeholder removed."""
    if image is None:
        return Group(p.s, _delete_paragraph(p))
    reqs = _replace_paragraph(p, "\n" + " ".join(image["title"].split()))
    reqs.append({"insertInlineImage": {"location": {"index": p.s}, "uri": image["url"],
                                       "objectSize": {"width": {"magnitude": IMAGE_WIDTH_PT, "unit": "PT"}}}})
    return Group(p.s, reqs)


def documentation(p: Paragraph, links: list[dict]) -> Group:
    """A bulleted list of titles, each linked to its page."""
    if not links:
        return Group(p.s, _delete_paragraph(p))
    titles = [" ".join(l["title"].split()) or l["url"] for l in links]
    text = "\n".join(titles)
    reqs = _replace_paragraph(p, text)
    at = p.s
    for title, link in zip(titles, links):
        end = at + utf16_len(title)
        reqs.append(_style(at, end, {"link": {"url": link["url"]}, "bold": False}, "link,bold"))
        at = end + 1
    reqs.append({"createParagraphBullets": {"range": {"startIndex": p.s, "endIndex": p.s + utf16_len(text)}, "bulletPreset": BULLETS}})
    return Group(p.s, reqs)


def _is_section_title(item) -> bool:
    """The master marks a new section (1.0, 2.0, ...) with a one-cell table, or a level-1 heading."""
    if isinstance(item, Table):
        return all(len(r.cells) == 1 for r in item.rows)
    return isinstance(item, Paragraph) and item.heading_level == 1


def further_blocks(outline: Outline, keep: set[int]) -> list[Group]:
    """
    The master may carry a second block for a further track: a level-2 heading with a {{Track}} token
    ("2.2 {{Track}} Scope", "3.2 {{Track}} Solution") and everything under it up to the next section
    title. With one track those blocks are removed whole (any empty paragraphs just before them too),
    so no token is left behind. `keep` holds the outline positions of the paragraphs the first track uses.
    """
    groups = []
    for heading in outline.paragraphs:
        if heading.heading_level != 2 or not any(t in heading.text for t in TOKENS["track"]):
            continue
        start_item = heading
        for item in reversed(outline.items[:heading.index]):
            if isinstance(item, Paragraph) and not item.text.strip():
                start_item = item
            else:
                break
        last = heading
        for item in outline.items[heading.index + 1:]:
            if _is_section_title(item):
                break
            if item is not None:
                last = item
        # Keep the block's final newline: the Docs API refuses to delete the newline before a table, and
        # the next section title is a table in the master.
        end = last.e - 1 if isinstance(last, Paragraph) else last.e
        inside = [p.index for p in outline.paragraphs if start_item.s <= p.s < end]
        if any(i in keep for i in inside):
            continue  # the first track's own block (its heading may carry {{Track}} too)
        if end > start_item.s:
            groups.append(Group(start_item.s, [{"deleteContentRange": {"range": {"startIndex": start_item.s, "endIndex": end}}}]))
    return groups


def track_label(name: str) -> str:
    """What {{Track}} becomes: 'Project' for the default track (so headings read 'Project Scope')."""
    return "Project" if name.strip().casefold() == DEFAULT_TRACK.casefold() else name.strip()


def _replace_all(token_key: str, text: str) -> list[dict]:
    return [{"replaceAllText": {"containsText": {"text": spelling, "matchCase": True}, "replaceText": text}}
            for spelling in TOKENS[token_key]]


def plan_document(outline: Outline, *, merchant: str, introduction: dict, track: dict) -> dict:
    """
    track: {name, discovery: [{question, answer}], features: [{feature, in_scope, text}],
            technical_considerations: [str], integration_design: [str], diagram: {title, url} | None,
            links: [{title, url}]}
    Returns {"requests": [...], "summary": {...}}. One track for now; further tracks are regenerated blocks (next).
    """
    tokens = {key: find_token(outline, key) for key in ("background", "goals", "considerations", "design",
                                                        "diagrams", "documentation")}
    table = features_table(outline)
    # Discovery: a Question | Answer table under the heading when the master has one, else the {{Discovery}} paragraph
    disc_table = discovery_table(outline)
    if disc_table is not None:
        disc_group = discovery_rows(disc_table, track["discovery"])
    else:
        tokens["discovery"] = find_token(outline, "discovery")
        disc_group = discovery(tokens["discovery"], track["discovery"])
    groups = [
        plain_paragraphs(tokens["background"], introduction.get("background") or []),
        plain_paragraphs(tokens["goals"], introduction.get("goals") or []),
        disc_group,
        features(table, track["features"]),
        plain_paragraphs(tokens["considerations"], track["technical_considerations"]),
        plain_paragraphs(tokens["design"], track["integration_design"]),
        diagram(tokens["diagrams"], track.get("diagram")),
        documentation(tokens["documentation"], track["links"]),
    ]
    removed = further_blocks(outline, {p.index for p in tokens.values()})
    groups += removed
    anchors = [g.anchor for g in groups]
    if len(set(anchors)) != len(anchors):
        raise _bad("two tokens share a paragraph.")
    for g in removed:  # a removed block must not overlap any edit of the first track
        end = g.requests[0]["deleteContentRange"]["range"]["endIndex"]
        if any(g.anchor <= other.anchor < end for other in groups if other is not g):
            raise _bad("a further track's block overlaps the first track's paragraphs.")
    requests: list[dict] = []
    for g in sorted(groups, key=lambda g: g.anchor, reverse=True):
        requests += g.requests
    requests += _replace_all("merchant", merchant.strip())
    requests += _replace_all("track", track_label(track["name"]))
    return {
        "requests": requests,
        "summary": {
            "discovery_rows": len(track["discovery"]),
            "feature_rows": len(track["features"]),
            "considerations": len(track["technical_considerations"]),
            "design": len(track["integration_design"]),
            "diagram": bool(track.get("diagram")),
            "links": len(track["links"]),
            "background": bool(introduction.get("background")),
            "goals": bool(introduction.get("goals")),
            "blocks_removed": len(removed),
            "discovery_as_table": disc_table is not None,
        },
    }
