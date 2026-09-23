"""Defensive coercion helpers shared by the parsers of the site's loosely typed JSON."""

from __future__ import annotations

import re
from datetime import date

_CODE = re.compile(r"[0-9A-Za-z_-]{1,20}")


def to_int(value: object) -> int | None:
    """A non-negative integer from an int, integral float or ASCII digit string; else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        return int(value) if value.is_integer() and value >= 0 else None
    if isinstance(value, str) and value.strip().isascii() and value.strip().isdigit():
        return int(value.strip())
    return None


def to_date(value: object) -> date | None:
    """The date in an ISO date or datetime string (only its first ten characters); else None."""
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def clean_text(value: object) -> str | None:
    """Text with whitespace collapsed, or None if it is not text or is blank."""
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text or None


def to_code(value: object) -> str | None:
    """A short identifier (letters, digits, ``_``, ``-``; at most 20) from text or a non-negative int; else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        value = str(value) if value >= 0 else None
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text if _CODE.fullmatch(text) else None
