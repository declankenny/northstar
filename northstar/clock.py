"""The only place the app asks what today's date is."""

from datetime import date


def today() -> date:
    """Today's date on the machine running the app. No timezone logic in v1."""
    return date.today()
