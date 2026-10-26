"""UTC helpers. All timestamps are stored as ISO-8601 strings ending in 'Z'."""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_http_date(value: str | None) -> datetime | None:
    """Parse an HTTP date header (e.g. Last-Modified); None if absent or malformed."""
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
