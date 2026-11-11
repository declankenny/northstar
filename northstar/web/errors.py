"""The one place a broken rule becomes an HTTP response, so a route never catches these errors itself.

The status comes from the error's type, never from its message: 403 for NotAllowedError, 404 for NotFoundError, 409 for StaleImport (what was
reviewed has changed, so review again), UndoBlocked (the import cannot be undone as things now are) and
ConflictingEdit (a balance changed since the person opened it) and LocaleChanged (their number and date format changed since
the form was opened), 422 for every other ValidationError. The body is {"detail": message} plus whatever the error lists in `details`.
"""

import logging
import traceback

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
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
    """A report that is itself broken. The diagnostic goes to the log and never to the person, and there is no partial result.

    The log gets the framework's own message (which names a place, never a value) and, when a calculation raised, only where it
    raised: the type of the exception and its frames as file, line and function. The exception's own message and its traceback text are
    never logged, because a message such as a KeyError's can hold a name or a balance."""
    cause = error.__cause__
    where = ""
    if cause is not None:
        frames = traceback.extract_tb(cause.__traceback__)
        where = f" [{type(cause).__name__} at " + " <- ".join(f"{frame.filename.rsplit('/', 1)[-1].rsplit(chr(92), 1)[-1]}:{frame.lineno} {frame.name}" for frame in reversed(frames)) + "]"
    log.error("A report failed: %s%s", error, where)
    return JSONResponse({"detail": "That report could not be worked out. This is a fault in Northstar, not something you did.",
                         "code": "calculation_error"}, status_code=500)


async def request_invalid(request: Request, error: RequestValidationError):
    """A request FastAPI itself cannot read (a body that is not JSON). Under /api/reports it is the report error contract, so the page
    classifies it by `code` like every other report failure; everywhere else it stays FastAPI's own answer."""
    if request.url.path.startswith("/api/reports"):
        return JSONResponse({"detail": "The request must be a JSON object.", "code": "invalid_input", "path": []}, status_code=422)
    return await request_validation_exception_handler(request, error)


def install(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, request_invalid)
    app.add_exception_handler(ValidationError, respond)
    app.add_exception_handler(ReportDefectError, report_defect)
