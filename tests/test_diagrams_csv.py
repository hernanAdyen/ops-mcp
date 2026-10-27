import pytest

from imcp.graph.diagrams import parse_diagrams_csv
from imcp.graph.docs_index import RulesError

HEADER = "title,url,description,channels,pillars,categories,platforms,note\n"


def test_parse_rows_with_tags():
    pages = parse_diagrams_csv(HEADER + "Token flow,https://img.example.com/a.png,Tokens for recurring,ECOM;MOTO,DIGITAL,PAYIN,PSP,first\n"
                               "Tip flow,https://img.example.com/b.JPG,Tipping on the terminal,,,,,\n")
    assert pages[0].url == "https://img.example.com/a.png" and pages[0].title == "Token flow"
    assert pages[0].tags == {"channels": ["ECOM", "MOTO"], "pillars": ["DIGITAL"], "categories": ["PAYIN"], "platforms": ["PSP"]}
    assert pages[1].tags == {"channels": [], "pillars": [], "categories": [], "platforms": []} and pages[1].rule == "diagrams"


@pytest.mark.parametrize("line, message", [
    ("Token flow,https://img.example.com/a.png,,,,,,", "all needed"),
    ("Token flow,http://img.example.com/a.png,desc,,,,,", "https"),
    ("Token flow,https://img.example.com/a.svg,desc,,,,,", "PNG, JPEG or GIF"),
    ("Token flow,https://img.example.com/a.png,desc,WEB,,,,", "unknown channels"),
    ("A,https://img.example.com/a.png,desc,,,,,\nB,https://img.example.com/a.png,desc,,,,,", "twice"),
])
def test_bad_rows_are_refused(line, message):
    with pytest.raises(RulesError, match=message):
        parse_diagrams_csv(HEADER + line + "\n")


def test_empty_or_wrong_file():
    with pytest.raises(RulesError, match="no rows"):
        parse_diagrams_csv(HEADER)
    with pytest.raises(RulesError, match="missing the column"):
        parse_diagrams_csv("title,url\nA,https://x/a.png\n")
