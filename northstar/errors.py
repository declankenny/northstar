class ValidationError(ValueError):
    """A rule was broken. The message is written to be shown to the user."""


class NotFoundError(ValidationError):
    """The thing asked for does not exist (or no longer does). The web layer answers 404."""
