class ValidationError(ValueError):
    """A rule was broken. The message is written to be shown to the user."""

    @property
    def details(self) -> dict:
        """Facts about the failure that go to the client beside the message, as plain data (never a status code)."""
        return {}


class NotFoundError(ValidationError):
    """The thing asked for does not exist (or no longer does)."""
