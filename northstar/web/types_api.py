"""JSON endpoints for the Account types page. Every one needs an admin (403 otherwise).

Like the other routes, these call the plain functions in account_types.py and add no rules of
their own. Every change answers with the whole list, so the browser shows what the server now
holds. A broken rule is a 422 and an unknown type a 404.
"""

from contextlib import closing

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from northstar import account_types, db
from northstar.errors import NotFoundError, ValidationError
from northstar.web.auth_routes import require_admin

router = APIRouter(prefix="/api/types", dependencies=[Depends(require_admin)])


class TypeRow(BaseModel):
    id: int
    name: str
    class_id: int
    class_name: str
    stale_after_days: int
    account_count: int       # how many accounts use it: a type in use can't be deleted or change class


class ClassRow(BaseModel):
    id: int
    name: str


class TypeList(BaseModel):
    types: list[TypeRow]     # ordered by class, then creation
    classes: list[ClassRow]


class NewType(BaseModel):
    name: str
    class_id: int
    stale_after_days: int


class TypeChange(BaseModel):
    name: str
    stale_after_days: int
    class_id: int | None = None   # left out or unchanged means the class stays as it is


def _run(request: Request, action):
    """Run an action on a connection, turning a broken rule into an error response."""
    with closing(db.connect(request.app.state.db_path)) as conn:
        try:
            return action(conn)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error))
        except ValidationError as error:
            raise HTTPException(status_code=422, detail=str(error))


def _list(conn) -> dict:
    return {"types": [dict(row) for row in account_types.list_types(conn)],
            "classes": [dict(row) for row in account_types.list_classes(conn)]}


@router.get("", response_model=TypeList)
def list_types(request: Request):
    return _run(request, _list)


@router.post("", response_model=TypeList, status_code=201)
def add_type(body: NewType, request: Request):
    def action(conn):
        account_types.add_type(conn, body.name, body.class_id, body.stale_after_days)
        return _list(conn)
    return _run(request, action)


@router.patch("/{type_id}", response_model=TypeList)
def edit_type(type_id: int, body: TypeChange, request: Request):
    def action(conn):
        account_types.update_type(conn, type_id, body.name, body.stale_after_days, body.class_id)
        return _list(conn)
    return _run(request, action)


@router.delete("/{type_id}", response_model=TypeList)
def delete_type(type_id: int, request: Request):
    def action(conn):
        account_types.delete_type(conn, type_id)
        return _list(conn)
    return _run(request, action)
