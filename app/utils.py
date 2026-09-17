from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re


MONEY_RE = re.compile(r"\d+(?:[.,]\d{1,2})?")
URL_RE = re.compile(r"(https?://|t\.me(?:/|\b)|telegram\.me(?:/|\b)|www\.|@[A-Za-z0-9_]{4,})", re.I)


def parse_money(raw: str) -> Decimal:
    match = MONEY_RE.search(raw or "")
    if not match:
        return Decimal("0")
    try:
        return Decimal(match.group(0).replace(",", "."))
    except InvalidOperation:
        return Decimal("0")


def parse_positive_int(raw: str, maximum: int) -> tuple[int | None, str | None]:
    cleaned = (raw or "").strip().replace(" ", "")
    if not cleaned.isdigit():
        return None, "not_number"
    value = int(cleaned)
    if value < 1:
        return None, "too_small"
    if value > maximum:
        return None, "too_large"
    return value, None


def next_progress_milestone(valid: int, total: int, last_sent: int) -> int | None:
    if total <= 0:
        return None
    percentage = (valid * 100) // total
    for milestone in (25, 50, 75):
        if percentage >= milestone and last_sent < milestone:
            return milestone
    return None


def contains_external_reference(text: str | None, entities=None) -> bool:
    if text and URL_RE.search(text):
        return True
    for entity in entities or []:
        entity_type = getattr(entity, "type", "")
        entity_type = str(getattr(entity_type, "value", entity_type))
        if entity_type in {"url", "text_link", "mention"}:
            return True
    return False


def truncate(value: str | None, maximum: int) -> str:
    return (value or "").strip()[:maximum]
