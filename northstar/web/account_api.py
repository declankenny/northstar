"""JSON endpoints for the account page: one account, its balances, and the actions on them.

Like the other routes, these call the plain functions in accounts.py and balances.py and add no
rules of their own. Every change answers with the account's whole page, so the browser shows
exactly what the server now holds. A broken rule is a 422 and an unknown account or balance a 404.
"""

from contextlib import closing

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from northstar import accounts, balances, clock, db
from northstar.errors import NotFoundError, ValidationError

router = APIRouter(prefix="/api")


class BalanceOut(BaseModel):
    id: int
    as_of_date: str          # YYYY-MM-DD, a calendar date with no timezone
    amount_cents: int
    note: str | None


class TypeOut(BaseModel):
    id: int
    name: str


class OtherClass(BaseModel):
    id: int
    name: str
    types: list[TypeOut]


class AccountOut(BaseModel):
    id: int
    name: str
    class_name: str
    type_id: int
    type_name: str
    is_open: bool
    notes: str | None
    stale_after_days: int
    balance_count: int
    earliest_date: str | None
    last_date: str | None
    last_cents: int | None
    days_since: int | None
    stale: bool
    balances: list[BalanceOut]
    types: list[TypeOut]     # the types an edit may choose from (same class)
    other_class: OtherClass  # the class a class change would move the account to
    today: str               # the server's today(), so the browser never needs its own clock


class AccountChange(BaseModel):
    name: str
    type_id: int
    notes: str | None = None


class ClassChange(BaseModel):
    type_id: int             # a type of the other class: class and type change together


class BalanceEntry(BaseModel):
    date: str                # typed text, checked by the same rules as the classic pages
    amount: str
    note: str | None = None


def _run(request: Request, action):
    """Run an action on a connection, turning a broken rule into an error response."""
    with closing(db.connect(request.app.state.db_path)) as conn:
        try:
            return action(conn)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error))
        except ValidationError as error:
            raise HTTPException(status_code=422, detail=str(error))


def _page(conn, account_id: int) -> dict:
    today = clock.today()
    return {**accounts.account_page(conn, account_id, today), "today": today.isoformat()}


@router.get("/accounts/{account_id}", response_model=AccountOut)
def read_account(account_id: int, request: Request):
    return _run(request, lambda conn: _page(conn, account_id))


@router.patch("/accounts/{account_id}", response_model=AccountOut)
def edit_account(account_id: int, body: AccountChange, request: Request):
    def action(conn):
        accounts.update_account(conn, account_id, body.name, body.type_id, body.notes)
        return _page(conn, account_id)
    return _run(request, action)


@router.post("/accounts/{account_id}/change-class", response_model=AccountOut)
def change_class(account_id: int, body: ClassChange, request: Request):
    def action(conn):
        accounts.change_class(conn, account_id, body.type_id)
        return _page(conn, account_id)
    return _run(request, action)


@router.post("/accounts/{account_id}/close", response_model=AccountOut)
def close_account(account_id: int, request: Request):
    def action(conn):
        accounts.close_account(conn, account_id)
        return _page(conn, account_id)
    return _run(request, action)


@router.post("/accounts/{account_id}/reopen", response_model=AccountOut)
def reopen_account(account_id: int, request: Request):
    def action(conn):
        accounts.reopen_account(conn, account_id)
        return _page(conn, account_id)
    return _run(request, action)


@router.delete("/accounts/{account_id}", status_code=204)
def delete_account(account_id: int, request: Request):
    _run(request, lambda conn: accounts.delete_account(conn, account_id))
    return Response(status_code=204)


@router.post("/accounts/{account_id}/balances", response_model=AccountOut)
def add_balance(account_id: int, body: BalanceEntry, request: Request):
    """A date that already has a balance is edited, as on the classic pages."""
    def action(conn):
        balances.add_balance(conn, account_id, body.date, body.amount, body.note, clock.today())
        return _page(conn, account_id)
    return _run(request, action)


@router.patch("/balances/{balance_id}", response_model=AccountOut)
def edit_balance(balance_id: int, body: BalanceEntry, request: Request):
    def action(conn):
        account_id = balances.get_balance(conn, balance_id)["account_id"]
        balances.update_balance(conn, balance_id, body.date, body.amount, body.note, clock.today())
        return _page(conn, account_id)
    return _run(request, action)


@router.delete("/balances/{balance_id}", response_model=AccountOut)
def delete_balance(balance_id: int, request: Request):
    def action(conn):
        account_id = balances.get_balance(conn, balance_id)["account_id"]
        balances.delete_balance(conn, balance_id)
        return _page(conn, account_id)
    return _run(request, action)
