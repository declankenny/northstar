"""Update balances screen."""

from contextlib import closing

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from northstar import accounts, balances, clock, db
from northstar.errors import ValidationError
from northstar.money import cents_to_input

router = APIRouter()


def _count(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _page(request: Request, as_of_text: str | None, values: dict[int, str] | None = None,
          errors: dict[int, str] | None = None, error: str | None = None,
          saved: dict[str, int] | None = None, status_code: int = 200):
    """Render the screen for one date. A missing or bad date falls back to today."""
    today = clock.today()
    try:
        as_of = balances.parse_date(as_of_text, today) if as_of_text else today
    except ValidationError as err:
        as_of, error, status_code = today, str(err), 400
    with closing(db.connect(request.app.state.db_path)) as conn:
        rows = balances.update_rows(conn, as_of, today)
    if values is None:
        values = {r["id"]: cents_to_input(r["existing_cents"])
                  for r in rows if r["existing_cents"] is not None}
    context = {
        "as_of": as_of.isoformat(), "today": today.isoformat(), "rows": rows,
        "values": values, "errors": errors or {}, "error": error, "saved": saved,
    }
    return request.app.state.templates.TemplateResponse(
        request, "update_balances.html", context, status_code=status_code
    )


@router.get("/balances/update")
def update_page(request: Request, date: str | None = None, added: str | None = None,
                updated: str | None = None, unchanged: str | None = None):
    saved = None
    if added is not None or updated is not None or unchanged is not None:
        saved = {"added": _count(added) or 0, "updated": _count(updated) or 0,
                 "unchanged": _count(unchanged) or 0}
    return _page(request, date, saved=saved)


@router.post("/balances/update")
async def save_update(request: Request):
    form = await request.form()
    date_text = form.get("date")
    amounts: dict[int, str] = {}
    for key, value in form.items():
        if key.startswith("amount_") and key[7:].isascii() and key[7:].isdigit():
            amounts[int(key[7:])] = str(value)
    try:
        with closing(db.connect(request.app.state.db_path)) as conn:
            counts = balances.save_update(conn, date_text, amounts, clock.today())
    except balances.EntryErrors as err:
        return _page(request, date_text, values=amounts, errors=err.by_account,
                     error=str(err), status_code=400)
    except ValidationError as err:
        return _page(request, None, values=amounts, error=str(err), status_code=400)
    return RedirectResponse(
        f"/balances/update?date={date_text}&added={counts['added']}"
        f"&updated={counts['updated']}&unchanged={counts['unchanged']}",
        status_code=303,
    )


# -- one balance: edit and delete (reached from the account detail page) --

def _conn(request: Request):
    return closing(db.connect(request.app.state.db_path))


def _missing(request: Request, err: ValidationError):
    """The balance is gone: show the accounts list with the message."""
    with _conn(request) as conn:
        context = {"accounts": accounts.list_accounts(conn), "closed": False, "error": str(err)}
    return request.app.state.templates.TemplateResponse(
        request, "accounts.html", context, status_code=404)


def _balance_page(request: Request, template: str, balance: dict, form: dict | None = None,
                  error: str | None = None, status_code: int = 200):
    context = {
        "b": balance, "error": error, "today": clock.today().isoformat(),
        "form": form or {"date": balance["as_of_date"],
                         "amount": cents_to_input(balance["amount_cents"]),
                         "note": balance["note"] or ""},
    }
    return request.app.state.templates.TemplateResponse(
        request, template, context, status_code=status_code)


@router.get("/balances/{balance_id}/edit")
def edit_balance_page(request: Request, balance_id: int):
    with _conn(request) as conn:
        try:
            balance = balances.get_balance(conn, balance_id)
        except ValidationError as err:
            return _missing(request, err)
    return _balance_page(request, "balance_edit.html", balance)


@router.post("/balances/{balance_id}/edit")
async def edit_balance(request: Request, balance_id: int):
    form = await request.form()
    typed = {"date": str(form.get("date", "")), "amount": str(form.get("amount", "")),
             "note": str(form.get("note", ""))}
    with _conn(request) as conn:
        try:
            balance = balances.get_balance(conn, balance_id)
        except ValidationError as err:
            return _missing(request, err)
        try:
            result = balances.update_balance(
                conn, balance_id, typed["date"], typed["amount"], typed["note"], clock.today())
        except ValidationError as err:
            return _balance_page(request, "balance_edit.html", balance, typed, str(err), 400)
    return RedirectResponse(f"/accounts/{balance['account_id']}?saved={result}", status_code=303)


@router.get("/balances/{balance_id}/delete")
def delete_balance_page(request: Request, balance_id: int):
    with _conn(request) as conn:
        try:
            balance = balances.get_balance(conn, balance_id)
        except ValidationError as err:
            return _missing(request, err)
    return _balance_page(request, "balance_delete.html", balance)


@router.post("/balances/{balance_id}/delete")
def delete_balance(request: Request, balance_id: int):
    with _conn(request) as conn:
        try:
            balance = balances.get_balance(conn, balance_id)
        except ValidationError as err:
            return _missing(request, err)
        try:
            balances.delete_balance(conn, balance_id)
        except ValidationError as err:
            return _balance_page(request, "balance_delete.html", balance, error=str(err), status_code=400)
    return RedirectResponse(f"/accounts/{balance['account_id']}?saved=deleted", status_code=303)
