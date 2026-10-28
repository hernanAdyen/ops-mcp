"""Small text helpers shared by the scope commands: trimming and scrubbing what we write or keep.

The scrubbing itself lives in imcp.pii, shared with the graph loaders; the names here stay for the callers.
"""

import re

from imcp.pii import scrub as scrub_contacts  # noqa: F401  (emails, phones, IBANs, cards, keys)
from imcp.pii import scrub_name  # noqa: F401


def one_line(value, limit: int) -> str:
    """A value as one line of text, at most `limit` characters."""
    return " ".join(str(value or "").split())[:limit]


def similar(a: str, b: str) -> float:
    """How alike two questions read (0 to 1), ignoring case, punctuation and spacing."""
    from difflib import SequenceMatcher

    norm = lambda s: " ".join(re.sub(r"[^\w\s]", " ", s.casefold()).split())  # noqa: E731
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


STOPWORDS = {"a", "an", "and", "any", "are", "be", "by", "can", "do", "does", "for", "how", "if", "in", "is", "it",
             "of", "on", "or", "our", "so", "that", "the", "there", "this", "to", "we", "what", "which", "will",
             "with", "you", "your"}


def _content_words(text: str) -> set[str]:
    return {w for w in re.sub(r"[^\w\s]", " ", text.casefold()).split() if w not in STOPWORDS}


def same_question(a: str, b: str, threshold: float = 0.85) -> bool:
    """Whether two questions ask the same thing in nearly the same words. The key words must match
    too, so 'Is 3DS in scope?' and 'Is AVS in scope?' stay different questions."""
    words_a, words_b = _content_words(a), _content_words(b)
    overlap = len(words_a & words_b) / max(1, len(words_a | words_b))
    return overlap >= 0.75 and similar(a, b) >= threshold
