"""Small text helpers shared by the scope commands: trimming and scrubbing what we write or keep."""

import re

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Phone numbers in the usual written forms: +1 614 555 0100, (614) 555-0100, 614.555.0100, +44 20 7946 0958
PHONE = re.compile(r"(?<![\w-])(?:\+\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)\s?|\d{2,4}[\s.-])\d{3,4}[\s.-]\d{3,4}(?![\w-])")


def one_line(value, limit: int) -> str:
    """A value as one line of text, at most `limit` characters."""
    return " ".join(str(value or "").split())[:limit]


def scrub_name(text: str, name: str | None) -> str:
    """Replaces the merchant's name with 'the merchant'. Names shorter than 3 characters are left alone."""
    if name and len(name.strip()) >= 3:
        text = re.sub(re.escape(name.strip()), "the merchant", text, flags=re.IGNORECASE)
    return text


def scrub_contacts(text: str) -> str:
    """Removes email addresses and phone numbers."""
    return PHONE.sub("[phone]", EMAIL.sub("[email]", text))


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
