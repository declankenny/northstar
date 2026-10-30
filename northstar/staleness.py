"""How old is an account's latest balance, and is that too old for its type."""

from datetime import date


def days_since(last: str | None, today: date) -> int | None:
    """Days from the latest balance's date to today. None when there is no balance."""
    if last is None:
        return None
    return (today - date.fromisoformat(last)).days


def is_stale(last: str | None, today: date, stale_after_days: int) -> bool:
    """Stale when older than the type's limit. An account with no balance counts as stale."""
    days = days_since(last, today)
    return days is None or days > stale_after_days
