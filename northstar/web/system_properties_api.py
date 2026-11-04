"""JSON endpoints for the System properties page. Every one needs an admin (403 otherwise).

Like the other routes, these call the plain functions in system_properties.py and add no rules of their own. A change
answers with the whole list, so the browser shows what the server now holds. A refused value is a 422 whose message is
fit to show, and an unknown property a 404.
"""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from northstar import system_properties
from northstar.web.auth_routes import operation, require_admin, run

router = APIRouter(prefix="/api/system-properties", dependencies=[Depends(require_admin)])


class Option(BaseModel):
    value: str
    label: str


class PropertyRow(BaseModel):
    name: str                  # lowercase dotted: the first segment is the group the page lists it under
    type: str                  # String, Integer or Lookup
    value: str | None          # always text, null when unset
    allow_null: bool           # whether it may be set back to unset
    hint: str
    read_only: bool
    options: list[Option]      # the allowed values of a Lookup, else empty


class PropertyList(BaseModel):
    properties: list[PropertyRow]     # ordered by name


class NewValue(BaseModel):
    value: str | None = None          # blank or null means unset


def _list(conn) -> dict:
    return {"properties": system_properties.list_properties(conn)}


@router.get("", response_model=PropertyList)
def list_properties(request: Request):
    return run(request, _list)


@router.put("/{name}", response_model=PropertyList)
def set_property(name: str, body: NewValue, request: Request):
    def action(conn):
        system_properties.set_property(operation(request, conn), name, body.value)
        return _list(conn)
    return run(request, action)
