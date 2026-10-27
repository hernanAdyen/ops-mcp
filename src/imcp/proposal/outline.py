"""The document outline the skill passes, and its checks.

A Google Doc is big as JSON (a template runs to 100 KB and more), so the skill doesn't pass
`documents.get` through. It derives a compact outline from `body.content`, one item per
structural element, in order:

  paragraph:  {"s": startIndex, "e": endIndex, "text": its text without the final newline, "style": namedStyleType}
              (text may be cut to its first 40 characters, except for a paragraph that contains "{{")
  table:      {"s", "e", "rows": [{"s", "e", "cells": [{"s", "e", "text"}]}]}
  other:      {"s", "e", "kind": "sectionBreak" | "toc"}

Indexes are UTF-16 code units, as the Docs API counts them. The checks here catch copying slips:
elements must be contiguous, a token paragraph's length must match its text, and a table's rows
and cells must line up the way the Docs API lays them out (row = table start + 1, first cell = row
start + 1, an empty cell spans 2, table end = last row end + 1).
"""

from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from imcp.scope.runs import RunError


def utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


class CellIn(BaseModel):
    s: int
    e: int
    text: str = ""


class RowIn(BaseModel):
    s: int
    e: int
    cells: list[CellIn]


class ElementIn(BaseModel):
    s: int | None = None  # the first section break has no startIndex
    e: int
    text: str | None = None
    style: str | None = None
    rows: list[RowIn] | None = None
    kind: str | None = None


@dataclass
class Paragraph:
    s: int
    e: int
    text: str
    style: str
    index: int  # position in the outline

    @property
    def is_token(self) -> bool:
        return "{{" in self.text

    @property
    def heading_level(self) -> int | None:
        return int(self.style[-1]) if self.style.startswith("HEADING_") and self.style[-1].isdigit() else None


@dataclass
class Cell:
    s: int
    e: int
    text: str


@dataclass
class Row:
    s: int
    e: int
    cells: list[Cell]


@dataclass
class Table:
    s: int
    e: int
    rows: list[Row]
    index: int


@dataclass
class Outline:
    items: list = field(default_factory=list)  # Paragraph | Table | None (other), in order

    @property
    def paragraphs(self) -> list[Paragraph]:
        return [i for i in self.items if isinstance(i, Paragraph)]

    @property
    def tables(self) -> list[Table]:
        return [i for i in self.items if isinstance(i, Table)]

    @property
    def end(self) -> int:
        return max(i.e for i in self.items if i is not None)

    def token_paragraphs(self, token: str) -> list[Paragraph]:
        return [p for p in self.paragraphs if p.text.strip() == token]

    def paragraphs_containing(self, text: str) -> list[Paragraph]:
        return [p for p in self.paragraphs if text in p.text]

    def table_after(self, paragraph: Paragraph) -> Table | None:
        """The first table after the paragraph, before the next heading."""
        for item in self.items[paragraph.index + 1:]:
            if isinstance(item, Table):
                return item
            if isinstance(item, Paragraph) and item.heading_level is not None:
                return None
        return None

    def next_heading(self, paragraph: Paragraph, max_level: int) -> Paragraph | None:
        """The next heading of level `max_level` or higher (a smaller number), or None."""
        for item in self.items[paragraph.index + 1:]:
            if isinstance(item, Paragraph) and item.heading_level is not None and item.heading_level <= max_level:
                return item
        return None


def _bad(message: str) -> RunError:
    return RunError(422, f"The outline doesn't line up with the document: {message} Read the document again and "
                         "pass every element's startIndex and endIndex as given.")


def parse_outline(elements: list[ElementIn]) -> Outline:
    if not elements:
        raise _bad("it is empty.")
    out = Outline()
    expected = None
    for n, el in enumerate(elements):
        s = el.s if el.s is not None else (expected if expected is not None else 0)
        if expected is not None and s != expected:
            raise _bad(f"element {n + 1} starts at {s} but the one before ends at {expected}.")
        if el.e <= s:
            raise _bad(f"element {n + 1} ends at {el.e}, before it starts ({s}).")
        if el.rows is not None:
            out.items.append(_table(el, s, n))
        elif el.text is not None or el.style is not None:
            text = el.text or ""
            # A token paragraph may also hold an inline image (one index with no text), so the span
            # may exceed the text; it can never be shorter. The edits use the indexes, never the text length.
            if "{{" in text and el.e - s < utf16_len(text) + 1:
                raise _bad(f"the paragraph {text.strip()[:40]!r} spans {el.e - s} but its text is {utf16_len(text) + 1} long "
                           "(pass its text without the final newline, as read).")
            if el.e - s < 1:
                raise _bad(f"element {n + 1} is too short for a paragraph.")
            out.items.append(Paragraph(s, el.e, text, el.style or "NORMAL_TEXT", len(out.items)))
        else:
            out.items.append(None)
        expected = el.e
    return out


def _table(el: ElementIn, s: int, n: int) -> Table:
    rows: list[Row] = []
    at = s + 1
    for r, row in enumerate(el.rows or []):
        if row.s != at:
            raise _bad(f"table {n + 1}: row {r + 1} starts at {row.s}, expected {at}.")
        cells: list[Cell] = []
        cat = row.s + 1
        for c, cell in enumerate(row.cells):
            if cell.s != cat:
                raise _bad(f"table {n + 1}: row {r + 1} cell {c + 1} starts at {cell.s}, expected {cat}.")
            if cell.e < cell.s + 2:
                raise _bad(f"table {n + 1}: row {r + 1} cell {c + 1} is too short.")
            cells.append(Cell(cell.s, cell.e, cell.text or ""))
            cat = cell.e
        if not cells or row.e != cat:
            raise _bad(f"table {n + 1}: row {r + 1} ends at {row.e}, expected {cat}.")
        rows.append(Row(row.s, row.e, cells))
        at = row.e
    if not rows or el.e != at + 1:
        raise _bad(f"table {n + 1} ends at {el.e}, expected {at + 1}.")
    return Table(s, el.e, rows, n)
