"""The one place a broken rule becomes an HTTP response, so a route never catches these errors itself.

The status comes from the error's type, never from its message: 404 for NotFoundError, 409 for StaleImport (what was
reviewed has changed, so review again), UndoBlocked (the import cannot be undone as things now are) and
ConflictingEdit (a balance changed since the person opened it) and LocaleChanged (their number and date format changed since
the form was opened), 422 for every other ValidationError. The body is {"detail": message} plus whatever the error lists in `details`.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from northstar.balance_import import StaleImport
from northstar.balances import ConflictingEdit
from northstar.import_register import UndoBlocked
from northstar.locales import LocaleChanged
from northstar.errors import NotFoundError, ValidationError

# The most specific class in the error's type chain wins, and ValidationError is in every chain, so every error has a status.
STATUS = {NotFoundError: 404, StaleImport: 409, UndoBlocked: 409, ConflictingEdit: 409, LocaleChanged: 409, ValidationError: 422}


def status_for(error: ValidationError) -> int:
    return next(STATUS[kind] for kind in type(error).__mro__ if kind in STATUS)


def respond(request: Request, error: ValidationError) -> JSONResponse:
    return JSONResponse({"detail": str(error), **error.details}, status_code=status_for(error))


def install(app: FastAPI) -> None:
    app.add_exception_handler(ValidationError, respond)
