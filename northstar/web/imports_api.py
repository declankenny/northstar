"""JSON endpoint for the admin Imports page: the register of past imports. Admin only (403 otherwise).

Like the other routes, this calls the plain functions (import_register) and adds no rules of its own.
"""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from northstar import import_register
from northstar.web.auth_routes import current_user, require_admin, run

router = APIRouter(prefix="/api/imports", dependencies=[Depends(require_admin)])


class ImportOut(BaseModel):
    id: int
    date: str                      # YYYY-MM-DD, the UTC date the import was made
    by: str
    account_id: int | None
    account_name: str | None       # as it is now
    account_deleted: bool
    account_open: bool
    file: str | None               # the base name only
    added: int
    replaced: int
    reverted_on: str | None        # the UTC date of the undo, once there is one


class ImportList(BaseModel):
    imports: list[ImportOut]
    more: bool                     # older imports than the ones listed exist
    limit: int


@router.get("", response_model=ImportList)
def list_imports(request: Request):
    return run(request, import_register.list_imports)


class UndoPlanOut(BaseModel):
    """What undoing would do, for the confirmation."""
    import_id: int
    file: str | None
    date: str
    by: str
    account_id: int | None
    account_name: str | None
    delete: int                    # balances the import added, which undo deletes
    restore: int                   # balances the import replaced, which undo puts back


class UndoOut(BaseModel):
    deleted: int
    restored: int
    after: ImportList              # the register as it is now


@router.get("/{import_id}/undo", response_model=UndoPlanOut)
def undo_plan(import_id: int, request: Request):
    """Writes nothing: what an undo would do, or why it cannot be done."""
    def action(conn):
        plan = import_register.undo_plan(conn, import_id)
        return {**{name: getattr(plan, name) for name in ("import_id", "file", "date", "by", "account_id", "account_name")},
                "delete": len(plan.delete), "restore": len(plan.restore)}
    return run(request, action)


@router.post("/{import_id}/undo", response_model=UndoOut)
def undo_import(import_id: int, request: Request):
    def action(conn):
        result = import_register.undo_import(conn, current_user(request)["id"], import_id)
        return {"deleted": result.deleted, "restored": result.restored, "after": import_register.list_imports(conn)}
    return run(request, action)
