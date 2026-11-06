"""JSON endpoints for the Account types page. Every one needs an admin (403 otherwise).

Like the other routes, these call the plain functions in account_types.py and add no rules of
their own. Every change answers with the whole list, so the browser shows what the server now
holds. A broken rule is a 422 and an unknown type a 404.
"""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from northstar import account_types
from northstar.web.auth_routes import operation, require_admin, run

router = APIRouter(prefix="/api/types", dependencies=[Depends(require_admin)])


class TypeRow(BaseModel):
    id: int
    name: str
    class_id: int
    class_name: str
    stale_after_days: int
    account_count: int       # how many accounts use it: a type in use can't be deleted or change class
    deleted_account_count: int    # deleted accounts keep their type until they can be restored, so they hold it too


class ClassRow(BaseModel):
    id: int
    name: str


class TypeList(BaseModel):
    types: list[TypeRow]     # ordered by class, then creation
    classes: list[ClassRow]
    default_stale_after_days: int    # what the Add type form starts at: the system.balance.stale_days system property


class NewType(BaseModel):
    name: str
    class_id: int
    stale_after_days: int


class TypeChange(BaseModel):
    name: str
    stale_after_days: int
    class_id: int | None = None   # left out or unchanged means the class stays as it is


def _list(conn) -> dict:
    return {"types": [dict(row) for row in account_types.list_types(conn)],
            "classes": [dict(row) for row in account_types.list_classes(conn)],
            "default_stale_after_days": account_types.default_stale_after_days(conn)}


@router.get("", response_model=TypeList)
def list_types(request: Request):
    return run(request, _list)


@router.post("", response_model=TypeList, status_code=201)
def add_type(body: NewType, request: Request):
    def action(conn):
        account_types.add_type(operation(request, conn), body.name, body.class_id, body.stale_after_days)
        return _list(conn)
    return run(request, action)


@router.patch("/{type_id}", response_model=TypeList)
def edit_type(type_id: int, body: TypeChange, request: Request):
    def action(conn):
        account_types.update_type(operation(request, conn), type_id, body.name, body.stale_after_days, body.class_id)
        return _list(conn)
    return run(request, action)


@router.delete("/{type_id}", response_model=TypeList)
def delete_type(type_id: int, request: Request):
    def action(conn):
        account_types.delete_type(operation(request, conn), type_id)
        return _list(conn)
    return run(request, action)
