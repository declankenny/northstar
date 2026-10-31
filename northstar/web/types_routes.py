"""Account types screen (classic page). Admins only, like the new one."""

from contextlib import closing

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from northstar import account_types, db
from northstar.errors import ValidationError
from northstar.web.auth_routes import require_admin

router = APIRouter(dependencies=[Depends(require_admin)])


def _int(value: str | None) -> int | None:
    """Form text to a number. Missing stays None. Junk becomes -1, which the rules reject."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return -1


def _page(request: Request, error: str | None = None, status_code: int = 200,
          add_form: dict | None = None):
    with closing(db.connect(request.app.state.db_path)) as conn:
        context = {
            "types": account_types.list_types(conn),
            "classes": account_types.list_classes(conn),
            "error": error,
            "add_form": add_form or {"name": "", "class_id": 1, "stale_after_days": 35},
        }
    return request.app.state.templates.TemplateResponse(
        request, "types.html", context, status_code=status_code
    )


def _done() -> RedirectResponse:
    return RedirectResponse("/types", status_code=303)


@router.get("/types")
def types_page(request: Request):
    return _page(request)


@router.post("/types")
def add_type(request: Request, name: str = Form(""), class_id: str | None = Form(None),
             stale_after_days: str = Form("")):
    try:
        with closing(db.connect(request.app.state.db_path)) as conn:
            account_types.add_type(conn, name, _int(class_id), stale_after_days)
    except ValidationError as err:
        form = {"name": name, "class_id": _int(class_id), "stale_after_days": stale_after_days}
        return _page(request, str(err), 400, form)
    return _done()


@router.post("/types/{type_id}")
def update_type(request: Request, type_id: int, name: str = Form(""),
                stale_after_days: str = Form(""), class_id: str | None = Form(None)):
    try:
        with closing(db.connect(request.app.state.db_path)) as conn:
            account_types.update_type(conn, type_id, name, stale_after_days, _int(class_id))
    except ValidationError as err:
        return _page(request, str(err), 400)
    return _done()


@router.post("/types/{type_id}/delete")
def delete_type(request: Request, type_id: int):
    try:
        with closing(db.connect(request.app.state.db_path)) as conn:
            account_types.delete_type(conn, type_id)
    except ValidationError as err:
        return _page(request, str(err), 400)
    return _done()
