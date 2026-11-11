"""JSON endpoints for the account page: one account, its balances, and the actions on them.

Like the other routes, these call the plain functions in accounts.py and balances.py and add no
rules of their own. Every change answers with the account's whole page, so the browser shows
exactly what the server now holds. A broken rule is a 422 and an unknown account or balance a 404.
"""

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from northstar import accounts, balance_export, balances, clock, currencies
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
    types: list[TypeOut]     # the types an edit may choose from (same class)
    other_class: OtherClass  # the class a class change would move the account to
    today: str               # the server's today(), so the browser never needs its own clock


class ClassTypes(BaseModel):
    id: int
    name: str
    types: list[TypeOut]


class AccountOptions(BaseModel):
    """What the Add account dialog offers. The list of accounts is the list framework's (`/api/lists/accounts`)."""
    currency: CurrencyOut | None     # the system currency; null while it is unset, when no account can be added
    currencies: list[CurrencyOut]    # what a new account can be in: the system currency first, then the other usable ones
    classes: list[ClassTypes]        # the types each class offers
    today: str


class AccountCreated(BaseModel):
    id: int


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


def _options(conn) -> dict:
    return {"currency": currencies.system_currency_dict(conn), "currencies": currencies.choosable(conn),
            "classes": accounts.classes_with_types(conn), "today": clock.today().isoformat()}


# Declared before the routes of one account, whose id is a number, so that "options" is never read as an id.
@router.get("/accounts/options", response_model=AccountOptions)
def account_options(request: Request):
    return run(request, _options)


@router.post("/accounts", response_model=AccountCreated, status_code=201)
def add_account(body: NewAccount, request: Request):
    """Adds the account (and its first balance, if an amount is typed) and answers with its id."""
    def action(conn):
        account_id = balances.add_account_with_balance(
            operation(request, conn), body.account_class, body.name, body.type_id, body.notes, body.amount, body.date,
            clock.today(), body.locale, body.currency)
        return {"id": account_id}
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


class ReportingOut(BaseModel):
    value: int | None        # in the system currency, empty when the account's currency has no rate on or before the date
    scale: int               # the system currency's decimal places
    unit: str                # its code
    rate_date: str | None    # the date of the rate used; empty with no value


class BalanceAccountOut(BaseModel):
    """What a balance's own page needs of its account, and no more."""
    id: int
    name: str
    currency: CurrencyOut
    class_name: str
    type_name: str
    is_open: bool


class NeighbourOut(BaseModel):
    as_of_date: str
    amount_cents: int


class NeighboursOut(BaseModel):
    older: NeighbourOut | None    # the balance before this one on the account, if any
    newer: NeighbourOut | None    # the balance after it


class BalancePageOut(BaseModel):
    account: BalanceAccountOut
    balance: BalanceOut
    reporting: ReportingOut | None    # empty when the account is in the system currency, or there is none yet
    entered_by: str
    entered_on: str          # the UTC date it was entered
    changed_by: str
    changed_on: str


@router.get("/balances/{balance_id:int}", response_model=BalancePageOut)         # not "/balances/update", which is the Update balances page
def read_balance(balance_id: int, request: Request):
    """One balance for its own page: the balance, a few facts about its account and the details. A balance that is gone is a 404."""
    def action(conn):
        balance = balances.get_balance(conn, balance_id)
        account = accounts.account_summary(conn, balance["account_id"], clock.today())
        return {"account": account, "balance": balance,
                **balances.balance_details(conn, balance_id, account["currency"]["code"])}
    return run(request, action)


@router.get("/balances/{balance_id:int}/neighbours", response_model=NeighboursOut)
def read_neighbours(balance_id: int, request: Request):
    """The balances either side of this one, for the sentence that says what deleting it does. A balance that is gone is a 404."""
    return run(request, lambda conn: balances.neighbours(conn, balance_id))


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
