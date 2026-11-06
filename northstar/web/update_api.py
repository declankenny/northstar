"""JSON endpoints for the Update balances screen: the open accounts for one date, and the save.

Like the other routes, these call the plain functions in balances.py and add no rules of their own.
Reading a date writes nothing. A save is all or nothing: if any amount is bad it is a 422 whose
`errors` say which accounts, and if a balance has changed since the page loaded it is a 409 whose
`conflicts` say which, and nothing is saved.
"""


from fastapi import APIRouter, Request
from pydantic import BaseModel

from northstar import balances, clock
from northstar.web.auth_routes import operation, run

router = APIRouter(prefix="/api")


class RowCurrency(BaseModel):
    code: str
    name: str
    minor_units: int


class UpdateRow(BaseModel):
    id: int
    name: str
    currency: RowCurrency        # the account's currency: what is typed and shown on this row is in it
    class_name: str
    type_name: str
    stale_after_days: int
    last_date: str | None
    last_cents: int | None
    days_since: int | None
    stale: bool
    existing_cents: int | None   # the balance already saved on the chosen date, if any
    existing_version: int | None  # its version, which a save sends back


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
    versions: dict[int, int | None]  # for each account sent, the version of its balance on the date when loaded, or None for none
    locale: str | None = None        # the number and date format the page was using, refused if it is no longer the saved one


def _page(conn, date_text: str | None, saved: dict[str, int] | None = None) -> dict:
    today = clock.today()
    as_of = balances.parse_date(date_text, today) if date_text else today
    return {"date": as_of.isoformat(), "today": today.isoformat(),
            "rows": balances.update_rows(conn, as_of, today), "saved": saved}


@router.get("/balances/update", response_model=UpdatePage)
def read_update(request: Request, date: str | None = None):
    """The open accounts and what is saved on `date` (today when left out)."""
    return run(request, lambda conn: _page(conn, date))


@router.post("/balances/update", response_model=UpdatePage)
def save_update(body: UpdateEntries, request: Request):
    """Save one date's amounts, then answer with that date as the server now holds it."""
    def action(conn):
        counts = balances.save_update(operation(request, conn, "bulk_update", {"date": body.date}), body.date, body.amounts, clock.today(), body.versions,
                                       locale_tag=body.locale)
        return _page(conn, body.date, counts)

    return run(request, action)
