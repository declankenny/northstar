"""The endpoints every report uses. Like the other routes they add no rules: the report framework decides what a request means, and
these only check who may ask and carry the answer.

A report is calculated with a POST, because a filter's values are household data that should not be in an address or a log. It changes
nothing. An unknown report is a 404, an admin-only report is a 403 for anyone else, and a request that breaks a rule is a 422 whose
body says `code: "invalid_input"` and the `path` to the field, or `code: "unavailable_data"` and a `reason`. A report that is itself
broken is a 500 with `code: "calculation_error"` and no result.
"""

from typing import Any

from fastapi import APIRouter, Body, Request

from northstar import clock
from northstar.errors import NotAllowedError
from northstar.reports import engine, loader
from northstar.web.auth_routes import current_user, run

router = APIRouter(prefix="/api/reports")


def _report(key: str, user):
    definition = loader.get_report(key)
    if definition.admin_only and not user["is_admin"]:
        raise NotAllowedError("Only admins can see that report.")
    return definition


@router.get("")
def list_reports(request: Request):
    user = current_user(request)
    return {"reports": [{"key": d.key, "title": d.title, "description": d.description} for d in loader.visible_to(user)]}


@router.get("/{key}")
def describe_report(key: str, request: Request):
    definition = _report(key, current_user(request))
    return engine.describe(definition, clock.today())


@router.post("/{key}")
def calculate_report(key: str, request: Request, body: Any = Body(default_factory=dict)):
    # `Any`, not `dict`: a body that is not an object (an array, a string) must reach the framework, which refuses it with the
    # report error contract instead of FastAPI's own 422.
    user = current_user(request)
    definition = _report(key, user)
    today = clock.today()                        # read once: the calculation and what it echoes use the same day
    return run(request, lambda conn: engine.calculate(conn, definition, user, body, today))
