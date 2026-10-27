import pytest

from imcp.proposal.doc_plan import TICK, BOX, plan_document, track_label
from imcp.proposal.outline import parse_outline, utf16_len
from imcp.scope.runs import RunError
from tests.fake_doc import FakeDoc


def master() -> FakeDoc:
    """A small proposal master with the agreed tokens and one track block."""
    return (FakeDoc()
            .paragraph("{{Merchant Name}} Solution Proposal", "TITLE")
            .table([["1.0 Introduction"]])
            .paragraph("1.4 Project Background", "HEADING_2").paragraph("{{Project Background}}")
            .paragraph("1.5 Project Goals & Objectives", "HEADING_2").paragraph("{{Project Goals}}")
            .table([["2.0 Scope"]])
            .paragraph("2.1 {{Track}} Scope", "HEADING_2")
            .paragraph("2.1.1 Discovery", "HEADING_3").paragraph("{{Discovery}}")
            .paragraph("2.1.2 Features & Functionality", "HEADING_3").paragraph("")
            .table([["Feature & Functionality", "In Scope"], ["", ""]])
            .table([["3.0 Solution"]])
            .paragraph("3.1 {{Track}} Solution", "HEADING_2")
            .paragraph("3.1.1 Technical Considerations", "HEADING_3").paragraph("{{Technical Considerations}}")
            .paragraph("3.1.2 Integration Design", "HEADING_3").paragraph("{{Integration Design}}")
            .paragraph("3.1.3 Flow Diagrams", "HEADING_3").paragraph("{{Flow Diagrams}}")
            .paragraph("3.1.4 Documentation", "HEADING_3").paragraph("{{Documentation}}")
            .table([["4.0 Timeframe"]])
            .paragraph("Boilerplate about the timeframe."))


TRACK = {
    "name": "Project Scope",
    "discovery": [{"question": "Which regions are in scope?", "answer": "UK and NL"},
                  {"question": "Current PSP?", "answer": "A legacy PSP, moving to Adyen"}],
    "features": [{"feature": "3D Secure", "in_scope": True, "text": ""},
                 {"feature": "Tokenization", "in_scope": False, "text": ""},
                 {"feature": "Payment methods", "in_scope": None, "text": "Cards | iDEAL"}],
    "technical_considerations": ["Tokens must be migrated before go-live.", "3DS2 applies to EU cards."],
    "integration_design": ["Drop-in with the Sessions flow."],
    "diagram": {"title": "Tokenization flow", "url": "https://img.example.com/tokens.png"},
    "links": [{"title": "Tokenization", "url": "https://docs.adyen.com/online-payments/tokenization"},
              {"title": "3D Secure 2", "url": "https://docs.adyen.com/online-payments/3d-secure"}],
}
INTRO = {"background": ["Northwind sells outdoor gear online.", "They are moving off a legacy PSP."], "goals": ["Go live in Q1."]}


def planned(track=TRACK, intro=INTRO, doc=None):
    doc = doc or master()
    outline = parse_outline(doc.outline())
    plan = plan_document(outline, merchant="Northwind Outfitters", introduction=intro, track=track)
    doc.apply(plan["requests"])
    return doc, plan


def test_fake_doc_outline_matches_docs_geometry():
    doc = FakeDoc().paragraph("ab").table([["", ""]]).paragraph("c")
    items = doc.outline()
    # "ab\n" = 1..4, table starts at 4: row 5, cells 6-8 and 8-10, row ends 10, table ends 11
    assert (items[1].s, items[1].e) == (1, 4)
    table = items[2]
    assert (table.s, table.e) == (4, 11) and table.rows[0].s == 5 and table.rows[0].e == 10
    assert [(c.s, c.e) for c in table.rows[0].cells] == [(6, 8), (8, 10)]
    assert (items[3].s, items[3].e, items[3].text) == (11, 13, "c")


def test_the_whole_plan_fills_the_document():
    doc, plan = planned()
    text = doc.text()
    assert "{{" not in text and "}}" not in text
    paras = {p["text"]: p for p in doc.paragraphs()}
    assert "Northwind Outfitters Solution Proposal" in paras
    assert "2.1 Project Scope" in paras and "3.1 Project Solution" in paras  # the default track reads "Project"
    # 1.4 and 1.5
    assert "Northwind sells outdoor gear online." in paras and "They are moving off a legacy PSP." in paras and "Go live in Q1." in paras
    # Discovery: bold questions, plain answers, in order
    texts = [p["text"] for p in doc.paragraphs()]
    i = texts.index("Which regions are in scope?")
    assert texts[i:i + 4] == ["Which regions are in scope?", "UK and NL", "Current PSP?", "A legacy PSP, moving to Adyen"]
    assert paras["Which regions are in scope?"]["bold"] == ["Which regions are in scope?"] and paras["UK and NL"]["bold"] == []
    # Features table
    ff = doc.tables()[2]
    assert ff == [["Feature & Functionality", "In Scope"], ["3D Secure", TICK], ["Tokenization", BOX], ["Payment methods", "Cards | iDEAL"]]
    # Section 3
    assert "Tokens must be migrated before go-live." in paras and "Drop-in with the Sessions flow." in paras
    # Diagram: image paragraph, then its title
    j = texts.index("Tokenization flow")
    assert doc.paragraphs()[j - 1]["images"] == ["https://img.example.com/tokens.png"] and doc.paragraphs()[j - 1]["text"] == ""
    # Documentation: bulleted, linked titles
    assert paras["Tokenization"]["bullet"] and paras["Tokenization"]["links"] == {"https://docs.adyen.com/online-payments/tokenization": "Tokenization"}
    assert paras["3D Secure 2"]["links"] == {"https://docs.adyen.com/online-payments/3d-secure": "3D Secure 2"}
    assert texts[-1] == "Boilerplate about the timeframe."
    assert plan["summary"] == {"discovery_rows": 2, "feature_rows": 3, "considerations": 2, "design": 1, "diagram": True,
                               "links": 2, "background": True, "goals": True, "blocks_removed": 0, "discovery_as_table": False}
    # replaceAllText comes last, after every index-based edit
    kinds = [next(iter(r)) for r in plan["requests"]]
    assert kinds[-1] == "replaceAllText" and "replaceAllText" not in kinds[:kinds.index("replaceAllText")]


def test_empty_parts_remove_their_placeholder():
    track = {**TRACK, "discovery": [], "features": [], "technical_considerations": [], "integration_design": [],
             "diagram": None, "links": []}
    doc, plan = planned(track=track, intro={"background": [], "goals": []})
    texts = [p["text"] for p in doc.paragraphs()]
    assert "{{" not in doc.text()
    # headings stay, placeholders become empty paragraphs (their newline is kept); the Features table keeps its one empty row
    assert "2.1.1 Discovery" in texts and texts[texts.index("2.1.1 Discovery") + 1:texts.index("2.1.1 Discovery") + 3] == ["", "2.1.2 Features & Functionality"]
    assert doc.tables()[2] == [["Feature & Functionality", "In Scope"], ["", ""]]
    assert texts[texts.index("3.1.3 Flow Diagrams") + 1:texts.index("3.1.3 Flow Diagrams") + 3] == ["", "3.1.4 Documentation"]
    assert plan["summary"]["diagram"] is False and plan["summary"]["background"] is False


def test_one_feature_row_reuses_the_empty_row():
    track = {**TRACK, "features": [{"feature": "Tipping", "in_scope": True, "text": ""}]}
    doc, plan = planned(track=track)
    assert doc.tables()[2] == [["Feature & Functionality", "In Scope"], ["Tipping", TICK]]
    assert not any("insertTableRow" in r for r in plan["requests"])


def test_named_track_keeps_its_name_and_unicode_lengths_hold():
    track = {**TRACK, "name": "Ecommerce España",
             "discovery": [{"question": "¿Qué regiones?", "answer": "España y Portugal 🇪🇸"}]}
    doc, _ = planned(track=track)
    paras = {p["text"]: p for p in doc.paragraphs()}
    assert "2.1 Ecommerce España Scope" in paras
    assert paras["¿Qué regiones?"]["bold"] == ["¿Qué regiones?"] and paras["España y Portugal 🇪🇸"]["bold"] == []
    assert utf16_len("🇪🇸") == 4


def test_track_label():
    assert track_label("Project Scope") == "Project" and track_label(" In-person UK ") == "In-person UK"


def test_master_without_a_token_is_refused():
    doc = (FakeDoc().paragraph("{{Project Background}}").paragraph("{{Project Goals}}").paragraph("{{Discovery}}")
           .paragraph("2.1.2 Features & Functionality", "HEADING_3").table([["Feature", "In Scope"], ["", ""]])
           .paragraph("{{Technical Considerations}}").paragraph("{{Integration Design}}").paragraph("{{Flow Diagrams}}"))
    with pytest.raises(RunError, match="Documentation"):
        plan_document(parse_outline(doc.outline()), merchant="M", introduction=INTRO, track=TRACK)


def test_features_table_is_checked():
    bad = (FakeDoc().paragraph("{{Project Background}}").paragraph("{{Project Goals}}").paragraph("{{Discovery}}")
           .paragraph("2.1.2 Features & Functionality", "HEADING_3").table([["Feature", "In Scope"], ["x", ""]])
           .paragraph("{{Technical Considerations}}").paragraph("{{Integration Design}}").paragraph("{{Flow Diagrams}}")
           .paragraph("{{Documentation}}"))
    with pytest.raises(RunError, match="body row must be empty"):
        plan_document(parse_outline(bad.outline()), merchant="M", introduction=INTRO, track=TRACK)
    no_table = (FakeDoc().paragraph("{{Project Background}}").paragraph("{{Project Goals}}").paragraph("{{Discovery}}")
                .paragraph("2.1.2 Features & Functionality", "HEADING_3").paragraph("3.1 Solution", "HEADING_2")
                .paragraph("{{Technical Considerations}}").paragraph("{{Integration Design}}").paragraph("{{Flow Diagrams}}")
                .paragraph("{{Documentation}}"))
    with pytest.raises(RunError, match="no table under"):
        plan_document(parse_outline(no_table.outline()), merchant="M", introduction=INTRO, track=TRACK)


def test_outline_checks_catch_copy_slips():
    items = master().outline()
    items[3] = items[3].model_copy(update={"s": items[3].s + 1})
    with pytest.raises(RunError, match="starts at"):
        parse_outline(items)
    items = master().outline()
    tok = next(i for i, e in enumerate(items) if e.text == "{{Discovery}}")
    items[tok] = items[tok].model_copy(update={"text": "{{Discovery}} "})
    with pytest.raises(RunError, match="spans"):
        parse_outline(items)
    items = master().outline()
    table = next(i for i, e in enumerate(items) if e.rows and len(e.rows) == 2)
    rows = [r.model_copy(update={"s": r.s + (1 if n else 0)}) for n, r in enumerate(items[table].rows)]
    items[table] = items[table].model_copy(update={"rows": rows})
    with pytest.raises(RunError, match="row 2 starts at"):
        parse_outline(items)
    with pytest.raises(RunError, match="empty"):
        parse_outline([])


def test_outline_accepts_truncated_text_for_plain_paragraphs():
    items = master().outline()
    items[-1] = items[-1].model_copy(update={"text": "Boilerplate about"})
    outline = parse_outline(items)
    assert outline.paragraphs[-1].text == "Boilerplate about"


def master_with_track_block() -> FakeDoc:
    """The owner's master: a first block plus a second, per-track block (2.2 / 3.2) with its own tokens."""
    return (FakeDoc()
            .paragraph("{{Merchant Name}} Solution Proposal", "TITLE")
            .paragraph("1.4 Project Background", "HEADING_2").paragraph("{{Project Background}}")
            .paragraph("1.5 Project Goals & Objectives", "HEADING_2").paragraph("{{Project Goals}}")
            .table([["2.0 Scope"]])
            .paragraph("2.1 Project Scope", "HEADING_2")
            .paragraph("2.1.1 Discovery", "HEADING_3").paragraph("{{Discovery}}")
            .paragraph("2.1.2 Features & Functionality", "HEADING_3").paragraph("")
            .table([["Feature & Functionality", "In Scope"], ["", ""]])
            .paragraph("", "HEADING_2")
            .paragraph("2.2 {{Track}} - Scope", "HEADING_2")
            .paragraph("2.2.1 Discovery", "HEADING_3").paragraph("{{Discovery}}")
            .paragraph("2.2.2 Features & Functionality", "HEADING_3").paragraph("")
            .table([["Feature & Functionality", "In Scope"], ["", ""]])
            .paragraph("")
            .table([["3.0 Solution"]])
            .paragraph("3.1 Project Solution", "HEADING_2")
            .paragraph("3.1.1 Technical Considerations", "HEADING_3").paragraph("{{Technical Considerations}}")
            .paragraph("3.1.2 Integration Design", "HEADING_3").paragraph("{{Integration Design}}")
            .paragraph("3.1.3 Flow Diagrams", "HEADING_3").paragraph("{{Flow Diagrams}}")
            .paragraph("3.1.4 Documentation", "HEADING_3").paragraph("{{Documentation}}")
            .paragraph("3.2 {{Track}} - Proposed Solution", "HEADING_2").paragraph("{{Technical Considerations}}")
            .paragraph("3.2.2 Integration Design", "HEADING_3").paragraph("{{Integration Design}}")
            .paragraph("3.2.3 Flow Diagrams", "HEADING_3").paragraph("{{Flow Diagrams}}")
            .paragraph("3.2.4 Documentation", "HEADING_3").paragraph("{{Documentation}}")
            .paragraph("")
            .table([["4.0 Timeframe"]])
            .paragraph("Boilerplate about the timeframe."))


def test_a_second_track_block_is_removed_whole_with_one_track():
    doc, plan = planned(doc=master_with_track_block())
    text = doc.text()
    assert "{{" not in text and "}}" not in text
    texts = [p["text"] for p in doc.paragraphs()]
    assert "2.1 Project Scope" in texts and "3.1 Project Solution" in texts
    assert not any("2.2" in t or "3.2" in t for t in texts)
    assert "" not in [p["text"] for p in doc.paragraphs() if p["style"] == "HEADING_2"]  # the stray empty heading went too
    assert len(doc.tables()) == 4  # 2.0, the first Features table, 3.0, 4.0: the second Features table is gone
    assert doc.tables()[1][1] == ["3D Secure", TICK]
    assert plan["summary"]["blocks_removed"] == 2
    # the empty paragraph before each section table survives, so no table touches another
    assert texts[texts.index("3.1.4 Documentation") + 3:texts.index("3.1.4 Documentation") + 5] == ["", "Boilerplate about the timeframe."]


def master_with_tables() -> FakeDoc:
    """The master with Discovery as a Question | Answer table, like the Features table."""
    return (FakeDoc()
            .paragraph("{{Merchant Name}} Solution Proposal", "TITLE")
            .paragraph("1.4 Project Background", "HEADING_2").paragraph("{{Project Background}}")
            .paragraph("1.5 Project Goals & Objectives", "HEADING_2").paragraph("{{Project Goals}}")
            .table([["2.0 Scope"]])
            .paragraph("2.1 Project Scope", "HEADING_2")
            .paragraph("2.1.1 Discovery", "HEADING_3").paragraph("")
            .table([["Question", "Answer"], ["", ""]])
            .paragraph("2.1.2 Features & Functionality", "HEADING_3").paragraph("")
            .table([["Feature & Functionality", "In Scope"], ["", ""]])
            .paragraph("")
            .table([["3.0 Solution"]])
            .paragraph("3.1 Project Solution", "HEADING_2")
            .paragraph("3.1.1 Technical Considerations", "HEADING_3").paragraph("{{Technical Considerations}}")
            .paragraph("3.1.2 Integration Design", "HEADING_3").paragraph("{{Integration Design}}")
            .paragraph("3.1.3 Flow Diagrams", "HEADING_3").paragraph("{{Flow Diagrams}}")
            .paragraph("3.1.4 Documentation", "HEADING_3").paragraph("{{Documentation}}")
            .paragraph("")
            .table([["4.0 Timeframe"]])
            .paragraph("Boilerplate about the timeframe."))


def test_discovery_fills_a_table_when_the_master_has_one():
    doc, plan = planned(doc=master_with_tables())
    assert "{{" not in doc.text()
    assert doc.tables()[1] == [["Question", "Answer"], ["Which regions are in scope?", "UK and NL"],
                               ["Current PSP?", "A legacy PSP, moving to Adyen"]]
    assert doc.tables()[2] == [["Feature & Functionality", "In Scope"], ["3D Secure", TICK], ["Tokenization", BOX],
                               ["Payment methods", "Cards | iDEAL"]]
    assert plan["summary"]["discovery_as_table"] is True and plan["summary"]["discovery_rows"] == 2
    # no Discovery paragraphs were written outside the table
    assert "Which regions are in scope?" not in [p["text"] for p in doc.paragraphs()]


def test_discovery_table_with_no_answers_keeps_its_empty_row():
    doc, _ = planned(track={**TRACK, "discovery": []}, doc=master_with_tables())
    assert doc.tables()[1] == [["Question", "Answer"], ["", ""]]


def test_discovery_table_header_is_checked():
    bad = (FakeDoc().paragraph("{{Project Background}}").paragraph("{{Project Goals}}")
           .paragraph("2.1.1 Discovery", "HEADING_3").table([["Topic", "Notes"], ["", ""]])
           .paragraph("2.1.2 Features & Functionality", "HEADING_3").table([["Feature", "In Scope"], ["", ""]])
           .paragraph("{{Technical Considerations}}").paragraph("{{Integration Design}}").paragraph("{{Flow Diagrams}}")
           .paragraph("{{Documentation}}"))
    with pytest.raises(RunError, match="Discovery table's header row"):
        plan_document(parse_outline(bad.outline()), merchant="M", introduction=INTRO, track=TRACK)
