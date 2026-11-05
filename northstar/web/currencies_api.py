"""JSON endpoint for the admin Currencies page. It needs an admin (403 otherwise).

Like the other routes, it calls a plain function in currencies.py and adds no rules of its own. The page is read-only: the
catalog is never edited here, and enabling a currency arrives with exchange rates.
"""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from northstar import currencies
from northstar.web.auth_routes import require_admin, run

router = APIRouter(prefix="/api/currencies", dependencies=[Depends(require_admin)])


class CurrencyRow(BaseModel):
    code: str
    name: str
    minor_units: int        # digits after the decimal point: 0, 2 or 3
    is_enabled: bool        # the stored flag, as it is
    account_count: int      # accounts in this currency, open or closed, not deleted


class CurrencyList(BaseModel):
    currencies: list[CurrencyRow]     # ordered by code


@router.get("", response_model=CurrencyList)
def list_currencies(request: Request):
    return run(request, lambda conn: {"currencies": currencies.list_with_counts(conn)})
