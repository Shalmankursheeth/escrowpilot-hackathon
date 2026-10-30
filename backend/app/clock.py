"""Single source of 'now' so tests can move time forward."""
from datetime import datetime, timezone


def now() -> datetime:
    """Naive UTC time (stored and compared as naive UTC everywhere)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
