"""The one set of endpoints every list uses. Like the other routes, they add no rules: the list engine decides what a request means,
and these only check who may ask and carry the answer.

A list is read with a POST, because the request is a nested document (filters, columns, sort) and a filter's values are household
data that should not be in an address, an access log or a proxy's log. It changes nothing. An unknown list is a 404, a list only
for admins is a 403 for anyone else, and a request that breaks a rule is a 422.
"""

import json
import re
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, StrictInt

from northstar import clock, db, list_filters, list_prefs
from northstar.lists import export as list_export, loader
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
    groupable: bool       # may the list be grouped by it? An amount may not: the same number in two currencies would be one group


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
    filters: list[dict[str, Any]]    # the conditions applied: the request's, or the default filter's when it named none
    skipped: list[SkippedOut]        # conditions of the default filter that no longer fit the list and were left out
    default_filter_id: int | None    # the saved filter the list opened with, if the request named none
    default_columns: list[str]       # the keys of the columns the list shows when a person has chosen none
    customised: bool                 # are the columns shown this person's own saved choice (so there is something to reset)
    skipped_columns: list[SkippedOut]    # columns of the person's choice that the list no longer offers and were left out
    customisable: bool       # false for a fixed list: no filters, search, grouping, columns, page size or export


class SkippedOut(BaseModel):
    field: str | None
    reason: str


class SavedFilter(BaseModel):
    id: int
    name: str
    shared: bool                   # for everyone who can see the list; only an admin changes it
    is_default: bool               # opened with the list: this person's own, or the shared one
    can_edit: bool                 # may this person rename it, replace it, make it the default or remove it
    conditions: list[dict[str, Any]]
    problems: list[SkippedOut]     # conditions that no longer fit the list: they are skipped when it is applied


class SavedFilters(BaseModel):
    filters: list[SavedFilter]     # the shared ones and this person's own, by name
    default_id: int | None         # the one a list opens with for this person


class NewFilter(BaseModel):
    name: str
    conditions: list[dict[str, Any]]
    shared: bool = False


class FilterChange(BaseModel):
    name: str | None = None
    conditions: list[dict[str, Any]] | None = None
    is_default: bool | None = None


class PageSize(BaseModel):
    page_size: StrictInt         # exactly a whole number: "25" and true are refused


class ColumnChoice(BaseModel):
    columns: list[str] | None    # the keys in the order to show them; null forgets the choice, so the list's own columns apply


class ColumnsSaved(BaseModel):
    columns: list[str]
    customised: bool


def _roles(user) -> frozenset[str]:
    return frozenset({"admin"}) if user["is_admin"] else frozenset()


def _definition(key: str, user, *, customised: bool = True):
    """The list, if this person may see it. `customised` is for the endpoints that keep or use a person's own choices: a fixed list has
    none, so they refuse it."""
    definition = loader.get_list_definition(key)
    if definition.admin_only and not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Only admins can see that list.")
    if customised and not definition.customisable:
        raise HTTPException(status_code=422, detail="That list cannot be changed.")
    return definition


def _with_choices(conn, catalog, definition, user, key, data) -> tuple[list, int | None, list, bool]:
    """Put the person's own choices into a request that names none, in `data`: their saved columns, and their default filter (or the
    shared one). A request that names columns or filters, even an empty list of filters, gets exactly those. It says what it did: the
    conditions and columns that no longer fit the list and were left out, the filter it opened with, and whether the columns are the person's."""
    skipped, opened_with, skipped_columns, customised = [], None, [], False
    if "columns" not in data:                       # no columns named: the person's own choice, else the list's
        stored = list_prefs.saved_columns(conn, user["id"], key)
        if stored is not None:
            kept, skipped_columns = list_prefs.usable_columns(catalog, definition, stored)
            if kept:
                data["columns"], customised = kept, True
    if "filters" not in data:                       # no filter named: the person's default, else the shared one. An empty list is "none"
        opened_with = list_filters.default_id(conn, user["id"], key)
        if opened_with is not None:
            data["filters"], skipped = list_filters.usable(catalog, definition, list_filters.get(conn, user["id"], key, opened_with)["conditions"])
    return skipped, opened_with, skipped_columns, customised


@router.post("/{key}", response_model=ListPage)
def query_list(key: str, request: Request, body: dict = Body(default_factory=dict)):
    user = current_user(request)
    definition = _definition(key, user, customised=False)

    def action(conn):
        catalog = household_catalog(conn)
        data = dict(body)
        if definition.customisable:                 # a fixed list reads and keeps nothing of a person's own
            if "page_size" not in data:             # the person's own choice, else the list's
                data["page_size"] = list_prefs.page_size(conn, user["id"], key, definition.page_size)
            skipped, opened_with, skipped_columns, customised = _with_choices(conn, catalog, definition, user, key, data)
        else:
            skipped, opened_with, skipped_columns, customised = [], None, [], False
        parsed = parse_request(catalog, definition, data)
        result = run_list(conn, catalog, definition, parsed, _roles(user))
        return {"columns": describe(catalog, definition, parsed.columns, _roles(user)), "rows": result.rows,
                "total": result.total, "page": result.page, "pages": result.pages, "page_size": result.page_size,
                "group": result.group, "sort": {"field": result.sort[0], "direction": result.sort[1]},
                "filters": data.get("filters", []), "skipped": skipped, "default_filter_id": opened_with,
                "default_columns": list(definition.columns), "customised": customised, "skipped_columns": skipped_columns,
                "customisable": definition.customisable}

    return run(request, action)


def _saved(conn, catalog, definition, user) -> dict:
    rows = []
    for row in list_filters.visible(conn, user["id"], definition.key):
        kept, skipped = list_filters.usable(catalog, definition, row["conditions"])
        rows.append({"id": row["id"], "name": row["name"], "shared": row["owner_id"] is None, "is_default": bool(row["is_default"]),
                     "can_edit": row["owner_id"] is not None or bool(user["is_admin"]), "conditions": json.loads(row["conditions"]),
                     "problems": skipped})
    return {"filters": rows, "default_id": list_filters.default_id(conn, user["id"], definition.key)}


@router.get("/{key}/filters", response_model=SavedFilters)
def saved_filters(key: str, request: Request):
    """The saved filters of a list this person can see: the shared ones and their own."""
    user = current_user(request)
    definition = _definition(key, user)
    return run(request, lambda conn: _saved(conn, household_catalog(conn), definition, user))


@router.post("/{key}/filters", response_model=SavedFilters, status_code=201)
def save_filter(key: str, body: NewFilter, request: Request):
    """Save a filter, private or (for an admin) shared. Answers with the saved filters as they now are."""
    user = current_user(request)
    definition = _definition(key, user)

    def action(conn):
        catalog = household_catalog(conn)
        list_filters.create(operation(request, conn), catalog, definition, body.name, body.conditions, shared=body.shared,
                            is_admin=bool(user["is_admin"]))
        return _saved(conn, catalog, definition, user)

    return run(request, action)


@router.put("/{key}/filters/{filter_id}", response_model=SavedFilters)
def change_filter(key: str, filter_id: int, body: FilterChange, request: Request):
    """Rename a filter, replace its conditions, or make it the default (only what the request names changes)."""
    user = current_user(request)
    definition = _definition(key, user)
    given = body.model_dump(exclude_unset=True)

    def action(conn):
        catalog = household_catalog(conn)
        list_filters.update(operation(request, conn), catalog, definition, filter_id, is_admin=bool(user["is_admin"]), **given)
        return _saved(conn, catalog, definition, user)

    return run(request, action)


@router.delete("/{key}/filters/{filter_id}", response_model=SavedFilters)
def remove_filter(key: str, filter_id: int, request: Request):
    user = current_user(request)
    definition = _definition(key, user)

    def action(conn):
        list_filters.delete(operation(request, conn), definition, filter_id, is_admin=bool(user["is_admin"]))
        return _saved(conn, household_catalog(conn), definition, user)

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


@router.put("/{key}/columns", response_model=ColumnsSaved)
def set_columns(key: str, body: ColumnChoice, request: Request):
    """Save this person's columns for the list, in the order given, or forget them with null. Answers with the columns now in force."""
    definition = _definition(key, current_user(request))

    def action(conn):
        columns = list_prefs.set_columns(operation(request, conn), household_catalog(conn), definition, body.columns)
        return {"columns": columns, "customised": body.columns is not None}

    return run(request, action)


@router.post("/{key}/export")
def export_list(key: str, request: Request, body: dict = Body(default_factory=dict)):
    """The view as a CSV file: every row it matches, in its order, with its columns, however many pages that is. The request is the same
    as the list's, and a page and a page size are ignored. It names the person's own columns and default filter when it names none, so the
    file is the list as they see it, and it changes nothing they have saved. It is a POST so that a filter's values are in neither the
    address nor a log. A request that breaks a rule is refused before the file starts."""
    user = current_user(request)
    definition = _definition(key, user)

    def validate(conn):
        catalog = household_catalog(conn)
        data = {name: value for name, value in body.items() if name not in ("page", "page_size")}
        _with_choices(conn, catalog, definition, user, key, data)
        return parse_request(catalog, definition, data)

    parsed = run(request, validate)
    roles = _roles(user)
    path = request.app.state.db_path

    def file():
        conn = db.connect(path)             # its own connection, open for as long as the file takes to send
        try:
            yield from list_export.stream(conn, household_catalog(conn), definition, parsed, roles)
        finally:
            conn.close()

    name = f"northstar-{re.sub(r'[^A-Za-z0-9]+', '-', key).strip('-')}-{clock.today().isoformat()}.csv"
    return StreamingResponse(file(), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})
