"""The 'Suggested additions' section at the end of a scope sheet.

Questions the IM didn't pick but should look at go here, for the IM to review in the sheet:
bank questions the merchant material answered, and new questions no bank question covers (found in
the material, or drafted by our model for a topic in the IM's notes that the bank doesn't cover).
New questions get a temporary ID (NEW-0001, ...) in the hidden id column, so later runs can tell
what the IM kept, edited or removed. The section isn't collapsible, so it stays in view.
"""

import re
from collections.abc import Iterable

from imcp.db import enums as E
from imcp.db.models import Question
from imcp.scope.candidates import SUBSECTION_LABELS

ADDITIONS_LABEL = "Suggested additions"
NEW_ID = re.compile(r"NEW-(\d{4,})")
HEADER_FILL = {"red": 0.91, "green": 0.94, "blue": 0.99}  # same as the section headings


def new_ids(existing: Iterable[str], n: int) -> list[str]:
    """The next n temporary IDs after the highest NEW- ID already used."""
    numbers = [int(m.group(1)) for v in existing if (m := NEW_ID.fullmatch(str(v).strip()))]
    start = max(numbers, default=0) + 1
    return [f"NEW-{i:04d}" for i in range(start, start + n)]


def _key(name: str) -> str:
    return str(name or "").strip().lower()


def row_from(header: list[str], cells: dict) -> list:
    """Cell values in header order. Columns the row doesn't set stay empty."""
    return [cells.get(_key(name)) for name in header]


def _join(values) -> str | None:
    return ", ".join(getattr(v, "value", v) for v in values) or None


def bank_cells(q: Question) -> dict:
    """A bank question's own columns, as the master shows them."""
    join = _join
    return {
        "id": q.question_id,
        "enum": E.QuestionType(q.type).value,
        "question": q.text,
        "options": " | ".join(q.options) or None,
        "notes": q.notes,
        "priority": q.priority,
        "subsection": SUBSECTION_LABELS[E.Subsection(q.subsection)],
        "channels": join(q.channels),
        "pillars": join(q.pillars),
        "category": join(q.categories),
        "platform": join(q.platforms),
    }


def new_cells(new_id: str, item: dict) -> dict:
    """A new question's columns. Priority stays empty, so a priority filter never hides it."""
    return {
        "id": new_id,
        "enum": item.get("type") or "free_text",
        "question": item["question"],
        "options": " | ".join(item.get("options") or []) or None,
        "subsection": SUBSECTION_LABELS.get(E.Subsection(item["subsection"])) if item.get("subsection") else None,
    }


def _cell(value) -> dict:
    if value is None or value == "":
        return {}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return {"userEnteredValue": {"numberValue": value}}
    return {"userEnteredValue": {"stringValue": str(value)}}


def section_requests(tab_sheet_id: int, start_row: int, rows: list[list], width: int, label_column: int,
                     with_label: bool, row_count: int) -> tuple[list[dict], int]:
    """
    Requests that write the additions from `start_row` down: the section label row first if
    `with_label`, then the rows. Rows are added to the grid when it is too short.
    Returns the requests and the grid's row count afterwards.
    """
    if not rows:
        return [], row_count
    block: list[list] = []
    if with_label:
        label = [None] * width
        label[label_column] = ADDITIONS_LABEL
        block.append(label)
    block += [(r + [None] * width)[:width] for r in rows]
    end = start_row + len(block)
    reqs: list[dict] = []
    if end > row_count:
        reqs.append({"appendDimension": {"sheetId": tab_sheet_id, "dimension": "ROWS", "length": end - row_count}})
    reqs.append({"updateCells": {
        "range": {"sheetId": tab_sheet_id, "startRowIndex": start_row, "endRowIndex": end,
                  "startColumnIndex": 0, "endColumnIndex": width},
        "rows": [{"values": [_cell(v) for v in r]} for r in block],
        "fields": "userEnteredValue",
    }})
    if with_label:
        reqs.append({"repeatCell": {
            "range": {"sheetId": tab_sheet_id, "startRowIndex": start_row, "endRowIndex": start_row + 1,
                      "startColumnIndex": 0, "endColumnIndex": width},
            "cell": {"userEnteredFormat": {"textFormat": {"bold": True}, "wrapStrategy": "OVERFLOW_CELL",
                                           "backgroundColorStyle": {"rgbColor": HEADER_FILL}}},
            "fields": "userEnteredFormat.textFormat.bold,userEnteredFormat.wrapStrategy,"
                      "userEnteredFormat.backgroundColorStyle",
        }})
    return reqs, max(end, row_count)


def label_needed(ids: list[str], added_before: set[str]) -> bool:
    """
    Whether the sheet still needs the 'Suggested additions' label row: only when nothing follows the
    last question the scope itself chose. Otherwise the section is already there (its label, which
    has no ID, or rows the IM kept after deleting the label).
    ids: column A below the header. added_before: bank IDs earlier runs appended as additions.
    """
    core = [i for i, v in enumerate(ids) if v and not NEW_ID.fullmatch(v) and v not in added_before]
    tail = ids[core[-1] + 1:] if core else ids
    return not tail
