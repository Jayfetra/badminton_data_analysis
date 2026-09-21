"""Query sanitising and name normalisation."""

from __future__ import annotations

import re
import unicodedata

from bwf_player.exceptions import InvalidInputError

_TRANSLITERATE = str.maketrans(
    {"ø": "o", "æ": "ae", "œ": "oe", "ß": "ss", "ł": "l", "đ": "d", "ð": "d", "þ": "th", "ı": "i"}
)
_NON_WORD = re.compile(r"[\W_]+")
_WHITESPACE = re.compile(r"\s+")


def sanitize_query(raw: object, max_length: int = 100) -> str:
    """Validate user input and return it cleaned of control characters and extra whitespace.

    Raises:
        InvalidInputError: not text, empty, too long, or nothing searchable remains.
    """
    if not isinstance(raw, str):
        raise InvalidInputError("Query must be text.")
    text = unicodedata.normalize("NFKC", raw)
    text = "".join(" " if unicodedata.category(ch).startswith("C") else ch for ch in text)
    text = _WHITESPACE.sub(" ", text).strip()
    if not text:
        raise InvalidInputError("Query is empty.")
    if len(text) > max_length:
        raise InvalidInputError(f"Query is longer than {max_length} characters.")
    if not normalize_name(text):
        raise InvalidInputError("Query contains no searchable letters or digits.")
    return text


def normalize_name(text: str) -> str:
    """Lower-case, strip accents, and reduce punctuation/whitespace to single spaces."""
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.translate(_TRANSLITERATE)
    return _NON_WORD.sub(" ", text).strip()


def derive_slug(name: str) -> str:
    """Build a URL slug the way the site does (e.g. 'Jonatan CHRISTIE' -> 'jonatan-christie')."""
    return "-".join(normalize_name(name).split())
