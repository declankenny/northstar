"""JSON endpoints for the admin Currencies pages. Every one needs an admin (403 otherwise).

Like the other routes, they call plain functions (currencies.py, rates.py) and add no rules of their own. The list shows the
catalog as stored. A currency's page shows it with its rates, switches it on or off together with the date its rates start from,
and adds or corrects a rate. The catalog itself is never edited here. Every change answers with the whole page, so the browser
shows what the server now holds.
"""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from northstar import clock, currencies, rate_fetch, rates
from northstar.web.auth_routes import operation, require_admin, run

router = APIRouter(prefix="/api/currencies", dependencies=[Depends(require_admin)])


class RateRow(BaseModel):
    id: int
    date: str              # YYYY-MM-DD, the day the rate is for
    rate: str              # the exact decimal as stored: 1 unit of this currency = rate units of the system currency
    source: str            # "manual" or "provider"
    changed: str           # YYYY-MM-DD, the day the rate was last written
    until: str | None      # the date of the next newer rate, or None for the newest: a correction changes net worth up to it


class Stale(BaseModel):
    last_date: str
    days: int              # whole days from the newest rate to today
    threshold: int         # the currency.rate.stale_days property


class FetchRun(BaseModel):
    date: str              # YYYY-MM-DD, the day the run started, in the installation's time zone
    time: str              # HH:MM, 24-hour, in the same zone
    outcome: str           # running, succeeded, failed or abandoned
    detail: str | None     # a short message written by Northstar, never provider text


class FetchStatus(BaseModel):
    time: str | None       # the daily start time (currency.rate.fetch_time), None when automatic fetching is off
    zone: str              # the installation's time zone name, UTC when none is set
    last_run: FetchRun | None


class CurrencyPage(BaseModel):
    code: str
    name: str
    minor_units: int
    is_enabled: bool
    is_system: bool                # the system currency: always enabled, no rates, no start date
    system_code: str | None
    rates_start: str | None        # the date rates are wanted from; empty until the currency is first enabled
    default_rates_start: str       # what the field starts at the first time: currency.rate.start.default
    account_count: int
    open_account_count: int
    can_add_rates: bool            # enabled or with accounts, and not the system currency
    rates: list[RateRow]           # newest first
    stale: Stale | None            # set when the newest rate is older than the threshold and an account is open
    fetch: FetchStatus | None      # the automatic fetch, set when rates can be added for this currency
    today: str


class CurrencyChange(BaseModel):
    is_enabled: bool | None = None     # left out means unchanged
    rates_start: str | None = None     # YYYY-MM-DD; left out means unchanged


class NewRate(BaseModel):
    date: str                          # YYYY-MM-DD
    rate: str                          # typed text, read in the person's number format
    locale: str | None = None          # the number and date format the page was using, refused if it is no longer the saved one


class RateCorrection(BaseModel):
    rate: str
    locale: str | None = None


def _page(conn, code: str) -> dict:
    today = clock.today()
    page = rates.currency_page(conn, code, today)
    return {**page, "fetch": rate_fetch.status(conn) if page["can_add_rates"] else None, "today": today.isoformat()}


@router.get("/{code}", response_model=CurrencyPage)
def get_currency(code: str, request: Request):
    return run(request, lambda conn: _page(conn, code))


@router.patch("/{code}", response_model=CurrencyPage)
def change_currency(code: str, body: CurrencyChange, request: Request):
    def action(conn):
        currencies.update_currency(operation(request, conn), code, body.is_enabled, body.rates_start, clock.today())
        return _page(conn, code)
    return run(request, action)


@router.post("/{code}/rates", response_model=CurrencyPage, status_code=201)
def add_rate(code: str, body: NewRate, request: Request):
    def action(conn):
        rates.add_rate(operation(request, conn), code, body.date, body.rate, clock.today(), body.locale)
        return _page(conn, code)
    return run(request, action)


@router.put("/{code}/rates/{rate_id}", response_model=CurrencyPage)
def correct_rate(code: str, rate_id: int, body: RateCorrection, request: Request):
    def action(conn):
        rates.correct_rate(operation(request, conn), code, rate_id, body.rate, body.locale)
        return _page(conn, code)
    return run(request, action)
