"""The four ways a report can go wrong, and what each means to the person and to the server.

Every error body a report sends carries a stable machine-readable `code`, so the page never classifies a response by its status
alone or by the words of its message.
"""

from northstar.errors import ValidationError


class ReportInputError(ValidationError):
    """Something the person sent is wrong. `path` says where in the request: ["parameters", "closing_date"]. The message is written
    to be shown."""

    def __init__(self, message: str, path: list[str] | tuple[str, ...]):
        super().__init__(message)
        self.path = list(path)

    @property
    def details(self) -> dict:
        return {"code": "invalid_input", "path": self.path}


class ReportUnavailable(ValidationError):
    """The request is fine but the data to answer it is not there yet, such as an exchange rate nobody has entered. A state of the
    household's data, not a mistake. `reason` is stable ("missing_rates", "no_system_currency") and `facts` carry what the page
    needs to say more."""

    def __init__(self, message: str, reason: str, **facts):
        super().__init__(message)
        self.reason = reason
        self.facts = facts

    @property
    def details(self) -> dict:
        return {"code": "unavailable_data", "reason": self.reason, **self.facts}


class ReportDefectError(Exception):
    """A report is broken, not the request: a calculation returned the wrong shape, a hierarchy that does not add up, a default that
    does not hold. It is not a ValidationError, because the person did nothing wrong. The message is a diagnostic for the log and
    names where the problem is, never a balance or a name, and it is never sent to the person."""


class ReportDefinitionError(Exception):
    """A report's definition is wrong, found when it is registered, so the application does not start with it."""
