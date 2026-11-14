"""A list's definition: only data. Which table its rows are of, where it reads them from, and its defaults."""

import re
from dataclasses import dataclass

from northstar.errors import ValidationError
from northstar.lists.registry import Catalog, RegistryError

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PAGE_SIZES = (10, 25, 50, 100)


@dataclass(frozen=True)
class ListDef:
    key: str
    table: str                                      # the registry table the rows are of
    columns: tuple[str, ...]                        # the default columns, in order
    sort: tuple[str, str]                           # the default sort: a key and "asc" or "desc"
    source: str | None = None                       # a view over the table that applies the hard exclusions
    scope: str | None = None                        # a fixed condition on the table (alias `b`), written in code
    page_size: int = 25
    admin_only: bool = False                        # only a viewer with the role "admin" may see the list
    customisable: bool = True                       # False: a fixed view. No filters, search, grouping, columns, page size or export, and nothing saved
    params: tuple[str, ...] = ()                    # what a request must name for the scope, written `:name` in it (a key of PARAM_TABLES)


# A parameter of a list is the id of a record of one of these tables, which a request names and the server checks exists.
PARAM_TABLES = {"account": "live_accounts", "balance": "live_balances"}
_PARAM = re.compile(r":([a-z_]+)")


def check(catalog: Catalog, definition: ListDef) -> None:
    """Raise RegistryError if the definition names anything the registry does not offer. Run when a list is registered."""
    problems = []
    if definition.table not in catalog.tables:
        raise RegistryError(f"{definition.key}: {definition.table} has no entry")
    for name in (definition.source,):
        if name is not None and not _IDENTIFIER.match(name):
            problems.append(f"{definition.key}: {name} is not a plain name")
    if definition.customisable and definition.page_size not in PAGE_SIZES:
        problems.append(f"{definition.key}: the page size {definition.page_size} is not one of {PAGE_SIZES}")
    if not definition.customisable and definition.page_size < 1:
        problems.append(f"{definition.key}: the page size must be at least 1")
    for name in definition.params:
        if name not in PARAM_TABLES:
            problems.append(f"{definition.key}: {name} is not a parameter a list can take")
    if set(_PARAM.findall(definition.scope or "")) != set(definition.params):
        problems.append(f"{definition.key}: the scope names {sorted(set(_PARAM.findall(definition.scope or '')))} and the list declares {sorted(definition.params)}")
    if definition.sort[1] not in ("asc", "desc"):
        problems.append(f"{definition.key}: the sort direction must be asc or desc")
    if not definition.columns:
        problems.append(f"{definition.key}: no default columns")
    for key in (*definition.columns, definition.sort[0]):
        try:
            catalog.resolve(definition.table, key)
        except ValidationError as error:
            problems.append(f"{definition.key}: {error}")
    if problems:
        raise RegistryError("; ".join(problems))
