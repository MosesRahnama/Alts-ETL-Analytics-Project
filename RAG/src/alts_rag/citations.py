"""Quote and number citation checks against indexed original text."""

from __future__ import annotations

import re

NUMBER_CHARS = re.compile(
    r"(?<![\w.])(?:\(\s*[$€£]?\s*[0-9][0-9,.]*%?\s*\)|-\s*[$€£]?\s*[0-9][0-9,.]*%?|[$€£]?\s*[0-9][0-9,.]*%?)(?![\w.])"
)


def normalize_number(value: str) -> str:
    stripped = value.strip().translate(str.maketrans("", "", "$€£,")).strip()
    negative = (stripped.startswith("(") and stripped.rstrip("%").endswith(")")) or stripped.startswith("-")
    stripped = stripped.lstrip("(").rstrip("%)").lstrip("-").strip()
    return ("-" if negative else "") + stripped


def number_in_quote(value: str, quote: str) -> bool:
    """A claimed numeral matches only at number boundaries.

    A substring inside a different number fails. 8.2 does not match 18.2 or 8.25.
    """

    claimed = normalize_number(value)
    if not claimed:
        return True
    if not any(ch.isdigit() for ch in claimed):
        return bool(re.search(r"(?<!\w)" + re.escape(value.strip()) + r"(?!\w)", quote, re.I))
    return any(normalize_number(match.group(0)) == claimed for match in NUMBER_CHARS.finditer(quote))


def quote_in_source(quote: str, original: str) -> bool:
    if not quote.strip():
        return False
    return quote.strip() in original


def rounding_note(text: str) -> bool:
    lowered = text.lower()
    return "round" in lowered and not any(token in lowered for token in ("fee", "gross", "net of", "dietz"))
