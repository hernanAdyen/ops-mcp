"""The Docs batch that fills a proposal copy. A pure function over the outline and the content.

The master is a single-tab Google Doc with {{tokens}} where content goes:
  {{Merchant Name}}                      on the cover and in the header (replaced everywhere)
  {{Project Background}} {{Project Goals}}   1.4 and 1.5
  a track block in section 2: a level-2 heading "2.x {{Track}} - Scope" with Discovery (a
  Question | Answer table with a header row and one empty body row, or a {{Discovery}} paragraph)
  and the Features & Functionality table (a header row and exactly one empty body row); and a
  track block in section 3: "3.x {{Track}} - Proposed Solution" with {{Technical Considerations}},
  {{Integration Design}}, {{Flow Diagrams}} and {{Documentation}}.

The block whose heading carries {{Track}} is the template. Any other block in those sections (a
project-level "2.1 Project Scope" block, say) is removed whole. Track 1 fills the template in place,
headings renumbered to 2.1 and 3.1 and named after the track. Each further track gets a block
rebuilt from the template by index, inserted after the one before it, numbered 2.2, 3.2 and so on.

Every edit that uses an index is computed from the outline and applied from the end of the
document backwards, so earlier indexes stay valid; a generated block is written forwards from one
anchor, each piece appended at a running cursor; replaceAllText runs last because it changes
lengths. The IM's Claude relays the batch unchanged.
"""

import re
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



NUMBER = re.compile(r"^(\d+)\.(\d+)(?=\D|$)")  # "2.2 ..." -> section 2, block 2 (and "2.2.1 ..." starts the same way)


def _is_section_title(item) -> bool:
    """The master marks a new section (1.0, 2.0, ...) with a one-cell table, or a level-1 heading."""
    if isinstance(item, Table):
        return all(len(r.cells) == 1 for r in item.rows)
    return isinstance(item, Paragraph) and item.heading_level == 1


def _has_track_token(text: str) -> bool:
    return any(t in text for t in TOKENS["track"])


@dataclass
class Block:
    """A track block: a level-2 heading and everything under it up to the next level-2 heading or section title."""

    heading: Paragraph
    items: list  # outline items from the heading on, in order
    end: int  # index where the item after the block starts
    kind: str  # "scope" | "solution"
    section: int  # 2 or 3, from the heading's number
    start_item: object  # the heading, or the first of the empty paragraphs just before it (removed with it)

    @property
    def is_template(self) -> bool:
        return _has_track_token(self.heading.text)

    @property
    def start(self) -> int:
        return self.start_item.s

    def paragraphs(self) -> list[Paragraph]:
        return [i for i in self.items if isinstance(i, Paragraph)]

    def tables(self) -> list[Table]:
        return [i for i in self.items if isinstance(i, Table)]


def _kind_of(items: list) -> str | None:
    text = " ".join(i.text for i in items if isinstance(i, Paragraph)).casefold()
    if FEATURES_HEADING in text or any(t.casefold() in text for t in TOKENS["discovery"]) or DISCOVERY_HEADING in text:
        return "scope"
    if any(t.casefold() in text for key in ("considerations", "design", "diagrams", "documentation") for t in TOKENS[key]):
        return "solution"
    return None


def find_blocks(outline: Outline) -> list[Block]:
    blocks: list[Block] = []
    items = outline.items
    starts = [i for i, item in enumerate(items)
              if isinstance(item, Paragraph) and item.heading_level == 2 and item.text.strip()]
    for n, idx in enumerate(starts):
        heading = items[idx]
        end_idx = len(items)
        for j in range(idx + 1, len(items)):
            item = items[j]
            if item is None:
                continue
            if _is_section_title(item) or (isinstance(item, Paragraph) and item.heading_level == 2 and item.text.strip()):
                end_idx = j
                break
        block_items = [i for i in items[idx:end_idx] if i is not None]
        kind = _kind_of(block_items)
        if kind is None:
            continue
        m = NUMBER.match(heading.text.strip())
        section = int(m.group(1)) if m else (2 if kind == "scope" else 3)
        start_item = heading
        for item in reversed(items[:idx]):
            if isinstance(item, Paragraph) and not item.text.strip():
                start_item = item
            else:
                break
        end = items[end_idx].s if end_idx < len(items) and items[end_idx] is not None else outline.end
        blocks.append(Block(heading, block_items, end, kind, section, start_item))
    return blocks


def pick_template(blocks: list[Block], kind: str) -> Block:
    """The block with {{Track}} in its heading; else the first block of that kind."""
    of_kind = [b for b in blocks if b.kind == kind]
    if not of_kind:
        raise _bad(f"there is no {kind} block (a level-2 heading with the {kind} parts under it).")
    return next((b for b in of_kind if b.is_template), of_kind[0])


def remove_block(block: Block, outline: Outline | None = None) -> Group:
    """Delete the block whole. When a paragraph follows the block, its last newline goes too and nothing is
    left behind. When a table follows (a section title), the Docs API protects the newline before it: that
    one newline stays as an empty paragraph, set to normal text in case it was a heading."""
    last = block.items[-1]
    following = next((i for i in outline.items if i is not None and i.s == block.end), None) if outline else None
    keep_newline = isinstance(last, Paragraph) and not isinstance(following, Paragraph)
    end = last.e - 1 if keep_newline else last.e
    if end <= block.start:
        return Group(block.start, [])
    reqs = [{"deleteContentRange": {"range": {"startIndex": block.start, "endIndex": end}}}]
    if keep_newline:
        reqs.append({"updateParagraphStyle": {"range": {"startIndex": block.start, "endIndex": block.start + 1},
                                              "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"}, "fields": "namedStyleType"}})
    return Group(block.start, reqs)


def track_label(name: str) -> str:
    """What {{Track}} becomes: 'Project' for the default track (so headings read 'Project Scope')."""
    return "Project" if name.strip().casefold() == DEFAULT_TRACK.casefold() else name.strip()


def heading_text(template: str, section: int, number: int, label: str) -> str:
    """The template heading renumbered to section.number and with {{Track}} replaced by the track's label."""
    text = NUMBER.sub(f"{section}.{number}", template.strip(), count=1)
    for spelling in TOKENS["track"]:
        text = text.replace(spelling, label)
    return text


def _in_block(outline: Outline, block: Block, key: str) -> Paragraph:
    p = find_token(outline, key, after=block.heading.index)
    if p.s >= block.end:
        raise _bad(f"the paragraph {TOKENS[key][0]} is missing from the block {block.heading.text.strip()!r}.")
    return p


def _token_in_block(block: Block, key: str) -> Paragraph | None:
    return next((p for p in block.paragraphs() if p.text.strip() in TOKENS[key]), None)


def _skip_empty(items: list, i: int) -> bool:
    """An empty template paragraph isn't written when a table follows it (insertTable adds that newline)
    or when it ends the block (the insertion point's own empty paragraph stays as the separator)."""
    item = items[i]
    if not isinstance(item, Paragraph) or item.text.strip():
        return False
    return i == len(items) - 1 or isinstance(items[i + 1], Table)


def renumber_headings(block: Block, number: int, label: str) -> list[Group]:
    """Rewrite the block's headings for track `number`: new number, track name in place of the token."""
    groups = []
    for p in block.paragraphs():
        if p.heading_level in (2, 3) and p.text.strip():
            new = heading_text(p.text, block.section, number, label)
            if new != p.text.strip():
                groups.append(Group(p.s, _replace_paragraph(p, new)))
    return groups


def fill_scope_block(outline: Outline, block: Block, track: dict) -> list[Group]:
    """Track 1's Discovery and Features in the template scope block."""
    groups = []
    table = discovery_table(outline, after=block.heading.index)
    if table is not None and table.s < block.end:
        groups.append(discovery_rows(table, track["discovery"]))
        token = _token_in_block(block, "discovery")
        if token is not None:  # the master keeps a {{Discovery}} paragraph next to the table: empty it
            groups.append(Group(token.s, _delete_paragraph(token)))
    else:
        groups.append(discovery(_in_block(outline, block, "discovery"), track["discovery"]))
    features_tab = features_table(outline, after=block.heading.index)
    if features_tab.s >= block.end:
        raise _bad(f"the Features & Functionality table is missing from the block {block.heading.text.strip()!r}.")
    groups.append(features(features_tab, track["features"]))
    return groups


def fill_solution_block(outline: Outline, block: Block, track: dict) -> list[Group]:
    """Track 1's considerations, design, diagram and links in the template solution block."""
    return [
        plain_paragraphs(_in_block(outline, block, "considerations"), track["technical_considerations"]),
        plain_paragraphs(_in_block(outline, block, "design"), track["integration_design"]),
        diagram(_in_block(outline, block, "diagrams"), track.get("diagram")),
        documentation(_in_block(outline, block, "documentation"), track["links"]),
    ]


class BlockWriter:
    """Writes a new block forwards from one index: every piece is appended at a running cursor, so
    the indexes it uses are right at the moment each request is applied. The insertion point must be
    the start of an empty paragraph (the separator before the next section title), which stays after
    the written block."""

    def __init__(self, at: int):
        self.cursor = at
        self.requests: list[dict] = []

    def paragraph(self, text: str, style: str | None = None, bold: bool = False) -> tuple[int, int]:
        text = " ".join(text.split())
        start = self.cursor
        self.requests.append({"insertText": {"location": {"index": start}, "text": text + "\n"}})
        end = start + utf16_len(text)
        if style:
            self.requests.append({"updateParagraphStyle": {"range": {"startIndex": start, "endIndex": end + 1},
                                                           "paragraphStyle": {"namedStyleType": style}, "fields": "namedStyleType"}})
        if text:
            self.requests.append(_style(start, end, {"bold": bold}, "bold"))
        self.cursor = end + 1
        return start, end

    def table(self, header: tuple[str, str], rows: list[tuple[str, str]]) -> None:
        """A two-column table: the header row and one row per item. insertTable puts a newline before the table."""
        cols = 2
        all_rows = [header] + [(" ".join(a.split()), " ".join(b.split())) for a, b in rows]
        if len(all_rows) == 1:
            all_rows.append(("", ""))  # keep the master's shape: a header and one empty row
        self.requests.append({"insertTable": {"rows": len(all_rows), "columns": cols, "location": {"index": self.cursor}}})
        table_start = self.cursor + 1
        row_span = 1 + EMPTY_CELL * cols
        cell_at = lambda j, m: table_start + 1 + j * row_span + 2 + 2 * m  # noqa: E731
        for j in range(len(all_rows) - 1, -1, -1):
            for m in (1, 0):
                text = all_rows[j][m]
                if text:
                    self.requests.append({"insertText": {"location": {"index": cell_at(j, m)}, "text": text}})
        for m in (0, 1):  # header cells are filled last, so their indexes are the computed ones
            if header[m]:
                self.requests.append(_style(cell_at(0, m), cell_at(0, m) + utf16_len(header[m]), {"bold": True}, "bold"))
        size = 1 + len(all_rows) * row_span + 1
        self.cursor = table_start + size + sum(utf16_len(t) for r in all_rows for t in r)

    def image(self, url: str, title: str) -> None:
        self.requests.append({"insertText": {"location": {"index": self.cursor}, "text": "\n"}})
        self.requests.append({"insertInlineImage": {"location": {"index": self.cursor}, "uri": url,
                                                    "objectSize": {"width": {"magnitude": IMAGE_WIDTH_PT, "unit": "PT"}}}})
        self.cursor += 2
        self.paragraph(title)

    def bullets(self, links: list[dict]) -> None:
        start = self.cursor
        for link in links:
            title = " ".join(link["title"].split()) or link["url"]
            s, e = self.paragraph(title)
            self.requests.append(_style(s, e, {"link": {"url": link["url"]}}, "link"))
        if links:
            self.requests.append({"createParagraphBullets": {"range": {"startIndex": start, "endIndex": self.cursor - 1},
                                                             "bulletPreset": BULLETS}})


def _table_header(table: Table) -> tuple[str, str]:
    return tuple(c.text.strip() for c in table.rows[0].cells)  # type: ignore[return-value]


def write_scope_block(writer: BlockWriter, outline: Outline, template: Block, number: int, track: dict) -> None:
    """A further track's scope block, built piece by piece in the template's order."""
    label = track_label(track["name"])
    disc_table = discovery_table(outline, after=template.heading.index)
    disc_table = disc_table if disc_table is not None and disc_table.s < template.end else None
    features_tab = features_table(outline, after=template.heading.index)
    for i, item in enumerate(template.items):
        if isinstance(item, Table):
            if disc_table is not None and item.s == disc_table.s:
                writer.table(_table_header(item), [(a["question"], a["answer"]) for a in track["discovery"]])
            elif item.s == features_tab.s:
                writer.table(_table_header(item), [(r["feature"], TICK if r["in_scope"] is True else BOX if r["in_scope"] is False else r["text"])
                                                   for r in track["features"]])
            continue
        if _skip_empty(template.items, i):
            continue
        if item.heading_level in (2, 3):
            writer.paragraph(heading_text(item.text, template.section, number, label), f"HEADING_{item.heading_level}")
        elif item.text.strip() in TOKENS["discovery"]:
            if disc_table is not None:
                continue  # the answers go in the table; the token paragraph has no counterpart
            for a in track["discovery"]:
                writer.paragraph(a["question"], bold=True)
                writer.paragraph(a["answer"])
        elif not item.is_token:
            writer.paragraph(item.text)


def write_solution_block(writer: BlockWriter, template: Block, number: int, track: dict) -> None:
    label = track_label(track["name"])
    for i, item in enumerate(template.items):
        if isinstance(item, Table) or _skip_empty(template.items, i):
            continue
        text = item.text.strip()
        if item.heading_level in (2, 3):
            writer.paragraph(heading_text(item.text, template.section, number, label), f"HEADING_{item.heading_level}")
        elif text in TOKENS["considerations"]:
            for para in track["technical_considerations"]:
                writer.paragraph(para)
        elif text in TOKENS["design"]:
            for para in track["integration_design"]:
                writer.paragraph(para)
        elif text in TOKENS["diagrams"]:
            if track.get("diagram"):
                writer.image(track["diagram"]["url"], track["diagram"]["title"])
        elif text in TOKENS["documentation"]:
            writer.bullets(track["links"])
        elif not item.is_token:
            writer.paragraph(item.text)


def _insertion_point(outline: Outline, block: Block) -> int:
    """Where a block for a further track goes: the empty paragraph that ends the template block (or follows it).
    Writing there puts the new block before that paragraph, which stays as the separator before the next section."""
    last = block.items[-1]
    if isinstance(last, Paragraph) and not last.text.strip():
        return last.s
    after = next((i for i in outline.items if i is not None and i.s == block.end), None)
    if not isinstance(after, Paragraph) or after.text.strip():
        raise _bad(f"an empty paragraph is needed after the block {block.heading.text.strip()!r} (before the next section), "
                   "so further tracks can be added after it.")
    return after.s


def _replace_all(token_key: str, text: str) -> list[dict]:
    return [{"replaceAllText": {"containsText": {"text": spelling, "matchCase": True}, "replaceText": text}}
            for spelling in TOKENS[token_key]]


def plan_document(outline: Outline, *, merchant: str, introduction: dict, tracks: list[dict]) -> dict:
    """
    tracks: in tab order, each {name, discovery: [{question, answer}], features: [{feature, in_scope, text}],
            technical_considerations: [str], integration_design: [str], diagram: {title, url} | None,
            links: [{title, url}]}
    Returns {"requests": [...], "summary": {...}}.
    """
    if not tracks:
        raise _bad("the proposal needs at least one track.")
    first = tracks[0]
    blocks = find_blocks(outline)
    scope, solution = pick_template(blocks, "scope"), pick_template(blocks, "solution")
    removed = [remove_block(b, outline) for b in blocks if b is not scope and b is not solution]
    label = track_label(first["name"])

    groups = [
        plain_paragraphs(find_token(outline, "background"), introduction.get("background") or []),
        plain_paragraphs(find_token(outline, "goals"), introduction.get("goals") or []),
    ]
    groups += fill_scope_block(outline, scope, first) + fill_solution_block(outline, solution, first)
    groups += renumber_headings(scope, 1, label) + renumber_headings(solution, 1, label)
    groups += removed

    if len(tracks) > 1:
        scope_writer, solution_writer = BlockWriter(_insertion_point(outline, scope)), BlockWriter(_insertion_point(outline, solution))
        for number, track in enumerate(tracks[1:], start=2):
            write_scope_block(scope_writer, outline, scope, number, track)
            write_solution_block(solution_writer, solution, number, track)
        groups += [Group(_insertion_point(outline, scope), scope_writer.requests),
                   Group(_insertion_point(outline, solution), solution_writer.requests)]

    anchors = [g.anchor for g in groups]
    if len(set(anchors)) != len(anchors):
        raise _bad("two edits land on the same paragraph.")
    for g in removed:  # a removed block must not overlap any other edit
        if not g.requests:
            continue
        end = g.requests[0]["deleteContentRange"]["range"]["endIndex"]
        if any(g.anchor <= other.anchor < end for other in groups if other is not g):
            raise _bad("a removed block overlaps the template block's paragraphs.")
    requests: list[dict] = []
    for g in sorted(groups, key=lambda g: g.anchor, reverse=True):
        requests += g.requests
    requests += _replace_all("merchant", merchant.strip())
    requests += _replace_all("track", label)
    disc_as_table = discovery_table(outline, after=scope.heading.index) is not None
    return {
        "requests": requests,
        "summary": {
            "tracks": len(tracks),
            "discovery_rows": sum(len(t["discovery"]) for t in tracks),
            "feature_rows": sum(len(t["features"]) for t in tracks),
            "considerations": sum(len(t["technical_considerations"]) for t in tracks),
            "design": sum(len(t["integration_design"]) for t in tracks),
            "diagram": sum(1 for t in tracks if t.get("diagram")),
            "links": sum(len(t["links"]) for t in tracks),
            "background": bool(introduction.get("background")),
            "goals": bool(introduction.get("goals")),
            "blocks_removed": sum(1 for g in removed if g.requests),
            "blocks_added": 2 * (len(tracks) - 1),
            "discovery_as_table": disc_as_table,
        },
    }
