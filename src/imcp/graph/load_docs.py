"""One load of the Adyen doc pages: fetch the index, apply the rules, load the asset nodes.

The index is fetched from DOCS_INDEX_URL by the app server, used for this load and dropped.
"""

import ssl

import httpx

from imcp.config import AppSettings
from imcp.db import enums as E
from imcp.graph.assets import AssetLoadReport, load_assets
from imcp.graph.docs_index import RulesError, parse_index, parse_rules, select_pages
from imcp.scope.runs import RunError

INDEX_TIMEOUT = 60
MAX_INDEX_BYTES = 20_000_000


def fetch_text(url: str, timeout: float = INDEX_TIMEOUT) -> str:
    """The text at a public URL. Errors say what happened, without the body."""
    try:
        with httpx.Client(verify=ssl.create_default_context(), timeout=timeout, follow_redirects=True) as http:
            res = http.get(url)
    except httpx.HTTPError as exc:
        raise RunError(502, f"Could not fetch the docs index ({type(exc).__name__}).") from exc
    if res.status_code != 200:
        raise RunError(502, f"The docs index returned HTTP {res.status_code}.")
    if len(res.content) > MAX_INDEX_BYTES:
        raise RunError(502, "The docs index is larger than expected; not loading it.")
    return res.text


def load_doc_pages(session, settings: AppSettings, embedder, *, rules_csv: str, source_ref: str | None,
                   apply: bool, fetch=None) -> AssetLoadReport:
    """fetch: a stand-in for fetch_text in tests; the default is looked up at call time."""
    fetch = fetch or fetch_text
    try:
        rules = parse_rules(rules_csv)
    except RulesError as exc:
        raise RunError(422, f"The rules file can't be used: {exc}") from exc
    if not settings.DOCS_INDEX_URL:
        raise RunError(422, "DOCS_INDEX_URL isn't set on the app server.")
    if apply and embedder is None:
        raise RunError(422, "EMBEDDING_MODEL (and MODEL_BASE_URL or EMBEDDING_BASE_URL) must be set to load.")
    index_url = str(settings.DOCS_INDEX_URL)
    selection = select_pages(parse_index(fetch(index_url)), rules, host=httpx.URL(index_url).host)
    if not selection.pages:
        raise RunError(422, "No page in the index matched the rules. Check the rules file and the index URL.")
    report = load_assets(session, selection.pages, kind=E.AssetKind.doc_page, embedder=embedder,
                         source_ref=source_ref, apply=apply, no_description=selection.no_description)
    report.counts["excluded_by_rules"] = selection.excluded
    report.counts["index_entries"] = selection.excluded + selection.duplicates + len(selection.pages) + len(selection.no_description)
    return report
