"""The only place the app asks what the date and time are, so tests can fix them."""

from datetime import date, datetime, timezone


def today() -> date:
    """Today's date on the machine running the app. No timezone logic in v1."""
    return date.today()


def now() -> datetime:
    """The current moment, in UTC. Used for sign-in throttling, which needs a time and not just a date."""
    return datetime.now(timezone.utc)
