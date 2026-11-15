"""JSON endpoints for the admin Deleted balances page: the list, and restoring one. Admin only (403 otherwise), direct requests included.

Like the other routes, this calls the plain functions (deleted_balances) and adds no rules of its own.
"""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from northstar import deleted_balances
from northstar.web.auth_routes import operation, require_admin, run

router = APIRouter(prefix="/api/deleted-balances", dependencies=[Depends(require_admin)])


class CurrencyOut(BaseModel):
    code: str
    name: str
    minor_units: int


class DeletedBalanceOut(BaseModel):
    id: int
    entry_id: int                  # the log entry of the deletion shown, sent back with the restore so that a different one is refused
    account_id: int
    account_name: str
    account_open: bool
    currency: CurrencyOut
    as_of_date: str                # YYYY-MM-DD, the balance's own date
    amount_cents: int              # in the account's currency
    note: str | None
    deleted_by: str
    deleted_on: str                # YYYY-MM-DD, the UTC date it was deleted
    purge_on: str | None           # the date (in the installation's zone) of the first cleanup run after its period ends; None when the cleanup is off


class DeletedBalanceList(BaseModel):
    cleanup_on: bool
    retention_days: int
    balances: list[DeletedBalanceOut]


class RestoreIn(BaseModel):
    entry_id: int                  # the list's `entry_id` for the balance, which the restore checks is still its latest deletion


class RestoredOut(BaseModel):
    id: int
    account_id: int
    as_of_date: str


@router.get("", response_model=DeletedBalanceList)
def list_deleted(request: Request):
    return run(request, deleted_balances.list_deleted)


@router.post("/{balance_id}/restore", response_model=RestoredOut)
def restore(balance_id: int, body: RestoreIn, request: Request):
    def action(conn):
        op = operation(request, conn, "restore", {"table": "balances", "record_id": balance_id})
        return deleted_balances.restore_balance(op, balance_id, body.entry_id)
    return run(request, action)
