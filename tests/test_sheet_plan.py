import random

import pytest

from imcp.db import enums as E
from imcp.scope.sheet_plan import FOUND_BY, RowInfo, SheetPlanError, layout_requests, out_of_order, plan_sheet_edit, sort_key

TAB = 2039431867
COLS = 12
INTRO, DISC, FF = E.Subsection.introduction, E.Subsection.discovery, E.Subsection.features_functionality


class FakeTab:
    """Plays a batch of Sheets requests on a grid, like Sheets does, so tests can check the result."""

    def __init__(self, column_a: list[str], width: int = COLS, tab: int = TAB, basic_filter: dict | None = None):
        self.tab = tab
        self.rows = [[value] + [None] * (width - 1) for value in column_a]
        self.groups: list[tuple[int, int]] = []
        self.bold_rows: set[int] = set()
        self.control_after = True
        self.filter = basic_filter
        self.validations: list[tuple[int, int, int]] = []  # (start row, end row, column)
        self.widths: dict[int, int] = {}

    def hidden(self, row: list) -> bool:
        """Hidden by the filter: a cell's value is one of its column's hiddenValues ('' for empty)."""
        if not self.filter:
            return False
        for spec in self.filter["filterSpecs"]:
            value = row[spec["columnIndex"]]
            if ("" if value is None else str(value)) in spec["filterCriteria"].get("hiddenValues", []):
                return True
        return False

    def visible_column(self, index: int) -> list:
        return [row[index] for i, row in enumerate(self.rows) if i == 0 or not self.hidden(row)]

    def apply(self, requests: list[dict]) -> "FakeTab":
        for r in requests:
            (kind, body), = r.items()
            rng = body.get("range", body.get("filter", {}).get("range", {}))
            if kind == "clearBasicFilter":
                assert body["sheetId"] == self.tab
                self.filter = None
            elif kind == "setBasicFilter":
                self.filter = body["filter"]
            elif kind == "deleteDimension" and rng["dimension"] == "ROWS":
                del self.rows[rng["startIndex"]:rng["endIndex"]]
            elif kind == "deleteDimension":
                for row in self.rows:
                    del row[rng["startIndex"]:rng["endIndex"]]
            elif kind == "appendDimension" and body["dimension"] == "ROWS":
                width = len(self.rows[0])
                self.rows += [[None] * width for _ in range(body["length"])]
            elif kind == "appendDimension":
                for row in self.rows:
                    row.extend([None] * body["length"])
            elif kind == "insertDimension":
                width = len(self.rows[0])
                for _ in range(rng["endIndex"] - rng["startIndex"]):
                    self.rows.insert(rng["startIndex"], [None] * width)
            elif kind == "updateCells":
                assert rng["endRowIndex"] - rng["startRowIndex"] == len(body["rows"])
                for i, row in enumerate(body["rows"]):
                    assert rng["endColumnIndex"] - rng["startColumnIndex"] == len(row["values"])
                    for j, cell in enumerate(row["values"]):
                        value = cell.get("userEnteredValue")  # an empty cell clears it
                        self.rows[rng["startRowIndex"] + i][rng["startColumnIndex"] + j] = (
                            None if value is None else value.get("stringValue", value.get("numberValue")))
            elif kind == "setDataValidation":
                self.validations.append((rng["startRowIndex"], rng["endRowIndex"], rng["startColumnIndex"]))
            elif kind == "updateDimensionProperties":
                self.widths[rng["startIndex"]] = body["properties"]["pixelSize"]
            elif kind == "sortRange":
                col = body["sortSpecs"][0]["dimensionIndex"]
                s, e = rng["startRowIndex"], rng["endRowIndex"]
                # Like Sheets: with a filter on, only the visible rows are sorted, among their own places.
                places = [i for i in range(s, e) if not self.hidden(self.rows[i])]
                for i, row in zip(places, sorted((self.rows[i] for i in places), key=lambda row: row[col])):
                    self.rows[i] = row
            elif kind == "repeatCell" and "userEnteredValue" in body["cell"]:
                value = body["cell"]["userEnteredValue"]
                for r in range(rng["startRowIndex"], rng["endRowIndex"]):
                    for c in range(rng["startColumnIndex"], rng["endColumnIndex"]):
                        self.rows[r][c] = value.get("stringValue", value.get("numberValue"))
            elif kind == "repeatCell":
                assert body["cell"]["userEnteredFormat"]["textFormat"]["bold"] is True
                self.bold_rows.add(rng["startRowIndex"])
            elif kind == "addDimensionGroup":
                self.groups.append((rng["startIndex"], rng["endIndex"]))
            elif kind == "updateSheetProperties":
                self.control_after = body["properties"]["gridProperties"]["rowGroupControlAfter"]
            else:
                raise AssertionError(f"unexpected request {kind}")
            if "sheetId" in rng:
                assert rng["sheetId"] == self.tab
        return self

    def column(self, index: int) -> list:
        return [row[index] for row in self.rows]


def ids(n):
    return [f"ID-{i:04d}" for i in range(1, n + 1)]


# ID-0001.. : features first, like the real bank, so ordering really has to move rows
INFO = {
    "ID-0001": RowInfo(FF, 1), "ID-0002": RowInfo(FF, 2), "ID-0003": RowInfo(DISC, 2),
    "ID-0004": RowInfo(DISC, 1), "ID-0005": RowInfo(INTRO, 1), "ID-0006": RowInfo(FF, 1),
    "ID-0007": RowInfo(DISC, 3), "ID-0008": RowInfo(INTRO, 1),
}


def test_orders_by_section_priority_and_id_with_headers_and_groups():
    column = ["id"] + ids(10)
    keep = {q: "tags" for q in INFO}
    keep["ID-0003"] = "topic: token migration"
    plan = plan_sheet_edit(TAB, COLS, column, keep, INFO)
    tab = FakeTab(column).apply(plan["requests"])
    assert tab.column(0) == ["id",
                             "Introduction", "ID-0005", "ID-0008",
                             "Discovery", "ID-0004", "ID-0003", "ID-0007",
                             "Features & Functionality", "ID-0001", "ID-0006", "ID-0002"]
    found_by = tab.column(COLS)
    assert found_by[0] == FOUND_BY and found_by[6] == "topic: token migration" and found_by[1] is None
    assert len(tab.rows[0]) == COLS + 1  # the temporary sort column is gone
    assert tab.groups == [(2, 4), (5, 8), (9, 12)] and tab.bold_rows == {1, 4, 8} and tab.control_after is False
    assert plan["sections"] == [{"section": "Introduction", "header_row": 2, "questions": 2},
                                {"section": "Discovery", "header_row": 5, "questions": 3},
                                {"section": "Features & Functionality", "header_row": 9, "questions": 3}]
    assert plan["rows_kept"] == 8 and plan["rows_deleted"] == 2


def test_rows_without_an_id_are_removed():
    column = ["id", "ID-0005", "", "ID-0008"]
    plan = plan_sheet_edit(TAB, COLS, column, {"ID-0005": "tags", "ID-0008": "tags"}, INFO)
    assert FakeTab(column).apply(plan["requests"]).column(0) == ["id", "Introduction", "ID-0005", "ID-0008"]


def test_reports_chosen_questions_missing_from_the_sheet():
    plan = plan_sheet_edit(TAB, COLS, ["id", "ID-0005"], {"ID-0005": "tags", "ID-0099": "tags"},
                           {**INFO, "ID-0099": RowInfo(DISC, 1)})
    assert plan["missing_from_sheet"] == ["ID-0099"]


def test_column_a_must_start_with_the_header():
    with pytest.raises(SheetPlanError):
        plan_sheet_edit(TAB, COLS, ids(3), {"ID-0001": "tags"}, INFO)


def test_repeated_ids_in_the_sheet_are_refused():
    with pytest.raises(SheetPlanError):
        plan_sheet_edit(TAB, COLS, ["id", "ID-0005", "ID-0005"], {"ID-0005": "tags"}, INFO)


def test_layout_on_a_sheet_that_already_has_found_by():
    """Reordering an existing scope sheet: found_by is there already, so only the order and groups change."""
    rows = ["ID-0001", "ID-0005", "ID-0004"]
    tab = FakeTab(["id"] + rows, width=COLS + 1)
    for i, label in enumerate([FOUND_BY, "tags", "tags", "topic: x"]):
        tab.rows[i][COLS] = label
    reqs, layout = layout_requests(TAB, COLS + 1, rows, INFO, found_by=None)
    tab.apply(reqs)
    assert tab.column(0) == ["id", "Introduction", "ID-0005", "Discovery", "ID-0004", "Features & Functionality", "ID-0001"]
    assert tab.column(COLS) == [FOUND_BY, None, "tags", None, "topic: x", None, "tags"]
    assert len(tab.rows[0]) == COLS + 1 and [g for g in tab.groups] == [(2, 3), (4, 5), (6, 7)]


@pytest.mark.parametrize("seed", range(25))
def test_random_selections_end_up_grouped_and_aligned(seed):
    rnd = random.Random(seed)
    all_ids = ids(144)
    info = {q: RowInfo(rnd.choice([INTRO, DISC, FF]), rnd.randint(1, 3)) for q in all_ids}
    chosen = rnd.sample(all_ids, rnd.randint(1, 144))
    keep = {q: f"label {q}" for q in chosen}
    column = ["id"] + all_ids
    plan = plan_sheet_edit(TAB, COLS, column, keep, info)
    tab = FakeTab(column).apply(plan["requests"])
    order = {INTRO: 0, DISC: 1, FF: 2}
    expected_ids = sorted(chosen, key=lambda q: (order[info[q].section], info[q].priority, q))
    question_rows = [(i, row) for i, row in enumerate(tab.rows) if i > 0 and row[0] in keep]
    assert [row[0] for _, row in question_rows] == expected_ids
    assert all(row[COLS] == keep[row[0]] for _, row in question_rows)  # found_by moved with its row
    grouped = {r for start, end in tab.groups for r in range(start, end)}
    assert grouped == {i for i, _ in question_rows}  # every question row is in its section's group
    assert len(tab.rows) == 1 + len(chosen) + len(plan["sections"])


def test_section_names_go_in_the_question_column():
    """With id and enum hidden in the master, the names must sit where the IM can see them."""
    header = ["id", "enum", "question", "options", "notes", "answer", "priority", "subsection",
              "channels", "pillars", "category", "platform"]
    column = ["id", "ID-0005", "ID-0004"]
    plan = plan_sheet_edit(TAB, COLS, column, {"ID-0005": "tags", "ID-0004": "tags"}, INFO, header_row=header)
    tab = FakeTab(column).apply(plan["requests"])
    assert tab.column(2) == [None, "Introduction", None, "Discovery", None]
    assert tab.column(0) == ["id", None, "ID-0005", None, "ID-0004"]


def test_without_a_header_row_names_go_in_column_a():
    plan = plan_sheet_edit(TAB, COLS, ["id", "ID-0005"], {"ID-0005": "tags"}, INFO)
    assert FakeTab(["id", "ID-0005"]).apply(plan["requests"]).column(0) == ["id", "Introduction", "ID-0005"]


# --- a filter on the tab (e.g. the master shows P1 only) --------------------------------------

PRIORITY_COL = 6
P1_ONLY = {"range": {"sheetId": TAB, "startRowIndex": 0, "endRowIndex": 11, "startColumnIndex": 0, "endColumnIndex": COLS},
           "filterSpecs": [{"columnIndex": PRIORITY_COL, "filterCriteria": {"hiddenValues": ["2", "3"]}}]}


def filtered_tab(column, info=INFO, basic_filter=P1_ONLY):
    tab = FakeTab(column, basic_filter=basic_filter)
    for row in tab.rows[1:]:
        if row[0] in info:
            row[PRIORITY_COL] = str(info[row[0]].priority)
    return tab


def test_without_clearing_the_filter_the_sort_goes_wrong():
    """What happened on 2026-10-25: Sheets only sorted the P1 rows, so P2/P3 rows stayed out of place."""
    column = ["id"] + ids(8)
    plan = plan_sheet_edit(TAB, COLS, column, {q: "tags" for q in INFO}, INFO)  # filter not passed
    tab = filtered_tab(column).apply(plan["requests"])
    assert tab.column(0) != ["id", "Introduction", "ID-0005", "ID-0008", "Discovery", "ID-0004", "ID-0003",
                             "ID-0007", "Features & Functionality", "ID-0001", "ID-0006", "ID-0002"]


def test_a_filter_is_cleared_for_the_edit_and_put_back_over_the_new_rows():
    column = ["id"] + ids(10)
    plan = plan_sheet_edit(TAB, COLS, column, {q: "tags" for q in INFO}, INFO, basic_filter=P1_ONLY)
    assert plan["requests"][0] == {"clearBasicFilter": {"sheetId": TAB}} and plan["filter"] == "kept"
    tab = filtered_tab(column).apply(plan["requests"])
    assert tab.column(0) == ["id",
                             "Introduction", "ID-0005", "ID-0008",
                             "Discovery", "ID-0004", "ID-0003", "ID-0007",
                             "Features & Functionality", "ID-0001", "ID-0006", "ID-0002"]
    assert tab.groups == [(2, 4), (5, 8), (9, 12)]
    assert tab.filter["filterSpecs"] == P1_ONLY["filterSpecs"]
    assert tab.filter["range"] == {"sheetId": TAB, "startRowIndex": 0, "endRowIndex": 12,
                                   "startColumnIndex": 0, "endColumnIndex": COLS + 1}  # found_by included
    # what the IM sees: the section headings (blank priority) and the P1 questions
    assert tab.visible_column(0) == ["id", "Introduction", "ID-0005", "ID-0008", "Discovery", "ID-0004",
                                     "Features & Functionality", "ID-0001", "ID-0006"]


def test_a_filter_read_in_the_older_criteria_form_is_kept_too():
    old_form = {"range": P1_ONLY["range"], "criteria": {"6": {"hiddenValues": ["2", "3"]}}}
    plan = plan_sheet_edit(TAB, COLS, ["id"] + ids(8), {q: "tags" for q in INFO}, INFO, basic_filter=old_form)
    assert plan["requests"][-1]["setBasicFilter"]["filter"]["filterSpecs"] == P1_ONLY["filterSpecs"]


def test_a_filter_over_extra_blank_rows_still_covers_them():
    wide = {**P1_ONLY, "range": {**P1_ONLY["range"], "endRowIndex": 1000}}
    plan = plan_sheet_edit(TAB, COLS, ["id"] + ids(10), {q: "tags" for q in INFO}, INFO, basic_filter=wide)
    # 11 rows read, 2 deleted, 3 headings added: 1000 - 11 + 12
    assert plan["requests"][-1]["setBasicFilter"]["filter"]["range"]["endRowIndex"] == 1001


def test_the_filters_own_sort_is_dropped():
    sorted_filter = {**P1_ONLY, "sortSpecs": [{"dimensionIndex": 2, "sortOrder": "ASCENDING"}]}
    plan = plan_sheet_edit(TAB, COLS, ["id"] + ids(8), {q: "tags" for q in INFO}, INFO, basic_filter=sorted_filter)
    assert "sortSpecs" not in plan["requests"][-1]["setBasicFilter"]["filter"]


@pytest.mark.parametrize("seed", range(15))
def test_random_selections_on_a_filtered_tab(seed):
    rnd = random.Random(seed)
    all_ids = ids(144)
    info = {q: RowInfo(rnd.choice([INTRO, DISC, FF]), rnd.randint(1, 3)) for q in all_ids}
    chosen = rnd.sample(all_ids, rnd.randint(1, 144))
    column = ["id"] + all_ids
    flt = {**P1_ONLY, "range": {**P1_ONLY["range"], "endRowIndex": 145}}
    plan = plan_sheet_edit(TAB, COLS, column, {q: "tags" for q in chosen}, info, basic_filter=flt)
    tab = filtered_tab(column, info, flt).apply(plan["requests"])
    order = {INTRO: 0, DISC: 1, FF: 2}
    expected = sorted(chosen, key=lambda q: (order[info[q].section], info[q].priority, q))
    assert [v for v in tab.column(0) if v in info] == expected
    assert tab.filter["range"]["endRowIndex"] == len(tab.rows)


def test_out_of_order_names_the_misplaced_rows():
    assert out_of_order(["ID-0005", "ID-0004", "ID-0001"], INFO) == []
    assert out_of_order(["ID-0005", "ID-0001", "ID-0004"], INFO) == ["ID-0001", "ID-0004"]



def test_rows_already_in_order_need_no_sort_and_found_by_is_one_request():
    """A master sorted by section, priority and ID: the batch is only deletions, headings and groups."""
    info = {"ID-0001": RowInfo(INTRO, 1), "ID-0002": RowInfo(DISC, 1), "ID-0003": RowInfo(DISC, 2),
            "ID-0004": RowInfo(FF, 1), "ID-0005": RowInfo(FF, 3)}
    column = ["id"] + list(info) + ["ID-0006"]
    keep = {q: "tags" for q in info}
    keep["ID-0003"] = "topic: tokens"
    plan = plan_sheet_edit(TAB, COLS, column, keep, info)
    kinds = [next(iter(r)) for r in plan["requests"]]
    assert "sortRange" not in kinds and kinds.count("appendDimension") == 1
    found_by_writes = [r for r in plan["requests"] if "updateCells" in r
                       and r["updateCells"]["range"]["startColumnIndex"] == COLS]
    assert len(found_by_writes) == 2  # the header and the one row that differs
    tab = FakeTab(column).apply(plan["requests"])
    assert tab.column(0) == ["id", "Introduction", "ID-0001", "Discovery", "ID-0002", "ID-0003",
                             "Features & Functionality", "ID-0004", "ID-0005"]
    assert tab.column(COLS) == [FOUND_BY, None, "tags", None, "tags", "topic: tokens", None, "tags", "tags"]
    assert len(tab.rows[0]) == COLS + 1


def test_the_batch_is_much_smaller_when_the_master_is_in_order():
    import json
    rnd = random.Random(1)
    all_ids = ids(144)
    order = [INTRO, DISC, FF]
    info = {q: RowInfo(order[min(2, i * 3 // 144)], 1 + (i % 48) // 16) for i, q in enumerate(all_ids)}
    sorted_ids = sorted(all_ids, key=lambda q: sort_key(q, info[q]))
    chosen = set(rnd.sample(all_ids, 78))
    keep = {q: "tags" for q in chosen}
    shuffled = rnd.sample(all_ids, len(all_ids))
    unsorted = json.dumps(plan_sheet_edit(TAB, COLS, ["id"] + shuffled, keep, info)["requests"])
    in_order = json.dumps(plan_sheet_edit(TAB, COLS, ["id"] + sorted_ids, keep, info)["requests"])
    assert len(in_order) < len(unsorted) * 0.7  # random picks; real scopes keep rows in runs and save more
