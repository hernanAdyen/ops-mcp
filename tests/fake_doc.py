"""A stand-in Google Doc that plays a Docs batchUpdate on an index model, like FakeTab for Sheets.

The document is a list of atoms, one per UTF-16 index, the way the Docs API counts:
  a character (including each paragraph's final "\\n"), an inline image, or a structural marker:
  "T" table start, "R" row start, "C" cell start, "/T" table end. The section break is index 0.
Text style lives on character atoms; paragraph style and bullets live on the paragraph's "\\n".
"""

from dataclasses import dataclass, field

from imcp.proposal.outline import ElementIn


@dataclass
class Atom:
    kind: str  # "ch" | "img" | "T" | "R" | "C" | "/T" | "sb"
    ch: str = ""
    style: dict = field(default_factory=dict)  # text style for "ch"; {"uri": ...} for "img"
    para: dict = field(default_factory=dict)  # paragraph style and bullet, on the paragraph's "\n"


class FakeDoc:
    def __init__(self):
        self.atoms: list[Atom] = [Atom("sb")]

    # --- building a template ---------------------------------------------------------------------

    def paragraph(self, text: str, style: str = "NORMAL_TEXT", bold: bool = False) -> "FakeDoc":
        for ch in text:
            self.atoms.append(Atom("ch", ch, {"bold": True} if bold else {}))
        self.atoms.append(Atom("ch", "\n", {}, {"style": style}))
        return self

    def image(self, uri: str = "https://img.example.com/placeholder.png") -> "FakeDoc":
        self.atoms.append(Atom("img", "", {"uri": uri}))
        self.atoms.append(Atom("ch", "\n", {}, {"style": "NORMAL_TEXT"}))
        return self

    def table(self, rows: list[list[str]]) -> "FakeDoc":
        self.atoms.append(Atom("T"))
        for row in rows:
            self.atoms.append(Atom("R"))
            for cell in row:
                self.atoms.append(Atom("C"))
                for ch in cell:
                    self.atoms.append(Atom("ch", ch))
                self.atoms.append(Atom("ch", "\n", {}, {"style": "NORMAL_TEXT"}))
        self.atoms.append(Atom("/T"))
        return self

    # --- reading ---------------------------------------------------------------------------------

    def outline(self) -> list[ElementIn]:
        """The compact outline the skill would derive from documents.get."""
        items: list[ElementIn] = [ElementIn(s=None, e=1, kind="sectionBreak")]
        i = 1
        while i < len(self.atoms):
            a = self.atoms[i]
            if a.kind == "T":
                table_start = i
                i += 1
                rows = []
                while self.atoms[i].kind == "R":
                    row_start = i
                    i += 1
                    cells = []
                    while self.atoms[i].kind == "C":
                        cell_start = i
                        i += 1
                        text = ""
                        while self.atoms[i].kind in ("ch", "img"):
                            text += self.atoms[i].ch if self.atoms[i].kind == "ch" else ""
                            i += 1
                        cells.append({"s": cell_start, "e": i, "text": text.rstrip("\n")})
                    rows.append({"s": row_start, "e": i, "cells": cells})
                assert self.atoms[i].kind == "/T"
                i += 1
                items.append(ElementIn(s=table_start, e=i, rows=rows))
            else:
                start = i
                text, style = "", "NORMAL_TEXT"
                while True:
                    a = self.atoms[i]
                    i += 1
                    if a.kind == "ch":
                        if a.ch == "\n":
                            style = a.para.get("style", "NORMAL_TEXT")
                            break
                        text += a.ch
                items.append(ElementIn(s=start, e=i, text=text, style=style))
        return items

    def paragraphs(self) -> list[dict]:
        """[{text, style, bullet, bold: [runs], links: {text: url}, images: [uri]}] for body paragraphs outside tables."""
        out, depth = [], 0
        cur = {"text": "", "bold": [], "links": {}, "images": [], "_run": "", "_link": ""}
        for a in self.atoms[1:]:
            if a.kind in ("T", "R", "C"):
                depth += 1 if a.kind == "T" else 0
                continue
            if a.kind == "/T":
                depth -= 1
                continue
            if depth:
                continue
            if a.kind == "img":
                cur["images"].append(a.style["uri"])
                continue
            if a.ch == "\n":
                if cur["_run"]:
                    cur["bold"].append(cur["_run"])
                out.append({"text": cur["text"], "style": a.para.get("style", "NORMAL_TEXT"), "bullet": a.para.get("bullet", False),
                            "bold": cur["bold"], "links": cur["links"], "images": cur["images"]})
                cur = {"text": "", "bold": [], "links": {}, "images": [], "_run": "", "_link": ""}
                continue
            cur["text"] += a.ch
            if a.style.get("bold"):
                cur["_run"] += a.ch
            elif cur["_run"]:
                cur["bold"].append(cur["_run"])
                cur["_run"] = ""
            link = a.style.get("link", {}).get("url")
            if link:
                cur["links"][link] = cur["links"].get(link, "") + a.ch
        return out

    def tables(self) -> list[list[list[str]]]:
        out, i = [], 0
        while i < len(self.atoms):
            if self.atoms[i].kind == "T":
                rows, i = [], i + 1
                while self.atoms[i].kind == "R":
                    cells, i = [], i + 1
                    while self.atoms[i].kind == "C":
                        text, i = "", i + 1
                        while self.atoms[i].kind in ("ch", "img"):
                            text += self.atoms[i].ch
                            i += 1
                        cells.append(text.rstrip("\n"))
                    rows.append(cells)
                out.append(rows)
            i += 1
        return out

    def text(self) -> str:
        return "".join(a.ch for a in self.atoms if a.kind == "ch")

    # --- playing a batch -------------------------------------------------------------------------

    def apply(self, requests: list[dict]) -> None:
        for req in requests:
            [(name, body)] = req.items()
            getattr(self, f"_{name}")(body)

    def _insertText(self, body):
        index, text = body["location"]["index"], body["text"]
        self._check_insert_point(index)
        prev = self.atoms[index - 1]
        base = dict(prev.style) if prev.kind == "ch" and prev.ch != "\n" else {}
        para = self._paragraph_style_at(index)
        new = [Atom("ch", ch, dict(base), dict(para) if ch == "\n" else {}) for ch in text]
        self.atoms[index:index] = new

    def _paragraph_style_at(self, index: int) -> dict:
        for a in self.atoms[index:]:
            if a.kind == "ch" and a.ch == "\n":
                return a.para
            if a.kind not in ("ch", "img"):
                break
        return {"style": "NORMAL_TEXT"}

    def _check_insert_point(self, index: int) -> None:
        assert 1 <= index < len(self.atoms), f"index {index} is outside the document"
        assert self.atoms[index].kind in ("ch", "img"), f"can't insert at a structural marker (index {index})"
        assert self.atoms[index - 1].kind not in ("T", "/T", "R"), f"can't insert between table markers (index {index})"

    def _insertInlineImage(self, body):
        index = body["location"]["index"]
        self._check_insert_point(index)
        self.atoms.insert(index, Atom("img", "", {"uri": body["uri"], "size": body.get("objectSize")}))

    def _deleteContentRange(self, body):
        s, e = body["range"]["startIndex"], body["range"]["endIndex"]
        assert 1 <= s < e <= len(self.atoms), f"bad range {s}-{e}"
        kinds = [a.kind for a in self.atoms[s:e]]
        # a table may be deleted whole, never in part
        assert kinds.count("T") == kinds.count("/T"), f"range {s}-{e} cuts through a table"
        assert self.atoms[s].kind not in ("R", "C", "/T") and all(
            k in ("ch", "img", "T", "R", "C", "/T") for k in kinds), f"range {s}-{e} starts inside a table"
        depth = 0
        for k in kinds:
            depth += (k == "T") - (k == "/T")
            assert depth >= 0, f"range {s}-{e} cuts through a table"
        # the last newline of a cell, of the document, or of the paragraph before a table can't go
        assert not (self.atoms[e - 1].kind == "ch" and self.atoms[e - 1].ch == "\n"
                    and (e >= len(self.atoms) or self.atoms[e].kind in ("C", "R", "/T", "T"))), \
            f"range {s}-{e} would delete a final newline the Docs API protects"
        del self.atoms[s:e]

    def _updateTextStyle(self, body):
        s, e = body["range"]["startIndex"], body["range"]["endIndex"]
        fields = body["fields"].split(",")
        for a in self.atoms[s:e]:
            if a.kind == "ch":
                for f in fields:
                    a.style[f] = body["textStyle"].get(f)

    def _updateParagraphStyle(self, body):
        s, e = body["range"]["startIndex"], body["range"]["endIndex"]
        for a in self._paragraph_ends(s, e):
            if "namedStyleType" in body["paragraphStyle"]:
                a.para["style"] = body["paragraphStyle"]["namedStyleType"]

    def _createParagraphBullets(self, body):
        s, e = body["range"]["startIndex"], body["range"]["endIndex"]
        for a in self._paragraph_ends(s, e):
            a.para["bullet"] = True

    def _paragraph_ends(self, s: int, e: int) -> list[Atom]:
        """The "\\n" atoms of the paragraphs overlapping [s, e)."""
        ends, i = [], s
        while i < len(self.atoms):
            a = self.atoms[i]
            if a.kind == "ch" and a.ch == "\n":
                ends.append(a)
                if i >= e - 1:
                    break
            i += 1
        return ends

    def _insertTableRow(self, body):
        loc = body["tableCellLocation"]
        t = loc["tableStartLocation"]["index"]
        assert self.atoms[t].kind == "T", f"no table starts at {t}"
        # find the rows
        i, rows = t + 1, []
        while self.atoms[i].kind == "R":
            start, i, cols = i, i + 1, 0
            while self.atoms[i].kind == "C":
                cols, i = cols + 1, i + 1
                while self.atoms[i].kind in ("ch", "img"):
                    i += 1
            rows.append((start, i, cols))
        start, end, cols = rows[loc["rowIndex"]]
        at = end if body["insertBelow"] else start
        new = [Atom("R")]
        for _ in range(cols):
            new += [Atom("C"), Atom("ch", "\n", {}, {"style": "NORMAL_TEXT"})]
        self.atoms[at:at] = new

    def _replaceAllText(self, body):
        needle, replacement = body["containsText"]["text"], body["replaceText"]
        positions = [i for i, a in enumerate(self.atoms) if a.kind == "ch"]
        text = "".join(self.atoms[i].ch for i in positions)
        start = 0
        while True:
            found = text.find(needle, start)
            if found == -1:
                break
            # replace in atoms, from the back of this match
            idxs = positions[found:found + len(needle)]
            style = dict(self.atoms[idxs[0]].style)
            self.atoms[idxs[0]:idxs[-1] + 1] = [Atom("ch", ch, dict(style)) for ch in replacement]
            positions = [i for i, a in enumerate(self.atoms) if a.kind == "ch"]
            text = "".join(self.atoms[i].ch for i in positions)
            start = found + len(replacement)
