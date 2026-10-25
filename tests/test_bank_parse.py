import csv
import io

from imcp.bank.parse import parse_bank_csv
from imcp.db import enums as E

HEADER = ["id", "enum", "options", "question", "notes", "answer", "priority", "subsection",
          "channels", "pillars", "category", "platform"]


def make_csv(*rows, header=HEADER) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    for row in rows:
        writer.writerow(row)
    return buf.getvalue()


def row(qid="ID-0001", enum="toggle", options="", question="Is 3DS in scope?", notes="", answer="",
        priority="2", subsection="Features & Functionality", channels="ECOM", pillars="DIGITAL, PFS",
        category="PAYIN", platform=""):
    return [qid, enum, options, question, notes, answer, priority, subsection, channels, pillars, category, platform]


def test_valid_row():
    result = parse_bank_csv(make_csv(row()))
    assert result.fatal is None and result.invalid == []
    q = result.rows[0]
    assert (q.question_id, q.type, q.priority, q.subsection) == (
        "ID-0001", E.QuestionType.toggle, 2, E.Subsection.features_functionality)
    assert q.channels == [E.Channel.ECOM] and q.pillars == [E.Pillar.DIGITAL, E.Pillar.PFS]
    assert q.categories == [E.Category.PAYIN] and q.platforms == []  # blank = applies to everyone
    assert q.row == 2 and q.notes is None


def test_columns_found_by_header_and_extra_columns_ignored():
    header = ["question", "id", "subsection", "priority", "enum", "found_by"]
    result = parse_bank_csv(make_csv(["Project Background", "ID-0083", "Introduction", "1", "free_text", "tags"],
                                     header=header))
    assert result.invalid == [] and result.rows[0].text == "Project Background"
    assert result.ignored_columns == ["found_by"]


def test_missing_required_column_is_fatal():
    header = [h for h in HEADER if h != "enum"]
    result = parse_bank_csv(make_csv(header=header))
    assert result.fatal and "enum" in result.fatal and result.rows == []


def test_duplicate_column_is_fatal():
    assert parse_bank_csv(make_csv(header=HEADER + ["id"])).fatal


def test_empty_file_is_fatal():
    assert parse_bank_csv("").fatal


def test_blank_rows_are_skipped():
    result = parse_bank_csv(make_csv(row(), [""] * 12, row(qid="ID-0002")))
    assert [q.question_id for q in result.rows] == ["ID-0001", "ID-0002"]
    assert result.data_rows == 2


def test_values_are_normalised():
    result = parse_bank_csv(make_csv(row(enum=" Toggle ", channels="ipp,ECOM , ecom", pillars="UC,DIGITAL",
                                         subsection="features_functionality", question="  Is 3DS in scope?\r\n")))
    q = result.rows[0]
    assert q.type == E.QuestionType.toggle and q.text == "Is 3DS in scope?"
    assert q.channels == [E.Channel.ECOM, E.Channel.IPP]  # deduplicated, fixed order
    assert q.pillars == [E.Pillar.DIGITAL, E.Pillar.UC]


def test_multiline_text_and_bom():
    text = "﻿" + make_csv(row(question="Line one\nLine two", notes="A note\r\nover two lines"))
    q = parse_bank_csv(text).rows[0]
    assert q.text == "Line one\nLine two" and q.notes == "A note\nover two lines"


def test_choice_options():
    result = parse_bank_csv(make_csv(row(enum="multi_choice", options=" iOS | Android |Web | ")))
    assert result.rows[0].options == ["iOS", "Android", "Web"]


def test_option_rules():
    result = parse_bank_csv(make_csv(
        row(qid="ID-0001", enum="single_choice", options=""),            # choice without options
        row(qid="ID-0002", enum="single_choice", options="Only one"),    # one option isn't a choice
        row(qid="ID-0003", enum="toggle", options="Yes | No"),           # options on a toggle
        row(qid="ID-0004", enum="multi_choice", options="iOS | ios"),    # duplicate option
    ))
    assert result.rows == []
    problems = {p.question_id: " ".join(p.problems) for p in result.invalid}
    assert "needs at least two options" in problems["ID-0001"]
    assert "needs at least two options" in problems["ID-0002"]
    assert "only choice questions have options" in problems["ID-0003"]
    assert "appears twice" in problems["ID-0004"]


def test_every_problem_in_a_row_is_reported():
    result = parse_bank_csv(make_csv(row(qid="ID-12", enum="string", question="", priority="4",
                                         subsection="Scope", channels="POS", category="PAYINS")))
    problems = result.invalid[0].problems
    assert result.invalid[0].row == 2 and result.invalid[0].question_id == "ID-12"
    assert len(problems) == 7, problems
    text = " ".join(problems)
    for expected in ("ID-0001", "enum 'string'", "missing question", "priority '4'", "subsection 'Scope'",
                     "unknown channel 'POS'", "unknown category 'PAYINS'"):
        assert expected in text


def test_missing_values_are_reported():
    problems = parse_bank_csv(make_csv(row(qid="", enum="", priority="", subsection=""))).invalid[0].problems
    assert {"missing id", "missing enum (the answer type)", "missing priority", "missing subsection"} <= set(problems)


def test_duplicate_ids_invalidate_every_copy():
    result = parse_bank_csv(make_csv(row(), row(question="Another"), row(qid="ID-0002")))
    assert [q.question_id for q in result.rows] == ["ID-0002"]
    assert [(p.row, p.problems[-1]) for p in result.invalid] == [
        (2, "id ID-0001 is also used on row 3"), (3, "id ID-0001 is also used on row 2")]


def test_content_hash_ignores_tag_order_but_not_text():
    a = parse_bank_csv(make_csv(row(pillars="DIGITAL, PFS"))).rows[0]
    b = parse_bank_csv(make_csv(row(pillars="PFS,DIGITAL"))).rows[0]
    c = parse_bank_csv(make_csv(row(question="Is 3DS2 in scope?"))).rows[0]
    assert a.content_hash() == b.content_hash() != c.content_hash()


def test_option_order_is_a_change():
    a = parse_bank_csv(make_csv(row(enum="single_choice", options="A | B"))).rows[0]
    b = parse_bank_csv(make_csv(row(enum="single_choice", options="B | A"))).rows[0]
    assert a.content_hash() != b.content_hash()
