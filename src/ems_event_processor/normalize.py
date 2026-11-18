"""Small explicit conversions. No fuzzy matching or operational inference."""

import re
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation

from .models import Value


def text(value: Value) -> str:
    return "" if value is None else str(value).strip()


def parse_date(value: Value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = text(value)
    raw = re.sub(
        r"^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+", "", raw, flags=re.I
    )
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def parse_time(value: Value) -> time | None:
    if isinstance(value, datetime):
        return value.time()
    if isinstance(value, time):
        return value
    if isinstance(value, (int, float)) and 0 <= value < 1:
        seconds = round(value * 86400) % 86400
        return time(seconds // 3600, seconds % 3600 // 60, seconds % 60)
    for fmt in ("%I:%M %p", "%I:%M%p", "%I %p", "%I%p", "%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(text(value).upper(), fmt).time()
        except ValueError:
            continue
    return None


def quantity(value: Value) -> Decimal | None:
    raw = text(value)
    if not re.fullmatch(r"(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?", raw):
        return None
    try:
        return Decimal(raw.replace(",", ""))
    except InvalidOperation:
        return None


def split_request(value: str) -> tuple[str, Decimal | None]:
    """Only explicit quantity prefixes/suffixes; dimensions are never quantities."""
    raw = value.strip()
    explicit = re.fullmatch(r"(?:Qty\s*[:=]\s*)?([\d,.]+)\s*(?:[x×:]\s*|\s+)(.+)", raw, flags=re.I)
    if explicit:
        count, description = explicit.groups()
        if re.match(r"(?:ft\b|feet\b|foot\b|in\b|inch\b|inches\b|['\"′″])", description, re.I):
            return raw, None
        return description.strip(), quantity(count)
    suffix = re.fullmatch(r"(.+?)\s+(?:[x×]\s*(\d[\d,.]*)|\((\d[\d,.]*)\))", raw)
    if suffix:
        description, a, b = suffix.groups()
        return description.strip(), quantity(a or b)
    return raw, None
