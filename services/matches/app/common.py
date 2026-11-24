"""Shared helpers used by both the matches and catalog domains."""

from datetime import datetime, timezone

DIFFICULTIES = ("Easy", "Medium", "Hard")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_db_time(value: datetime) -> str:
    """Store timestamps as UTC ISO strings. Time columns are TEXT."""

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc).isoformat()


def parse_db_time(value) -> datetime | None:
    """Read a TEXT timestamp back into a timezone-aware datetime."""

    if value is None:
        return None

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)
