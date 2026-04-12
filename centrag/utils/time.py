from datetime import UTC, datetime


def utcnow() -> datetime:
    """Centralized timezone-aware current UTC time."""
    return datetime.now(UTC)
