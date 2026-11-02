"""The one place a broken rule becomes an HTTP response, so a route never catches these errors itself.

The status comes from the error's type, never from its message: 404 for NotFoundError, 409 for StaleImport (what was
reviewed has changed, so review again), 422 for every other ValidationError. The body is {"detail": message} plus
whatever the error lists in `details`.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from northstar.balance_import import StaleImport
from northstar.errors import NotFoundError, ValidationError

STATUS = {NotFoundError: 404, StaleImport: 409}
DEFAULT_STATUS = 422


def status_for(error: ValidationError) -> int:
    for kind in type(error).__mro__:
        if kind in STATUS:
            return STATUS[kind]
    return DEFAULT_STATUS


def respond(request: Request, error: ValidationError) -> JSONResponse:
    return JSONResponse({"detail": str(error), **error.details}, status_code=status_for(error))


def install(app: FastAPI) -> None:
    app.add_exception_handler(ValidationError, respond)
