"""JSON endpoints for the admin Deleted accounts page: the list, and restoring one. Admin only (403 otherwise), direct requests included.

Like the other routes, this calls the plain functions (deleted_accounts) and adds no rules of its own.
"""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from northstar import deleted_accounts
from northstar.web.auth_routes import operation, require_admin, run

router = APIRouter(prefix="/api/deleted-accounts", dependencies=[Depends(require_admin)])


class DeletedAccountOut(BaseModel):
    id: int
    name: str
    type_name: str
    is_open: bool                  # as it was; restoring does not change it
    deleted_on: str                # YYYY-MM-DD, the UTC date it was deleted
    purge_on: str | None           # the UTC date the cleanup is due to remove it for good; None when the cleanup is switched off
    balance_count: int             # the balances its deletion hid, which come back with it
    name_taken: bool               # a live account has its name now, so a new one is needed


class DeletedAccountList(BaseModel):
    cleanup_on: bool
    retention_days: int
    accounts: list[DeletedAccountOut]


class RestoreIn(BaseModel):
    name: str | None = None        # a new name, when the old one is in use


class RestoredOut(BaseModel):
    id: int
    name: str
    balance_count: int


@router.get("", response_model=DeletedAccountList)
def list_deleted(request: Request):
    return run(request, deleted_accounts.list_deleted)


@router.post("/{account_id}/restore", response_model=RestoredOut)
def restore(account_id: int, body: RestoreIn, request: Request):
    def action(conn):
        op = operation(request, conn, "restore", {"table": "accounts", "record_id": account_id})
        return deleted_accounts.restore_account(op, account_id, body.name)
    return run(request, action)
