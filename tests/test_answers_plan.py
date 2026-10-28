from imcp.scope.additions import ADDITIONS_LABEL, label_needed, new_ids
from imcp.scope.answers_plan import SCOPE_LOG_COLUMNS, SheetRead, plan_answers, plan_scope_log, same_answer
from tests.test_sheet_plan import FakeBook, FakeTab

TAB = 2039431867
HEADER = ["id", "enum", "question", "options", "answer", "notes", "priority", "subsection", "channels", "pillars",
          "category", "platform", "found_by"]
WIDTH = len(HEADER)
ANSWER, PRIORITY, QUESTION = 4, 6, 2
# A scope sheet as /ops-create-scope leaves it: section headings have no ID
COLUMN_A = ["id", "", "ID-0083", "", "ID-0069", "ID-0019", "", "ID-0037", "ID-0050"]
P1_ONLY = {"range": {"sheetId": TAB, "startRowIndex": 0, "endRowIndex": 9, "startColumnIndex": 0, "endColumnIndex": WIDTH},
           "filterSpecs": [{"columnIndex": PRIORITY, "filterCriteria": {"hiddenValues": ["2", "3"]}}]}


def scope_tab() -> FakeTab:
    tab = FakeTab(COLUMN_A, width=WIDTH, tab=TAB)
    tab.rows[0] = list(HEADER)
    for row, label in ((1, "Introduction"), (3, "Discovery"), (6, "Features & Functionality")):
        tab.rows[row][QUESTION] = label
    for row, priority in ((2, 1), (4, 1), (5, 2), (7, 3), (8, 2)):
        tab.rows[row][PRIORITY] = priority
    tab.rows[4][ANSWER] = "Ethernet"  # the IM's own answer
    return tab


def read(tab: FakeTab, **kw) -> SheetRead:
    """What the skill reads: header, column A, the answer column and any review columns."""
    header = [h for h in tab.rows[0] if h is not None]
    names = ["answer", "source", "confidence", "status", "ai_note"]
    columns = {n: [str(r[header.index(n)] or "") for r in tab.rows[1:]] for n in names if n in header}
    return SheetRead(tab_sheet_id=TAB, column_count=len(tab.rows[0]), row_count=len(tab.rows), header=header,
                     ids=[r[0] or "" for r in tab.rows[1:]], columns=columns, **kw)


def answer(qid, value, source="Call summary", confidence="high", evidence="said on the call", problem=None):
    return {"id": qid, "answer": value, "source": source, "confidence": confidence, "evidence": evidence,
            "problem": problem}


BANK_ROW = {"id": "ID-0096", "enum": "single_choice", "question": "Manual download or automated ingestion?",
            "options": "Manual download | Automated ingestion", "priority": 1, "subsection": "Discovery",
            "pillars": "DIGITAL, UC", "category": "REPORTING_RECONCILIATION", "answer": "Automated ingestion",
            "found_by": "answered in material", "source": "Call summary", "confidence": "high", "status": "suggested",
            "ai_note": "daily SFTP report"}
NEW_ROW = {"id": "NEW-0001", "enum": "toggle", "question": "Can one job be paid by an insurer and the customer?",
           "subsection": "Discovery", "answer": "TRUE", "found_by": "new question", "source": "Call summary",
           "status": "suggested", "ai_note": "insurance jobs"}


def test_first_run_fills_empty_answers_keeps_the_ims_and_adds_review_columns_and_additions():
    tab = scope_tab()
    plan = plan_answers(read(tab, basic_filter=P1_ONLY),
                        [answer("ID-0037", "FALSE"), answer("ID-0050", "Manual capture", confidence="medium"),
                         answer("ID-0069", "Cellular"), answer("ID-9999", "not in the sheet")],
                        [BANK_ROW, NEW_ROW], with_label=True)
    tab.apply(plan["requests"])
    header = tab.rows[0]
    assert header == HEADER + ["source", "confidence", "status", "ai_note"] and plan["columns_added"] == header[13:]
    src, conf, status, note = 13, 14, 15, 16
    assert tab.rows[7][ANSWER] == "FALSE" and tab.rows[7][src:] == ["Call summary", "high", "suggested", "said on the call"]
    assert tab.rows[8][ANSWER] == "Manual capture" and tab.rows[8][conf] == "medium"
    # the IM's answer stays; the finding goes in the note and the row is marked as a conflict
    assert tab.rows[4][ANSWER] == "Ethernet" and tab.rows[4][src:status + 1] == [None, None, "conflict"]
    assert tab.rows[4][note] == "Call summary says: Cellular"
    merge = plan["merge"]
    assert merge.filled == ["ID-0037", "ID-0050"] and [c["id"] for c in merge.conflicts] == ["ID-0069"]
    assert [(e["id"], e["change"]) for e in merge.log] == [("ID-0037", "filled"), ("ID-0050", "filled"), ("ID-0069", "conflict")]
    assert merge.log[2]["answer"] == "Cellular" and merge.log[2]["note"] == "the sheet says: Ethernet"
    assert merge.answered == {"ID-0069", "ID-0037", "ID-0050"}
    # Suggested additions at the end: label row, then the rows, in the sheet's own columns
    assert tab.column(0)[9:] == [None, "ID-0096", "NEW-0001"] and tab.rows[9][QUESTION] == ADDITIONS_LABEL
    assert tab.rows[10][PRIORITY] == 1 and tab.rows[10][ANSWER] == "Automated ingestion"
    assert tab.rows[11][PRIORITY] is None and tab.rows[11][header.index("found_by")] == "new question"
    assert plan["added_rows"] == [10, 11] and {0, 9} <= tab.bold_rows
    # the status dropdown is on question rows only, never on headings
    assert tab.validations == [(2, 3, status), (4, 6, status), (7, 9, status), (10, 12, status)]
    assert tab.widths == {src: 170, note: 340}
    # the filter now covers the new rows and columns
    assert tab.filter["range"]["endRowIndex"] == 12 and tab.filter["range"]["endColumnIndex"] == 17
    assert tab.filter["filterSpecs"] == P1_ONLY["filterSpecs"]
    assert tab.visible_column(0) == ["id", "", "ID-0083", "", "ID-0069", "", None, "ID-0096", "NEW-0001"]


def test_a_second_run_respects_what_the_im_did():
    tab = scope_tab()
    tab.apply(plan_answers(read(tab), [answer("ID-0037", "FALSE"), answer("ID-0050", "Manual capture")],
                           [NEW_ROW], with_label=True)["requests"])
    status = tab.rows[0].index("status")
    tab.rows[8][ANSWER], tab.rows[8][status] = None, "rejected"  # the IM rejected the capture answer
    tab.rows[7][status] = "confirmed"
    sheet = read(tab)
    assert not label_needed(sheet.ids, set())
    plan = plan_answers(sheet, [answer("ID-0050", "Delayed automatic capture", source="Call 2"),
                                answer("ID-0037", "false", source="Call 2"),
                                answer("ID-0083", "Moving off their processor", source="Call 2")],
                        [{**NEW_ROW, "id": "NEW-0002", "question": "Do fleet customers pay by bank transfer?"}],
                        with_label=False)
    before = len(tab.rows)
    tab.apply(plan["requests"])
    merge = plan["merge"]
    assert plan["columns_added"] == [] and merge.skipped_rejected == ["ID-0050"] and merge.agreed == ["ID-0037"]
    assert tab.rows[8][ANSWER] is None and "Call 2 says: Delayed automatic capture" in tab.rows[8][-1]
    assert tab.rows[7][tab.rows[0].index("source")] == "Call summary; Call 2" and tab.rows[7][status] == "confirmed"
    assert tab.rows[2][ANSWER] == "Moving off their processor"
    assert len(tab.rows) == before + 1 and tab.column(0)[-2:] == ["NEW-0001", "NEW-0002"]
    assert tab.column(QUESTION).count(ADDITIONS_LABEL) == 1


def test_the_material_confirms_the_ims_own_answer_and_marks_a_changed_one():
    tab = scope_tab()  # ID-0069 answered 'Ethernet' by the IM, no review columns yet
    plan = plan_answers(read(tab), [answer("ID-0069", "ethernet", source="Call 1, 2026-10-24")], [], with_label=False)
    tab.apply(plan["requests"])
    source, status = (tab.rows[0].index(n) for n in ("source", "status"))
    assert tab.rows[4][ANSWER] == "Ethernet" and tab.rows[4][status] == "confirmed"
    assert tab.rows[4][source] == "Call 1, 2026-10-24"
    merge = plan["merge"]
    assert merge.agreed == merge.confirmed == ["ID-0069"] and merge.log[0]["change"] == "confirmed your answer"
    # a later call says something else: the answer stays, the row becomes a conflict, both are visible
    plan = plan_answers(read(tab), [answer("ID-0069", "Wi-Fi", source="Call 2, 2026-10-30")], [], with_label=False)
    tab.apply(plan["requests"])
    assert tab.rows[4][ANSWER] == "Ethernet" and tab.rows[4][status] == "conflict"
    assert tab.rows[4][tab.rows[0].index("ai_note")] == "Call 2, 2026-10-30 says: Wi-Fi"
    assert plan["merge"].confirmed == [] and plan["merge"].log[0]["change"] == "conflict"
    # the IM resolves it in the sheet; a third call agreeing adds its source and leaves their decision alone
    tab.rows[4][status] = "confirmed"
    plan = plan_answers(read(tab), [answer("ID-0069", "Ethernet", source="Call 3")], [], with_label=False)
    tab.apply(plan["requests"])
    assert tab.rows[4][status] == "confirmed" and tab.rows[4][source] == "Call 1, 2026-10-24; Call 3"
    assert plan["merge"].log[0]["change"] == "agreed with the suggested answer" and plan["merge"].confirmed == []
    # a rejected row with an answer typed later is never touched beyond the note
    tab.rows[4][status] = "rejected"
    plan = plan_answers(read(tab), [answer("ID-0069", "Cellular", source="Call 4")], [], with_label=False)
    tab.apply(plan["requests"])
    assert tab.rows[4][status] == "rejected" and "Call 4 says: Cellular" in tab.rows[4][tab.rows[0].index("ai_note")]


def test_scope_log_tab_is_added_once_and_appended_with_one_line_per_change():
    entries = [{"id": "ID-0037", "change": "filled", "answer": "FALSE", "source": "Call 1, 2026-10-24",
                "confidence": "high", "note": "said on the call"},
               {"id": "NEW-0001", "change": "new question", "answer": "TRUE", "source": "Call 1, 2026-10-24",
                "confidence": "", "note": "Can one job have two payers?"}]
    questions = {"ID-0037": "Tipping"}
    assert plan_scope_log(None, "Project Scope", entries, "2026-10-27 10:00 UTC", questions)["requests"] == []
    assert plan_scope_log([(TAB, "Project Scope")], "Project Scope", [], "2026-10-27 10:00 UTC", questions)["rows"] == 0
    book = FakeBook({TAB: scope_tab()}, {TAB: "Project Scope"})
    first = plan_scope_log([(TAB, "Project Scope")], "Project Scope", entries, "2026-10-27 10:00 UTC", questions)
    book.apply(first["requests"])
    assert first["tab_added"] and first["rows"] == 2 and first["sheet_id"] == 1001
    log = book.tabs[1001]
    assert book.titles[1001] == "Scope log" and log.frozen_rows == 1 and log.widths[0] == 150
    assert log.rows[0] == list(SCOPE_LOG_COLUMNS)
    assert log.rows[1] == ["2026-10-27 10:00 UTC", "Project Scope", "ID-0037", "Tipping", "filled", "FALSE",
                           "Call 1, 2026-10-24", "high", "said on the call"]
    assert log.rows[2][2:4] == ["NEW-0001", None] and log.rows[2][8] == "Can one job have two payers?"
    second = plan_scope_log([(TAB, "Project Scope"), (1001, "Scope log")], "In-person UK", entries[:1],
                            "2026-10-30 09:00 UTC", questions)
    book.apply(second["requests"])
    assert not second["tab_added"] and second["sheet_id"] == 1001 and len(book.tabs) == 2
    assert log.rows[3][:3] == ["2026-10-30 09:00 UTC", "In-person UK", "ID-0037"]


def test_nothing_to_add_means_no_new_rows():
    tab = scope_tab()
    plan = plan_answers(read(tab), [answer("ID-0019", "17:00")], [], with_label=True)
    tab.apply(plan["requests"])
    assert len(tab.rows) == len(COLUMN_A) and plan["label_written"] is False and tab.rows[5][ANSWER] == "17:00"


def test_trailing_blank_rows_are_used_before_adding_rows():
    tab = scope_tab()
    tab.rows += [[None] * WIDTH for _ in range(3)]  # the grid is longer than the data
    sheet = read(tab)
    sheet.ids = sheet.ids[:len(COLUMN_A) - 1]  # column A as read stops at the last value
    plan = plan_answers(sheet, [], [NEW_ROW], with_label=True)
    tab.apply(plan["requests"])
    assert len(tab.rows) == len(COLUMN_A) + 3 and tab.column(0)[9:11] == [None, "NEW-0001"]


def test_same_answer_ignores_case_spacing_and_choice_order():
    assert same_answer("Manual  capture", "manual capture") and same_answer("iOS | Web", "web|ios")
    assert not same_answer("iOS", "iOS | Web")


def test_new_ids_continue_after_the_highest():
    assert new_ids(["ID-0001", "NEW-0002", "", "NEW-0007"], 2) == ["NEW-0008", "NEW-0009"]
    assert new_ids([], 1) == ["NEW-0001"]


def test_the_additions_label_is_written_once():
    ids = ["", "ID-0083", "", "ID-0069"]
    assert label_needed(ids, set())
    assert not label_needed(ids + ["", "NEW-0001"], set())
    assert not label_needed(ids + ["", "ID-0096"], {"ID-0096"})
    assert label_needed(ids + ["ID-0096"], set())  # ID-0096 belongs to the scope here
