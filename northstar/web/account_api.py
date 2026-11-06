"""JSON endpoints for the account page: one account, its balances, and the actions on them.

Like the other routes, these call the plain functions in accounts.py and balances.py and add no
rules of their own. Every change answers with the account's whole page, so the browser shows
exactly what the server now holds. A broken rule is a 422 and an unknown account or balance a 404.
"""

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from northstar import accounts, balance_export, balances, clock, currencies, networth
from northstar.web.auth_routes import operation, run

router = APIRouter(prefix="/api")


class BalanceOut(BaseModel):
    id: int
    as_of_date: str          # YYYY-MM-DD, a calendar date with no timezone
    amount_cents: int
    note: str | None
    version: int             # the id of the operation that last wrote it; sent back with an edit or delete


class TypeOut(BaseModel):
    id: int
    name: str


class OtherClass(BaseModel):
    id: int
    name: str
    types: list[TypeOut]


class CurrencyOut(BaseModel):
    code: str
    name: str
    minor_units: int


class AccountOut(BaseModel):
    id: int
    name: str
    currency: CurrencyOut    # the account's own currency: every amount on its page is in it
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


class ListedAccount(BaseModel):
    id: int
    name: str
    currency: CurrencyOut    # the currency last_cents is in
    class_name: str
    type_name: str
    notes: str | None
    balance_count: int
    last_date: str | None
    last_cents: int | None
    days_since: int | None
    stale: bool


class ClassTypes(BaseModel):
    id: int
    name: str
    types: list[TypeOut]


class Totals(BaseModel):
    assets: int
    liabilities: int


class AccountList(BaseModel):
    currency: CurrencyOut | None     # the system currency; null while it is unset, when no account can be added
    currencies: list[CurrencyOut]    # what a new account can be in: the system currency first, then the other usable ones
    closed: bool
    accounts: list[ListedAccount]    # grouped by class, then type, then name
    totals: Totals | None            # as of today, from net_worth_on; only for the open list
    classes: list[ClassTypes]        # what the Add account dialog offers
    today: str


class NewAccount(BaseModel):
    account_class: str               # "asset" or "liability"
    name: str
    type_id: int
    notes: str | None = None
    currency: str | None = None      # a currency code; left out means the system currency
    amount: str | None = None        # typed text; blank adds the account with no balance
    date: str | None = None          # as of; blank means today
    locale: str | None = None        # the number and date format the page was using, refused if it is no longer the saved one


class AccountChange(BaseModel):
    name: str
    type_id: int
    notes: str | None = None


class ClassChange(BaseModel):
    type_id: int             # a type of the other class: class and type change together


class BalanceEntry(BaseModel):
    date: str                # typed text, checked by the server
    amount: str
    note: str | None = None
    locale: str | None = None        # the number and date format the page was using, refused if it is no longer the saved one


class BalanceEdit(BalanceEntry):
    version: int             # the balance's version when the page loaded it; the edit is refused if it has changed since


def _page(conn, account_id: int) -> dict:
    today = clock.today()
    return {**accounts.account_page(conn, account_id, today), "today": today.isoformat()}


def _list(conn, closed: bool) -> dict:
    today = clock.today()
    totals = None if closed else networth.net_worth_on(conn, today)
    return {"currency": currencies.system_currency_dict(conn), "currencies": currencies.choosable(conn), "closed": closed,
            "accounts": accounts.account_rows(conn, today, closed),
            "totals": totals, "classes": accounts.classes_with_types(conn), "today": today.isoformat()}


@router.get("/accounts", response_model=AccountList)
def list_accounts(request: Request, closed: bool = False):
    return run(request, lambda conn: _list(conn, closed))


@router.post("/accounts", response_model=AccountList, status_code=201)
def add_account(body: NewAccount, request: Request):
    """Adds the account (and its first balance, if an amount is typed) and answers with the open list."""
    def action(conn):
        balances.add_account_with_balance(operation(request, conn), body.account_class, body.name, body.type_id,
                                          body.notes, body.amount, body.date, clock.today(), body.locale, body.currency)
        return _list(conn, closed=False)
    return run(request, action)


@router.get("/accounts/{account_id}", response_model=AccountOut)
def read_account(account_id: int, request: Request):
    return run(request, lambda conn: _page(conn, account_id))


@router.get("/accounts/{account_id}/export")
def export_balances(account_id: int, request: Request):
    """The account's balances as a CSV download, which the browser saves without asking."""
    def action(conn):
        text = balance_export.export_csv(conn, account_id)
        name = balance_export.file_name(accounts.get_account(conn, account_id)["name"], clock.today())
        return Response(text, media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})
    return run(request, action)


@router.patch("/accounts/{account_id}", response_model=AccountOut)
def edit_account(account_id: int, body: AccountChange, request: Request):
    def action(conn):
        accounts.update_account(operation(request, conn), account_id, body.name, body.type_id, body.notes)
        return _page(conn, account_id)
    return run(request, action)


@router.post("/accounts/{account_id}/change-class", response_model=AccountOut)
def change_class(account_id: int, body: ClassChange, request: Request):
    def action(conn):
        accounts.change_class(operation(request, conn), account_id, body.type_id)
        return _page(conn, account_id)
    return run(request, action)


@router.post("/accounts/{account_id}/close", response_model=AccountOut)
def close_account(account_id: int, request: Request):
    def action(conn):
        accounts.close_account(operation(request, conn), account_id)
        return _page(conn, account_id)
    return run(request, action)


@router.post("/accounts/{account_id}/reopen", response_model=AccountOut)
def reopen_account(account_id: int, request: Request):
    def action(conn):
        accounts.reopen_account(operation(request, conn), account_id)
        return _page(conn, account_id)
    return run(request, action)


@router.delete("/accounts/{account_id}", status_code=204)
def delete_account(account_id: int, request: Request):
    run(request, lambda conn: accounts.delete_account(operation(request, conn), account_id))
    return Response(status_code=204)


@router.post("/accounts/{account_id}/balances", response_model=AccountOut)
def add_balance(account_id: int, body: BalanceEntry, request: Request):
    """A date that already has a balance is edited."""
    def action(conn):
        balances.add_balance(operation(request, conn), account_id, body.date, body.amount, body.note, clock.today(),
                             locale_tag=body.locale)
        return _page(conn, account_id)
    return run(request, action)


@router.patch("/balances/{balance_id}", response_model=AccountOut)
def edit_balance(balance_id: int, body: BalanceEdit, request: Request):
    def action(conn):
        balances.update_balance(operation(request, conn), balance_id, body.date, body.amount, body.note, clock.today(), body.version,
                                locale_tag=body.locale)
        return _page(conn, balances.get_balance(conn, balance_id)["account_id"])
    return run(request, action)


@router.delete("/balances/{balance_id}", response_model=AccountOut)
def delete_balance(balance_id: int, version: int, request: Request):
    def action(conn):
        return _page(conn, balances.delete_balance(operation(request, conn), balance_id, version))
    return run(request, action)
