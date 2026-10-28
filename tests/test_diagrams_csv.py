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


def test_drive_share_links_become_direct_image_links():
    from imcp.graph.diagrams import drive_image_url
    direct = "https://drive.google.com/uc?export=view&id=1AbCdEfGhIjKlMnOpQrStUvWxYz"
    assert drive_image_url("https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz/view?usp=sharing") == direct
    assert drive_image_url("https://drive.google.com/open?id=1AbCdEfGhIjKlMnOpQrStUvWxYz") == direct
    assert drive_image_url(direct) == direct and drive_image_url("https://img.example.com/a.png") is None
    assert drive_image_url("https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOpQrStUvWxYz") is None
    pages = parse_diagrams_csv(HEADER + "Token flow,https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz/view?usp=sharing,Tokens,,,,,\n")
    assert pages[0].url == direct
    with pytest.raises(RulesError, match="file link"):
        parse_diagrams_csv(HEADER + "A,https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOpQrStUvWxYz,desc,,,,,\n")
