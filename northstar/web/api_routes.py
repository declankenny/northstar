"""JSON endpoints for the React frontend: the net worth series, which only reads.

Like the page routes, these call the plain functions and add no rules of their own.
"""

from contextlib import closing
from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from northstar import clock, db, networth
from northstar.errors import NotFoundError, ValidationError

router = APIRouter(prefix="/api")


class NetWorthPoint(BaseModel):
    date: str            # YYYY-MM-DD, a calendar date with no timezone
    assets: int          # integer cents
    liabilities: int
    net_worth: int


class NetWorthSeries(BaseModel):
    today: str           # the server's today(), so the browser never needs its own clock
    start: str           # the dates actually used (start is never before the first balance)
    end: str
    period: str
    series: list[NetWorthPoint]


@router.get("/networth", response_model=NetWorthSeries)
def net_worth_series(request: Request, start: date | None = None, end: date | None = None,
                     period: Literal["day", "week", "month"] = "month", account_id: int | None = None):
    today = clock.today()
    with closing(db.connect(request.app.state.db_path)) as conn:
        try:
            result = networth.net_worth_series(conn, today, start, end, period, account_id)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error))
        except ValidationError as error:
            raise HTTPException(status_code=422, detail=str(error))
    return {"today": today.isoformat(), **result}
