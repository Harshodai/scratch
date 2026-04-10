from datetime import datetime, timezone

def utcnow() -> datetime:
    """Centralized timezone-aware current UTC time."""
    return datetime.now(timezone.utc)
