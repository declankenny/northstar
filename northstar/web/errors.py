"""The one place a broken rule becomes an HTTP response, so a route never catches these errors itself.

The status comes from the error's type, never from its message: 403 for NotAllowedError, 404 for NotFoundError, 409 for StaleImport (what was
reviewed has changed, so review again), UndoBlocked (the import cannot be undone as things now are) and
ConflictingEdit (a balance changed since the person opened it) and LocaleChanged (their number and date format changed since
the form was opened), 422 for every other ValidationError. The body is {"detail": message} plus whatever the error lists in `details`.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from northstar.balance_import import StaleImport
from northstar.balances import ConflictingEdit
from northstar.import_register import UndoBlocked
from northstar.locales import LocaleChanged
from northstar.reports.errors import ReportDefectError
from northstar.errors import NotAllowedError, NotFoundError, ValidationError
from northstar.setup import SetupClosed, SetupSessionEnded

# The most specific class in the error's type chain wins, and ValidationError is in every chain, so every error has a status.
# SetupClosed is a 409 (setup is over) and SetupSessionEnded a 401 (the setup page asks for the token again; it is not a sign-in).
STATUS = {NotAllowedError: 403, NotFoundError: 404, StaleImport: 409, UndoBlocked: 409, ConflictingEdit: 409, LocaleChanged: 409,
          SetupClosed: 409, SetupSessionEnded: 401, ValidationError: 422}


def status_for(error: ValidationError) -> int:
    return next(STATUS[kind] for kind in type(error).__mro__ if kind in STATUS)


def respond(request: Request, error: ValidationError) -> JSONResponse:
    return JSONResponse({"detail": str(error), **error.details}, status_code=status_for(error))


log = logging.getLogger(__name__)


def report_defect(request: Request, error: ReportDefectError) -> JSONResponse:
    """A report that is itself broken. The diagnostic goes to the log and never to the person, and there is no partial result."""
    log.error("A report failed: %s", error, exc_info=error.__cause__ is not None)
    return JSONResponse({"detail": "That report could not be worked out. This is a fault in Northstar, not something you did.",
                         "code": "calculation_error"}, status_code=500)


def install(app: FastAPI) -> None:
    app.add_exception_handler(ValidationError, respond)
    app.add_exception_handler(ReportDefectError, report_defect)
