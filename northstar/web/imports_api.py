"""JSON endpoint for the admin Imports page: the register of past imports. Admin only (403 otherwise).

Like the other routes, this calls the plain functions (import_register) and adds no rules of its own.
"""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from northstar import import_register
from northstar.web.auth_routes import require_admin, run

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
