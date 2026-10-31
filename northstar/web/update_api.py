"""JSON endpoints for the Update balances screen: the open accounts for one date, and the save.

Like the other routes, these call the plain functions in balances.py and add no rules of their own.
Reading a date writes nothing. A save is all or nothing: if any amount is bad it is a 422 whose
`errors` say which accounts, and nothing is saved.
"""

from contextlib import closing

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from northstar import balances, clock, db
from northstar.errors import ValidationError

router = APIRouter(prefix="/api")


class UpdateRow(BaseModel):
    id: int
    name: str
    class_name: str
    type_name: str
    stale_after_days: int
    last_date: str | None
    last_cents: int | None
    days_since: int | None
    stale: bool
    existing_cents: int | None   # the balance already saved on the chosen date, if any


class SavedCounts(BaseModel):
    added: int
    updated: int
    unchanged: int


class UpdatePage(BaseModel):
    date: str                    # YYYY-MM-DD, a calendar date with no timezone
    today: str                   # the server's today(), so the browser never needs its own clock
    rows: list[UpdateRow]        # open accounts, grouped by class, then type, then name
    saved: SavedCounts | None = None


class UpdateEntries(BaseModel):
    date: str
    amounts: dict[int, str | None]   # account id to typed text; blank is skipped


def _page(conn, date_text: str | None, saved: dict[str, int] | None = None) -> dict:
    today = clock.today()
    as_of = balances.parse_date(date_text, today) if date_text else today
    return {"date": as_of.isoformat(), "today": today.isoformat(),
            "rows": balances.update_rows(conn, as_of, today), "saved": saved}


@router.get("/balances/update", response_model=UpdatePage)
def read_update(request: Request, date: str | None = None):
    """The open accounts and what is saved on `date` (today when left out)."""
    with closing(db.connect(request.app.state.db_path)) as conn:
        try:
            return _page(conn, date)
        except ValidationError as error:
            raise HTTPException(status_code=422, detail=str(error))


@router.post("/balances/update", response_model=UpdatePage)
def save_update(body: UpdateEntries, request: Request):
    """Save one date's amounts, then answer with that date as the server now holds it."""
    with closing(db.connect(request.app.state.db_path)) as conn:
        try:
            counts = balances.save_update(conn, body.date, body.amounts, clock.today())
            return _page(conn, body.date, counts)
        except balances.EntryErrors as error:
            return JSONResponse({"detail": str(error), "errors": error.by_account}, status_code=422)
        except ValidationError as error:
            raise HTTPException(status_code=422, detail=str(error))
