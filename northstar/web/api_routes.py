"""JSON endpoints for the React frontend: the net worth series, which only reads.

Like the page routes, these call the plain functions and add no rules of their own.
"""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from northstar import clock, networth
from northstar.web.auth_routes import run

router = APIRouter(prefix="/api")


class NetWorthPoint(BaseModel):
    date: str            # YYYY-MM-DD, a calendar date with no timezone
    assets: int          # integer minor units of the system currency
    liabilities: int
    net_worth: int


class Limited(BaseModel):
    starts_on: str | None    # where the series begins: the first date from which every later date can be converted; None if none can
    currencies: list[str]    # the currencies that have no rate before then


class NetWorthSeries(BaseModel):
    today: str           # the server's today(), so the browser never needs its own clock
    start: str           # the dates actually used (start is never before the first balance)
    end: str
    period: str
    series: list[NetWorthPoint]
    limited: Limited | None    # set when dates were left out because a currency has no rate for them


@router.get("/networth", response_model=NetWorthSeries)
def net_worth_series(request: Request, start: date | None = None, end: date | None = None,
                     period: Literal["day", "week", "month"] = "month", account_id: int | None = None):
    today = clock.today()
    result = run(request, lambda conn: networth.net_worth_series(conn, today, start, end, period, account_id))
    return {"today": today.isoformat(), **result}
