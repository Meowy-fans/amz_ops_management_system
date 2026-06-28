"""Shared attribute transform helpers for V1/V2 rule resolvers."""

from __future__ import annotations

import re
from difflib import get_close_matches
from typing import Any, Iterable


def parse_integer_value(value: Any) -> int | None:
    """Parse integers from numeric strings and supplier tokens such as ``3 Seat``."""
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        pass
    match = re.search(r"\d+", str(value))
    if not match:
        return None
    try:
        return int(match.group())
    except ValueError:
        return None


def join_text_value(value: Any) -> str | None:
    """Join list text into a single description string."""
    if value in (None, "", []):
        return None
    if isinstance(value, list):
        parts = [str(item).strip() for item in value if str(item).strip()]
        return "\n".join(parts) if parts else None
    text = str(value).strip()
    return text or None


def scan_enum_token(text: Any, candidates: Iterable[str]) -> str | None:
    """Match Amazon enum tokens inside longer supplier or title text."""
    haystack = str(text or "").strip()
    if not haystack:
        return None
    exact = {str(item).lower(): str(item) for item in candidates}
    lowered = haystack.lower()
    if lowered in exact:
        return exact[lowered]
    for key in sorted(exact.keys(), key=len, reverse=True):
        token = key.replace("_", " ")
        if token in lowered or key in lowered:
            return exact[key]
    match = get_close_matches(lowered, list(exact.keys()), n=1, cutoff=0.75)
    return exact[match[0]] if match else None


COUNTRY_NAME_TO_ISO = {
    "china": "CN",
    "cn": "CN",
    "prc": "CN",
    "united states": "US",
    "usa": "US",
    "us": "US",
    "vietnam": "VN",
    "viet nam": "VN",
    "vn": "VN",
    "malaysia": "MY",
    "my": "MY",
    "india": "IN",
    "mexico": "MX",
    "canada": "CA",
}


def normalize_country_of_origin(value: Any) -> str:
    """Map supplier country names to Amazon ISO country codes when possible."""
    text = str(value or "").strip()
    if not text:
        return text
    return COUNTRY_NAME_TO_ISO.get(text.lower(), text)
