"""Write the answers found in the IM's merchant material into the scope sheet's Project Scope tab.

One exact Sheets batch, as for /create-scope, so no row arithmetic is left to the model:
  - fill the answers the IM hasn't given. Theirs always win: a different finding goes in a note.
  - review columns to the right of the existing ones: source, confidence, status (a dropdown:
    suggested / confirmed / rejected) and ai_note
  - the 'Suggested additions' section at the end (see additions.py)
  - the tab's filter is put back over the new rows and columns
Rows are only added at the end and columns only at the right, so nothing the IM has moves.
"""

from dataclasses import dataclass, field

from imcp.scope.additions import row_from, section_requests
from imcp.scope.sheet_plan import restore_filter

REVIEW_COLUMNS = ("source", "confidence", "status", "ai_note")
STATUS_VALUES = ("suggested", "confirmed", "rejected")
REVIEW_WIDTHS = {"source": 170, "ai_note": 340}
MAX_NOTE = 500


@dataclass
class SheetRead:
    """What the skill read from the tab. Lists are below the header row."""

    tab_sheet_id: int
    column_count: int
    row_count: int
    header: list[str]
    ids: list[str]
    columns: dict[str, list[str]]  # by header name: the answer column and any review columns
    basic_filter: dict | None = None

    @property
    def names(self) -> list[str]:
        return [h.strip().lower() for h in self.header]

    def values(self, name: str) -> list[str]:
        col = self.columns.get(name, [])
        return [str(v or "").strip() for v in col] + [""] * max(0, len(self.ids) - len(col))


@dataclass
class Merge:
    updates: dict[int, dict[str, str]] = field(default_factory=dict)  # sheet row -> column name -> value
    filled: list[str] = field(default_factory=list)
    agreed: list[str] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    skipped_rejected: list[str] = field(default_factory=list)
    answered: set[str] = field(default_factory=set)  # IDs with an answer once the batch is applied


def _norm(value: str) -> str:
    return " ".join(value.casefold().split())


def same_answer(a: str, b: str) -> bool:
    """Equal ignoring case and spacing; multi-choice answers ('A | B') in any order."""
    if "|" in a or "|" in b:
        return {_norm(x) for x in a.split("|") if x.strip()} == {_norm(x) for x in b.split("|") if x.strip()}
    return _norm(a) == _norm(b)


def add_note(old: str, new: str) -> str:
    if not old:
        return new[:MAX_NOTE]
    if _norm(new) in _norm(old):
        return old
    return f"{old} · {new}"[:MAX_NOTE]


def merge_answers(sheet: SheetRead, answers: list[dict]) -> Merge:
    """
    answers: findings for questions in the sheet (id, answer, source, evidence, confidence, problem).
    The IM's answer is never overwritten, and an answer they rejected isn't written again.
    """
    merge = Merge()
    rows = {}
    for i, qid in enumerate(sheet.ids):
        rows.setdefault(qid, i)
    current, status = sheet.values("answer"), sheet.values("status")
    note, source = sheet.values("ai_note"), sheet.values("source")
    merge.answered = {qid for qid, i in rows.items() if qid and current[i]}
    for a in answers:
        i = rows.get(a["id"])
        if i is None:
            continue
        row, value = i + 1, a["answer"]  # +1: the header is row 0
        evidence = "; ".join(x for x in (a.get("evidence"), a.get("problem")) if x)
        if not current[i]:
            if status[i].lower() == "rejected":
                merge.updates[row] = {"ai_note": add_note(note[i], f"{a['source']} says: {value}")}
                merge.skipped_rejected.append(a["id"])
                continue
            merge.updates[row] = {"answer": value, "source": a["source"], "confidence": a.get("confidence") or "",
                                  "status": "suggested", "ai_note": evidence}
            merge.filled.append(a["id"])
            merge.answered.add(a["id"])
        elif same_answer(current[i], value):
            merge.agreed.append(a["id"])
            if status[i] and a["source"].casefold() not in source[i].casefold():
                merge.updates[row] = {"source": f"{source[i]}; {a['source']}" if source[i] else a["source"]}
        else:
            merge.updates[row] = {"ai_note": add_note(note[i], f"{a['source']} says: {value}")}
            merge.conflicts.append({"id": a["id"], "yours": current[i], "found": value, "source": a["source"],
                                    "earlier_ai_answer": bool(status[i])})
    return merge


def _runs(rows: list[int]) -> list[tuple[int, int]]:
    """Contiguous [start, end) runs of sorted row numbers."""
    runs: list[list[int]] = []
    for r in sorted(set(rows)):
        if runs and runs[-1][1] == r:
            runs[-1][1] = r + 1
        else:
            runs.append([r, r + 1])
    return [(s, e) for s, e in runs]


def _cell(value) -> dict:
    return {"userEnteredValue": {"stringValue": value}} if value not in (None, "") else {}


def plan_answers(sheet: SheetRead, answers: list[dict], additions: list[dict], with_label: bool) -> dict:
    """
    answers    findings for questions already in the sheet
    additions  cell dicts (by column name) for the rows to add under 'Suggested additions'
    with_label whether that section's label row still has to be written
    """
    names = sheet.names
    width_before = max(sheet.column_count, len(names))
    header = names + [""] * (width_before - len(names))
    missing = [c for c in REVIEW_COLUMNS if c not in header]
    header += missing
    width = len(header)
    col = {name: header.index(name) for name in ("answer", *REVIEW_COLUMNS)}
    label_column = header.index("question") if "question" in header else 0
    tab = sheet.tab_sheet_id
    reqs: list[dict] = []

    if missing:
        start = width_before
        reqs.append({"appendDimension": {"sheetId": tab, "dimension": "COLUMNS", "length": len(missing)}})
        reqs.append({"updateCells": {
            "range": {"sheetId": tab, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": start, "endColumnIndex": width},
            "rows": [{"values": [_cell(n) for n in missing]}], "fields": "userEnteredValue"}})
        reqs.append({"repeatCell": {
            "range": {"sheetId": tab, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": start, "endColumnIndex": width},
            "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}}, "fields": "userEnteredFormat.textFormat.bold"}})
        for name, pixels in REVIEW_WIDTHS.items():
            if name in missing:
                reqs.append({"updateDimensionProperties": {
                    "range": {"sheetId": tab, "dimension": "COLUMNS", "startIndex": col[name], "endIndex": col[name] + 1},
                    "properties": {"pixelSize": pixels}, "fields": "pixelSize"}})

    merge = merge_answers(sheet, answers)
    for row in sorted(merge.updates):
        by_col = {col[name]: value for name, value in merge.updates[row].items()}
        for start, end in _runs(list(by_col)):
            reqs.append({"updateCells": {
                "range": {"sheetId": tab, "startRowIndex": row, "endRowIndex": row + 1,
                          "startColumnIndex": start, "endColumnIndex": end},
                "rows": [{"values": [_cell(by_col[c]) for c in range(start, end)]}],
                "fields": "userEnteredValue"}})

    data_end = len(sheet.ids) + 1  # rows in use: the header plus column A as read
    rows = [row_from(header, cells) for cells in additions]
    section, rows_after = section_requests(tab, data_end, rows, width, label_column, with_label and bool(rows),
                                           sheet.row_count)
    reqs += section
    first_added = data_end + (1 if with_label and rows else 0)
    added_rows = list(range(first_added, first_added + len(rows)))

    question_rows = [i + 1 for i, v in enumerate(sheet.ids) if v] + added_rows
    status_col = col["status"]
    for start, end in _runs(question_rows):
        reqs.append({"setDataValidation": {
            "range": {"sheetId": tab, "startRowIndex": start, "endRowIndex": end,
                      "startColumnIndex": status_col, "endColumnIndex": status_col + 1},
            "rule": {"condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": v} for v in STATUS_VALUES]},
                     "showCustomUi": True, "strict": False}}})

    if sheet.basic_filter:
        reqs.append(restore_filter(tab, sheet.basic_filter, width_before, width, sheet.row_count, rows_after))
    return {
        "requests": reqs,
        "merge": merge,
        "columns_added": missing,
        "added_rows": added_rows,
        "label_written": with_label and bool(rows),
        "width": width,
        "rows_after": rows_after,
    }
