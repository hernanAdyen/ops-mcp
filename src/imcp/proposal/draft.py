"""Checking the draft the IM's model wrote from the research brief.

The draft is structured, never free-form: known keys only, plain paragraphs with limits, and every
link either an asset node we know or a page under the documentation host. Anything else is refused
with a message that says what to fix. Nothing in the draft is stored.
"""

from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from imcp.graph.docs_index import canonical_url
from imcp.scope.runs import RunError

MAX_PARAGRAPHS = 8
MAX_PARAGRAPH_CHARS = 1200
MAX_INTRO_CHARS = 2500
MAX_LINKS = 20


class TrackDraft(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    technical_considerations: list[str] = Field(default_factory=list, max_length=MAX_PARAGRAPHS)
    integration_design: list[str] = Field(default_factory=list, max_length=MAX_PARAGRAPHS)
    links: list[str] = Field(default_factory=list, max_length=MAX_LINKS, description="Documentation links used, in order")


class IntroductionDraft(BaseModel):
    background: list[str] | str | None = None
    goals: list[str] | str | None = None


class Draft(BaseModel):
    introduction: IntroductionDraft = Field(default_factory=IntroductionDraft)
    tracks: list[TrackDraft] = Field(min_length=1, max_length=6)


def _paragraphs(value, *, where: str, limit: int = MAX_PARAGRAPH_CHARS) -> list[str]:
    items = [value] if isinstance(value, str) else list(value or [])
    out = []
    for text in items:
        text = " ".join(str(text).split())
        if not text:
            continue
        if "{{" in text or "}}" in text:
            raise RunError(422, f"{where}: the text contains a template token. Write plain text.")
        if len(text) > limit:
            raise RunError(422, f"{where}: a paragraph is {len(text)} characters; the limit is {limit}. Split or shorten it.")
        out.append(text)
    return out


def check_draft(draft: Draft, track_names: list[str], allowed: dict[str, str], docs_host: str | None) -> dict:
    """
    allowed: canonical URL -> title, for the asset nodes (doc pages and diagrams) we know.
    Returns {"introduction": {"background": [...], "goals": [...]}, "tracks": {name: {...}}}.
    """
    wanted = {" ".join(n.casefold().split()): n for n in track_names}
    seen: dict[str, dict] = {}
    for t in draft.tracks:
        key = " ".join(t.name.casefold().split())
        if key not in wanted:
            raise RunError(422, f"The draft has a track named {t.name!r} that isn't in this run. Tracks: {', '.join(track_names)}.")
        if wanted[key] in seen:
            raise RunError(422, f"The draft has the track {t.name!r} twice.")
        links = []
        bad = []
        for raw in t.links:
            url = canonical_url(raw) if raw.strip().startswith(("http://", "https://")) else raw.strip()
            if url in allowed:
                links.append({"url": url, "title": allowed[url]})
            elif docs_host and urlsplit(url).netloc == docs_host and url.startswith("https://"):
                links.append({"url": url, "title": url.removeprefix("https://")})
            else:
                bad.append(raw)
        if bad:
            raise RunError(422, f"Track {t.name!r}: these links aren't documentation pages we know or pages under "
                                f"{docs_host or 'the documentation host'}: {', '.join(bad[:5])}. Use links from the brief.")
        seen[wanted[key]] = {
            "technical_considerations": _paragraphs(t.technical_considerations, where=f"Track {t.name!r}, technical considerations"),
            "integration_design": _paragraphs(t.integration_design, where=f"Track {t.name!r}, integration design"),
            "links": list({l["url"]: l for l in links}.values()),
        }
    missing = [n for n in track_names if n not in seen]
    if missing:
        raise RunError(422, f"The draft has no section for the track(s): {', '.join(missing)}.")
    return {
        "introduction": {
            "background": _paragraphs(draft.introduction.background, where="1.4 Project Background", limit=MAX_INTRO_CHARS),
            "goals": _paragraphs(draft.introduction.goals, where="1.5 Project Goals", limit=MAX_INTRO_CHARS),
        },
        "tracks": seen,
    }
