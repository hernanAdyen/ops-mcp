"""Turn a copy of the master bank into the IM's scope sheet, in one exact batch.

Claude copies the master, reads the copy's ID column, and sends it here with the confirmed
selection. We return the Sheets batchUpdate requests, so no row arithmetic is left to the model:
  1. delete the rows that weren't chosen, bottom-up, in contiguous blocks
  2. add a `found_by` column with each kept question's label
  3. order the rows by section (Introduction, Discovery, Features & Functionality, ...), then
     priority, then ID, using a temporary sort column that is removed again
  4. put a bold header row above each section and make the section's rows a collapsible group,
     with the +/- toggle on the header row
Steps 1-2 were tested against the Sheets connector on 2026-10-24.

If the tab has a basic filter (e.g. the master shows P1 only), it is cleared first and put back at the
end over the new rows: while a filter hides rows, Sheets sorts only the visible ones (seen 2026-10-25).

A scope with several project tracks gets one tab per track (`plan_tracks`): the master's Project Scope
tab is renamed to the first track, duplicated once per further track before any row is touched, and
then every tab is edited from its own selection, as above.
"""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from imcp.db import enums as E
from imcp.scope.additions import row_from, section_requests

FOUND_BY = "found_by"
SECTION_ORDER = list(E.Subsection)
SECTION_LABELS = {
    E.Subsection.introduction: "Introduction",
    E.Subsection.discovery: "Discovery",
    E.Subsection.features_functionality: "Features & Functionality",
    E.Subsection.technical_considerations: "Technical Considerations",
    E.Subsection.integration_design: "Integration Design",
    E.Subsection.documentation: "Documentation",
}
HEADER_FILL = {"red": 0.91, "green": 0.94, "blue": 0.99}


class SheetPlanError(ValueError):
    pass


@dataclass(frozen=True)
class RowInfo:
    section: E.Subsection
    priority: int


def sort_key(qid: str, info: RowInfo) -> int:
    """Section, then priority, then the ID's number, as one number Sheets can sort on."""
    number = int("".join(ch for ch in qid if ch.isdigit()) or 0)
    return SECTION_ORDER.index(info.section) * 10**8 + info.priority * 10**7 + number


def out_of_order(sheet_ids: list[str], info: dict[str, RowInfo], limit: int = 10) -> list[str]:
    """Question IDs, in sheet order, that aren't where the section, priority, ID order puts them."""
    expected = sorted(sheet_ids, key=lambda q: sort_key(q, info[q]))
    return [actual for actual, want in zip(sheet_ids, expected) if actual != want][:limit]


def _cell(value) -> dict:
    if isinstance(value, (int, float)):
        return {"userEnteredValue": {"numberValue": value}}
    return {"userEnteredValue": {"stringValue": value}}


def _write(tab: int, row: int, col: int, values: list[list]) -> dict:
    """updateCells for a block of values starting at (row, col)."""
    return {"updateCells": {
        "range": {"sheetId": tab, "startRowIndex": row, "endRowIndex": row + len(values),
                  "startColumnIndex": col, "endColumnIndex": col + len(values[0])},
        "rows": [{"values": [_cell(v) for v in r]} for r in values],
        "fields": "userEnteredValue",
    }}


def layout_requests(tab_sheet_id: int, column_count: int, rows_in_order: list[str],
                    info: dict[str, RowInfo], found_by: dict[str, str] | None,
                    label_column: int = 0) -> tuple[list[dict], list[tuple]]:
    """
    Requests that order the question rows by section and group them. The rows (row 1 onward) must
    hold exactly `rows_in_order`. With `found_by`, the found_by column is added as well.
    Section names go in `label_column` (the question column, so they show even when id is hidden).
    Returns the requests and the final layout: (section label, header row, first row, row count).
    """
    n = len(rows_in_order)
    if n == 0:
        return [], []
    tab = tab_sheet_id
    keys = [sort_key(q, info[q]) for q in rows_in_order]
    needs_sort = keys != sorted(keys)  # a master kept in section, priority, ID order needs no sort
    reqs: list[dict] = []
    width = column_count + (1 if found_by is not None else 0)
    added = (1 if found_by is not None else 0) + (1 if needs_sort else 0)
    if added:
        reqs.append({"appendDimension": {"sheetId": tab, "dimension": "COLUMNS", "length": added}})
    if found_by is not None:
        # The most common label in one request, then only the rows that differ
        common = Counter(found_by[q] for q in rows_in_order).most_common(1)[0][0]
        reqs.append(_write(tab, 0, column_count, [[FOUND_BY]]))
        reqs.append({"repeatCell": {
            "range": {"sheetId": tab, "startRowIndex": 1, "endRowIndex": n + 1,
                      "startColumnIndex": column_count, "endColumnIndex": column_count + 1},
            "cell": _cell(common), "fields": "userEnteredValue"}})
        for i, q in enumerate(rows_in_order, start=1):
            if found_by[q] != common:
                reqs.append(_write(tab, i, column_count, [[found_by[q]]]))
    if needs_sort:
        sort_col = width  # a temporary column after the others, removed after sorting
        reqs.append(_write(tab, 0, sort_col, [["sort"]] + [[k] for k in keys]))
        reqs.append({"sortRange": {
            "range": {"sheetId": tab, "startRowIndex": 1, "endRowIndex": n + 1,
                      "startColumnIndex": 0, "endColumnIndex": sort_col + 1},
            "sortSpecs": [{"dimensionIndex": sort_col, "sortOrder": "ASCENDING"}],
        }})
        reqs.append({"deleteDimension": {"range": {"sheetId": tab, "dimension": "COLUMNS",
                                                   "startIndex": sort_col, "endIndex": sort_col + 1}}})

    ordered = sorted(rows_in_order, key=lambda q: sort_key(q, info[q]))
    counts = Counter(info[q].section for q in ordered)
    sections = [s for s in SECTION_ORDER if counts[s]]

    # Header rows, inserted bottom-up so the earlier positions don't move.
    starts, row = {}, 1
    for s in sections:
        starts[s], row = row, row + counts[s]
    for s in reversed(sections):
        reqs.append({"insertDimension": {"range": {"sheetId": tab_sheet_id, "dimension": "ROWS",
                                                   "startIndex": starts[s], "endIndex": starts[s] + 1},
                                         "inheritFromBefore": False}})

    layout, row = [], 1
    for s in sections:
        header, first = row, row + 1
        layout.append((SECTION_LABELS[s], header, first, counts[s]))
        reqs.append({"updateCells": {
            "range": {"sheetId": tab_sheet_id, "startRowIndex": header, "endRowIndex": header + 1,
                      "startColumnIndex": label_column, "endColumnIndex": label_column + 1},
            "rows": [{"values": [_cell(SECTION_LABELS[s])]}],
            "fields": "userEnteredValue",
        }})
        reqs.append({"repeatCell": {
            "range": {"sheetId": tab_sheet_id, "startRowIndex": header, "endRowIndex": header + 1,
                      "startColumnIndex": 0, "endColumnIndex": width},
            "cell": {"userEnteredFormat": {"textFormat": {"bold": True}, "wrapStrategy": "OVERFLOW_CELL",
                                           "backgroundColorStyle": {"rgbColor": HEADER_FILL}}},
            "fields": "userEnteredFormat.textFormat.bold,userEnteredFormat.wrapStrategy,"
                      "userEnteredFormat.backgroundColorStyle",
        }})
        reqs.append({"addDimensionGroup": {"range": {"sheetId": tab_sheet_id, "dimension": "ROWS",
                                                     "startIndex": first, "endIndex": first + counts[s]}}})
        row = first + counts[s]
    reqs.append({"updateSheetProperties": {
        "properties": {"sheetId": tab_sheet_id, "gridProperties": {"rowGroupControlAfter": False}},
        "fields": "gridProperties.rowGroupControlAfter",
    }})
    return reqs, layout


def filter_specs(basic_filter: dict) -> list[dict]:
    """The filter's column rules, from filterSpecs or from the older criteria map ({"6": {...}})."""
    if basic_filter.get("filterSpecs"):
        return [dict(spec) for spec in basic_filter["filterSpecs"]]
    return [{"columnIndex": int(col), "filterCriteria": crit}
            for col, crit in sorted((basic_filter.get("criteria") or {}).items(), key=lambda kv: int(kv[0]))]


def restore_filter(tab_sheet_id: int, basic_filter: dict, column_count: int, width: int,
                   rows_before: int, rows_after: int) -> dict:
    """setBasicFilter with the same rules, over the rows the tab has after the edit."""
    old = basic_filter.get("range", {})
    start_row, start_col = old.get("startRowIndex", 0), old.get("startColumnIndex", 0)
    end_row = old.get("endRowIndex", rows_before)
    end_row = max(end_row - rows_before + rows_after, rows_after)  # it covered the data; still does
    end_col = old.get("endColumnIndex", column_count)
    if end_col >= column_count:
        end_col = width  # it reached the last column, so it covers found_by too
    return {"setBasicFilter": {"filter": {
        "range": {"sheetId": tab_sheet_id, "startRowIndex": start_row, "endRowIndex": end_row,
                  "startColumnIndex": start_col, "endColumnIndex": end_col},
        "filterSpecs": filter_specs(basic_filter),
    }}}  # the filter's own sort order isn't kept: it would undo the section order


def plan_sheet_edit(tab_sheet_id: int, column_count: int, id_column: list[str], keep: dict[str, str],
                    info: dict[str, RowInfo], header_row: list[str] | None = None,
                    basic_filter: dict | None = None, additions: list[dict] | None = None) -> dict:
    """
    tab_sheet_id  numeric sheetId of the copy's Project Scope tab
    column_count  the tab's current column count (gridProperties.columnCount)
    id_column     column A as read, starting with the header row; '' for empty cells
    keep          question ID -> found_by label, for the confirmed questions
    info          question ID -> section and priority, for every ID in keep
    header_row    row 1 of the tab; section names go in its 'question' column (column A if absent)
    basic_filter  the tab's basicFilter as read, if it has one; it's cleared and put back
    additions     cell dicts (by column name) for a 'Suggested additions' section at the end, e.g. the
                  questions drafted for topics no bank question covers. Needs header_row.
    """
    if not id_column or id_column[0].strip().lower() not in ("id", "question_id"):
        raise SheetPlanError("id_column must be column A of the Project Scope tab, starting with its 'id' header")
    ids = [value.strip() for value in id_column[1:]]

    delete_rows = [index + 1 for index, qid in enumerate(ids) if qid not in keep]  # +1: header is row 0
    blocks: list[list[int]] = []
    for row in delete_rows:
        if blocks and blocks[-1][1] == row:
            blocks[-1][1] = row + 1
        else:
            blocks.append([row, row + 1])
    requests: list[dict] = [{"clearBasicFilter": {"sheetId": tab_sheet_id}}] if basic_filter else []
    requests += [
        {"deleteDimension": {"range": {"sheetId": tab_sheet_id, "dimension": "ROWS", "startIndex": start, "endIndex": end}}}
        for start, end in reversed(blocks)  # bottom-up, so earlier deletions don't move later ones
    ]

    kept = [qid for qid in ids if qid in keep]
    repeated = sorted(qid for qid, n in Counter(kept).items() if n > 1)
    if repeated:
        raise SheetPlanError(f"these IDs appear more than once in the sheet: {', '.join(repeated)}")
    headers = [h.strip().lower() for h in (header_row or [])]
    label_column = headers.index("question") if "question" in headers else 0
    layout_reqs, layout = layout_requests(tab_sheet_id, column_count, kept, info, found_by=keep,
                                          label_column=label_column)
    requests += layout_reqs
    data_end = 1 + len(kept) + len(layout)
    added = 0
    if additions and headers:
        names = (headers + [""] * column_count)[:column_count] + [FOUND_BY]  # found_by is the last column now
        rows = [row_from(names, cells) for cells in additions]
        section, _ = section_requests(tab_sheet_id, data_end, rows, column_count + 1, label_column,
                                      with_label=True, row_count=data_end)
        requests += section
        added = len(rows) + 1
    if basic_filter:
        requests.append(restore_filter(tab_sheet_id, basic_filter, column_count, width=column_count + 1,
                                       rows_before=len(id_column), rows_after=data_end + added))
    return {
        "requests": requests,
        "filter": "kept" if basic_filter else None,
        "suggested_additions": {"label_row": data_end + 1, "rows": added - 1} if added else None,
        "rows_kept": len(kept),
        "rows_deleted": len(delete_rows),
        "sections": [{"section": label, "header_row": header + 1, "questions": count}
                     for label, header, _, count in layout],  # rows as shown in Sheets (1-based)
        "missing_from_sheet": sorted(set(keep) - set(ids)),
    }


# --------------------------------------------------------------------------- tracks


@dataclass(frozen=True)
class TrackEdit:
    """One track's tab: its name (the tab title), the IDs to keep with their found_by labels, and the
    cell dicts for a 'Suggested additions' section, if this tab gets one."""

    name: str
    keep: dict[str, str]
    additions: list[dict] | None = None


CALL_PROMPT_TAB = "Call prompt"
CALL_PROMPT_WIDTH = 900  # pixels: wide enough to read the prompt without scrolling sideways


def plan_call_prompt_tab(sheet_id: int, text: str, index: int | None = None, title: str = CALL_PROMPT_TAB) -> list[dict]:
    """A new tab holding the call-notes prompt in A1, so the IM copies it from the sheet instead of chat."""
    properties: dict = {"sheetId": sheet_id, "title": title, "gridProperties": {"rowCount": 3, "columnCount": 1}}
    if index is not None:
        properties["index"] = index
    return [
        {"addSheet": {"properties": properties}},
        {"updateCells": {"range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 1},
                         "rows": [{"values": [{"userEnteredValue": {"stringValue": text},
                                               "userEnteredFormat": {"wrapStrategy": "WRAP", "verticalAlignment": "TOP"}}]}],
                         "fields": "userEnteredValue,userEnteredFormat.wrapStrategy,userEnteredFormat.verticalAlignment"}},
        {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
                                       "properties": {"pixelSize": CALL_PROMPT_WIDTH}, "fields": "pixelSize"}},
    ]


def new_sheet_ids(existing: Iterable[int], n: int, start: int = 1001) -> list[int]:
    """Numeric sheetIds for new tabs that don't clash with the copy's own tabs."""
    taken, out, candidate = set(existing), [], start
    while len(out) < n:
        if candidate not in taken:
            out.append(candidate)
        candidate += 1
    return out


def plan_tracks(tab_sheet_id: int, sheet_ids: list[int], column_count: int, id_column: list[str],
                tracks: list[TrackEdit], info: dict[str, RowInfo], header_row: list[str] | None = None,
                basic_filter: dict | None = None) -> dict:
    """
    One batch that turns the copy's Project Scope tab into one tab per track.
    tab_sheet_id  the copy's Project Scope tab: it becomes the first track's tab
    sheet_ids     every tab of the copy, in tab order (so new tabs get free IDs and sit next to the first)
    The other arguments are as for plan_sheet_edit; id_column is the Project Scope tab's column A, which
    every duplicate starts from, because the duplicates are made before any row is deleted.
    Returns the requests and, per tab, what plan_sheet_edit reports.
    """
    if not tracks:
        raise SheetPlanError("a scope needs at least one track")
    names = [t.name.casefold() for t in tracks]
    if len(set(names)) != len(names):
        raise SheetPlanError("track names must be different from each other")
    if len(tracks) > 1 and tab_sheet_id not in sheet_ids:
        raise SheetPlanError("sheet_ids must list the copy's tabs (sheets.properties.sheetId), including the Project Scope tab")
    position = sheet_ids.index(tab_sheet_id) if tab_sheet_id in sheet_ids else 0
    tab_ids = [tab_sheet_id] + new_sheet_ids(sheet_ids, len(tracks) - 1)

    requests: list[dict] = [{"updateSheetProperties": {
        "properties": {"sheetId": tab_sheet_id, "title": tracks[0].name}, "fields": "title"}}]
    for i, (track, sid) in enumerate(zip(tracks[1:], tab_ids[1:]), start=1):
        requests.append({"duplicateSheet": {"sourceSheetId": tab_sheet_id, "insertSheetIndex": position + i,
                                            "newSheetId": sid, "newSheetName": track.name}})
    tabs = []
    for track, sid in zip(tracks, tab_ids):
        plan = plan_sheet_edit(sid, column_count, id_column, track.keep, info, header_row,
                               basic_filter=basic_filter, additions=track.additions)
        requests += plan["requests"]
        tabs.append({"name": track.name, "tab_sheet_id": sid, **{k: v for k, v in plan.items() if k != "requests"}})
    return {"requests": requests, "tabs": tabs}
