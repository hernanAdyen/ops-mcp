import pytest

from imcp.graph.docs_index import RulesError, canonical_url, parse_index, parse_rules, rule_for, select_pages

RULES = """prefix,include,max_depth,channels,pillars,categories,platforms,note
/,no,,,,,,default
/online-payments,yes,,ECOM,DIGITAL;UC,PAYIN,PSP,
/online-payments/classic-integrations,no,,,,,,legacy
/online-payments/3d-secure/redirect-3ds2,yes,0,ECOM,DIGITAL,PAYIN,PSP,overview only
/development-resources,yes,1,ECOM;IPP,,,,one level
/plugins,yes,1,,,,,
"""

INDEX = """# Adyen Docs

## Online payments
- [Online payments](https://docs.adyen.com/online-payments.md): Accept payments online.
- [Tokenization](https://docs.adyen.com/online-payments/tokenization.md): Store payment details for recurring payments.
- [Classic API](https://docs.adyen.com/online-payments/classic-integrations/classic-api-integration.md): Old API.
- [Redirect 3DS2](https://docs.adyen.com/online-payments/3d-secure/redirect-3ds2.md): Redirect flow.
- [Redirect 3DS2 web](https://docs.adyen.com/online-payments/3d-secure/redirect-3ds2/web.md): Web variant.
- [No description](https://docs.adyen.com/online-payments/refund.md)
- [Tokenization](https://docs.adyen.com/online-payments/tokenization.md): Listed twice.

## Development resources
- [Webhooks](https://docs.adyen.com/development-resources/webhooks.md): Get notified.
- [Handle events](https://docs.adyen.com/development-resources/webhooks/handle-webhook-events.md): Deeper.
- [Other site](https://help.adyen.com/something.md): Not our host.
- [Plugins](https://docs.adyen.com/plugins.md): Plugins index.
- [Shopify](https://docs.adyen.com/plugins/shopify.md): Shopify plugin.
- [Shopify methods](https://docs.adyen.com/plugins/shopify/supported-payment-methods.md): Too deep.
Some prose line that is not an entry.
"""


def test_canonical_url_drops_md_and_trailing_slash():
    assert canonical_url("https://Docs.Adyen.com/online-payments/tokenization.md") == "https://docs.adyen.com/online-payments/tokenization"
    assert canonical_url("https://docs.adyen.com/") == "https://docs.adyen.com/"
    assert canonical_url("https://docs.adyen.com/plugins/") == "https://docs.adyen.com/plugins"


def test_parse_rules_reads_tags_depth_and_include():
    rules = parse_rules(RULES)
    assert [r.prefix for r in rules][:3] == ["/", "/online-payments", "/online-payments/classic-integrations"]
    op = rules[1]
    assert op.include and op.max_depth is None and op.tags == {
        "channels": ["ECOM"], "pillars": ["DIGITAL", "UC"], "categories": ["PAYIN"], "platforms": ["PSP"]}
    assert rules[3].max_depth == 0 and rules[3].note == "overview only"
    assert rules[5].tags == {"channels": [], "pillars": [], "categories": [], "platforms": []}


@pytest.mark.parametrize("bad, message", [
    ("prefix,include,max_depth,channels,pillars,categories,platforms,note\nonline,yes,,,,,,", "must start with"),
    ("prefix,include,max_depth,channels,pillars,categories,platforms,note\n/a,maybe,,,,,,", "yes or no"),
    ("prefix,include,max_depth,channels,pillars,categories,platforms,note\n/a,yes,deep,,,,,", "whole number"),
    ("prefix,include,max_depth,channels,pillars,categories,platforms,note\n/a,yes,,WEB,,,,", "unknown channels"),
    ("prefix,include,max_depth,channels,pillars,categories,platforms,note\n/a,yes,,,,,,\n/a,no,,,,,,", "twice"),
    ("prefix,include\n/a,yes", "missing the column"),
    ("prefix,include,max_depth,channels,pillars,categories,platforms,note\n", "no rules"),
])
def test_parse_rules_rejects_bad_rows(bad, message):
    with pytest.raises(RulesError, match=message):
        parse_rules(bad)


def test_parse_index_reads_entries_sections_and_skips_repeats():
    entries = parse_index(INDEX)
    urls = [e.url for e in entries]
    assert urls[0] == "https://docs.adyen.com/online-payments"
    assert "https://docs.adyen.com/online-payments/tokenization" in urls and urls.count("https://docs.adyen.com/online-payments/tokenization") == 1
    tok = next(e for e in entries if e.path == "/online-payments/tokenization")
    assert (tok.title, tok.description, tok.section) == ("Tokenization", "Store payment details for recurring payments.", "Online payments")
    refund = next(e for e in entries if e.path == "/online-payments/refund")
    assert refund.description == ""
    assert next(e for e in entries if e.path == "/development-resources/webhooks").section == "Development resources"


def test_longest_prefix_wins():
    rules = parse_rules(RULES)
    assert rule_for("/online-payments/tokenization", rules).prefix == "/online-payments"
    assert rule_for("/online-payments/classic-integrations/x", rules).prefix == "/online-payments/classic-integrations"
    assert rule_for("/reporting", rules).prefix == "/"
    assert rule_for("/online-paymentsx", rules).prefix == "/"  # a prefix matches whole path parts only


def test_select_pages_applies_rules_depth_host_and_descriptions():
    sel = select_pages(parse_index(INDEX), parse_rules(RULES))
    paths = sorted(p.path for p in sel.pages)
    assert paths == [
        "/development-resources/webhooks",  # depth 1 below /development-resources
        "/online-payments",
        "/online-payments/3d-secure/redirect-3ds2",  # depth 0 rule keeps the overview
        "/online-payments/tokenization",
        "/plugins",
        "/plugins/shopify",
    ]
    assert sel.no_description == ["https://docs.adyen.com/online-payments/refund"]
    # classic API (excluded), redirect web (too deep), handle events (too deep), shopify methods (too deep)
    assert sel.excluded == 4
    tok = next(p for p in sel.pages if p.path == "/online-payments/tokenization")
    assert tok.tags["pillars"] == ["DIGITAL", "UC"] and tok.rule == "/online-payments"
    assert tok.url == "https://docs.adyen.com/online-payments/tokenization"
