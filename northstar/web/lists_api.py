"""The one set of endpoints every list uses. Like the other routes, they add no rules: the list engine decides what a request means,
and these only check who may ask and carry the answer.

A list is read with a POST, because the request is a nested document (filters, columns, sort) and a filter's values are household
data that should not be in an address, an access log or a proxy's log. It changes nothing. An unknown list is a 404, a list only
for admins is a 403 for anyone else, and a request that breaks a rule is a 422.
"""

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel, StrictInt

from northstar import list_prefs
from northstar.lists import loader
from northstar.lists.query import choices as filter_choices, describe, run as run_list
from northstar.lists.request import parse_request
from northstar.lists.tree import field_tree
from northstar.listdefs import catalog as household_catalog
from northstar.web.auth_routes import current_user, operation, run

router = APIRouter(prefix="/api/lists")


class ColumnOut(BaseModel):
    key: str
    label: str            # the last part: "Account type"
    path_label: str       # the whole path: "Account › Account type"
    kind: str             # text, integer, number, decimal, date, timestamp, yes_no, choice or amount
    scale: int | None     # for a decimal stored as a whole number: its decimal places (2 for hundredths); otherwise none
    linked: bool          # does this column open a page for this person?


class SortOut(BaseModel):
    field: str
    direction: str        # "asc" or "desc"


class ListPage(BaseModel):
    columns: list[ColumnOut]
    rows: list[dict[str, Any]]    # by column key, with `_id`, `_links` and, when grouped, `_group` and `_group_count`
    total: int            # every matching row, not only this page
    page: int             # the page shown (a page past the end shows the last)
    pages: int
    page_size: int
    group: str | None
    sort: SortOut         # the sort applied: the request's, or the list's own when it named none, so a page can show it


class PageSize(BaseModel):
    page_size: StrictInt         # exactly a whole number: "25" and true are refused


def _roles(user) -> frozenset[str]:
    return frozenset({"admin"}) if user["is_admin"] else frozenset()


def _definition(key: str, user):
    definition = loader.get_list_definition(key)
    if definition.admin_only and not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Only admins can see that list.")
    return definition


@router.post("/{key}", response_model=ListPage)
def query_list(key: str, request: Request, body: dict = Body(default_factory=dict)):
    user = current_user(request)
    definition = _definition(key, user)

    def action(conn):
        catalog = household_catalog(conn)
        data = dict(body)
        if "page_size" not in data:                 # the person's own choice, else the list's
            data["page_size"] = list_prefs.page_size(conn, user["id"], key, definition.page_size)
        parsed = parse_request(catalog, definition, data)
        result = run_list(conn, catalog, definition, parsed, _roles(user))
        return {"columns": describe(catalog, definition, parsed.columns, _roles(user)), "rows": result.rows,
                "total": result.total, "page": result.page, "pages": result.pages, "page_size": result.page_size,
                "group": result.group, "sort": {"field": result.sort[0], "direction": result.sort[1]}}

    return run(request, action)


@router.get("/{key}/fields")
def list_fields(key: str, request: Request) -> dict[str, Any]:
    """Every column the list can show, sort or filter by, as a tree: the list's own columns, and under each relation the columns of the
    record it points at. A relation is a column too (it shows the record's display value) and has `children` when there is more."""
    definition = _definition(key, current_user(request))
    return run(request, lambda conn: field_tree(household_catalog(conn), definition))


@router.get("/{key}/choices/{field}")
def list_choices(key: str, field: str, request: Request) -> dict[str, Any]:
    """What a person can pick from when filtering by one column: the declared values of a choice, or the records of a relation that
    the list's own rows point at (at most 500, with `more` when there were others)."""
    definition = _definition(key, current_user(request))
    return run(request, lambda conn: filter_choices(conn, household_catalog(conn), definition, field))


@router.put("/{key}/page-size", response_model=PageSize)
def set_page_size(key: str, body: PageSize, request: Request):
    _definition(key, current_user(request))
    return run(request, lambda conn: {"page_size": list_prefs.set_page_size(operation(request, conn), key, body.page_size)})
