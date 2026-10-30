"""Accounts screens."""

from contextlib import closing

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import RedirectResponse

from northstar import accounts, clock, db
from northstar.errors import ValidationError

router = APIRouter()


def _int(value: str | None) -> int | None:
    """Form text to a number. Missing stays None. Junk becomes -1, which the rules reject."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return -1


def _conn(request: Request):
    return closing(db.connect(request.app.state.db_path))


def _render(request: Request, template: str, context: dict, status_code: int = 200):
    return request.app.state.templates.TemplateResponse(
        request, template, context, status_code=status_code
    )


def _done(to: str = "/accounts") -> RedirectResponse:
    return RedirectResponse(to, status_code=303)


def _list_page(request: Request, closed: bool = False, error: str | None = None,
               status_code: int = 200):
    with _conn(request) as conn:
        context = {"accounts": accounts.list_accounts(conn, closed), "closed": closed, "error": error}
    return _render(request, "accounts.html", context, status_code)


def _form_page(request: Request, conn, cls, form: dict, account=None,
               error: str | None = None, status_code: int = 200):
    context = {
        "cls": cls, "account": account, "form": form, "error": error,
        "types": accounts.types_for_class(conn, cls["id"]),
    }
    return _render(request, "account_form.html", context, status_code)


@router.get("/accounts")
def accounts_page(request: Request, show: str | None = None):
    return _list_page(request, closed=(show == "closed"))


@router.get("/accounts/new")
def new_account_page(request: Request, account_class: str = Query("", alias="class")):
    with _conn(request) as conn:
        try:
            cls = accounts.get_class_by_slug(conn, account_class)
        except ValidationError as err:
            return _list_page(request, error=str(err), status_code=400)
        return _form_page(request, conn, cls, {"name": "", "type_id": None, "notes": ""})


@router.get("/accounts/{account_id}")
def account_detail_page(request: Request, account_id: int):
    # Registered after /accounts/new, so "new" is never read as an account id.
    with _conn(request) as conn:
        try:
            summary = accounts.account_summary(conn, account_id, clock.today())
        except ValidationError as err:
            return _list_page(request, error=str(err), status_code=404)
        history = accounts.balance_history(conn, account_id)
    return _render(request, "account_detail.html", {"a": summary, "history": history})


@router.post("/accounts")
def add_account(request: Request, account_class: str = Form("", alias="class"),
                name: str = Form(""), type_id: str | None = Form(None), notes: str = Form("")):
    with _conn(request) as conn:
        try:
            cls = accounts.get_class_by_slug(conn, account_class)
        except ValidationError as err:
            return _list_page(request, error=str(err), status_code=400)
        try:
            accounts.add_account(conn, name, cls["id"], _int(type_id), notes)
        except ValidationError as err:
            form = {"name": name, "type_id": _int(type_id), "notes": notes}
            return _form_page(request, conn, cls, form, error=str(err), status_code=400)
    return _done()


@router.get("/accounts/{account_id}/edit")
def edit_account_page(request: Request, account_id: int):
    with _conn(request) as conn:
        try:
            account = accounts.get_account(conn, account_id)
        except ValidationError as err:
            return _list_page(request, error=str(err), status_code=404)
        cls = {"id": account["class_id"], "name": account["class_name"]}
        form = {"name": account["name"], "type_id": account["type_id"], "notes": account["notes"] or ""}
        return _form_page(request, conn, cls, form, account=account)


@router.post("/accounts/{account_id}")
def update_account(request: Request, account_id: int, name: str = Form(""),
                   type_id: str | None = Form(None), notes: str = Form("")):
    with _conn(request) as conn:
        try:
            account = accounts.get_account(conn, account_id)
        except ValidationError as err:
            return _list_page(request, error=str(err), status_code=404)
        try:
            accounts.update_account(conn, account_id, name, _int(type_id), notes)
        except ValidationError as err:
            cls = {"id": account["class_id"], "name": account["class_name"]}
            form = {"name": name, "type_id": _int(type_id), "notes": notes}
            return _form_page(request, conn, cls, form, account=account, error=str(err), status_code=400)
    return _done(f"/accounts/{account_id}")


def _class_page(request: Request, conn, account, error: str | None = None, status_code: int = 200):
    target = accounts.other_class(conn, account["class_id"])
    context = {
        "account": account, "target": target, "error": error,
        "types": accounts.types_for_class(conn, target["id"]),
        "impact": accounts.class_change_impact(conn, account["id"]),
    }
    return _render(request, "account_class.html", context, status_code)


@router.get("/accounts/{account_id}/change-class")
def change_class_page(request: Request, account_id: int):
    with _conn(request) as conn:
        try:
            account = accounts.get_account(conn, account_id)
        except ValidationError as err:
            return _list_page(request, error=str(err), status_code=404)
        return _class_page(request, conn, account)


@router.post("/accounts/{account_id}/change-class")
def change_class(request: Request, account_id: int, type_id: str | None = Form(None)):
    with _conn(request) as conn:
        try:
            account = accounts.get_account(conn, account_id)
        except ValidationError as err:
            return _list_page(request, error=str(err), status_code=404)
        try:
            accounts.change_class(conn, account_id, _int(type_id))
        except ValidationError as err:
            return _class_page(request, conn, account, str(err), 400)
    return _done(f"/accounts/{account_id}")


@router.post("/accounts/{account_id}/close")
def close_account(request: Request, account_id: int):
    try:
        with _conn(request) as conn:
            accounts.close_account(conn, account_id)
    except ValidationError as err:
        return _list_page(request, error=str(err), status_code=400)
    return _done()


@router.post("/accounts/{account_id}/reopen")
def reopen_account(request: Request, account_id: int):
    try:
        with _conn(request) as conn:
            accounts.reopen_account(conn, account_id)
    except ValidationError as err:
        return _list_page(request, closed=True, error=str(err), status_code=400)
    return _done()


@router.get("/accounts/{account_id}/delete")
def delete_account_page(request: Request, account_id: int):
    with _conn(request) as conn:
        try:
            account = accounts.get_account(conn, account_id)
        except ValidationError as err:
            return _list_page(request, error=str(err), status_code=404)
    return _render(request, "account_delete.html", {"account": account})


@router.post("/accounts/{account_id}/delete")
def delete_account(request: Request, account_id: int):
    try:
        with _conn(request) as conn:
            accounts.delete_account(conn, account_id)
    except ValidationError as err:
        return _list_page(request, error=str(err), status_code=404)
    return _done()
