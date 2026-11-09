"""One view of a list as one parameterised statement.

Every name in the SQL comes from the registry or the database's own schema (checked as plain identifiers when the catalog is
built), and every value is a parameter. Each path of relations gets its own join, so one table reached in several roles is
joined once per role, and every join is on a primary key, so there is exactly one row for each row of the table.

The order is always: hard exclusions and scope, then search and filters, then the count, then the sort (nulls last, then the
record's id), then the page.
"""

import math
import sqlite3
from dataclasses import dataclass

from northstar.lists.kinds import Reference, Text, escape_like
from northstar.lists.listdef import ListDef
from northstar.lists.registry import Catalog, Resolved
from northstar.lists.request import ListRequest


@dataclass(frozen=True)
class ListResult:
    rows: list[dict]
    total: int
    page: int
    page_size: int
    pages: int
    columns: tuple[str, ...]
    group: str | None


class _Joins:
    """The joins a statement needs, one for each path of relations, created the first time something uses it."""

    def __init__(self, catalog: Catalog):
        self.catalog = catalog
        self.aliases: dict[tuple, str] = {(): "b"}
        self.sql: list[str] = []

    def alias(self, path) -> str:
        """The alias of the table at the end of `path` (the base table for an empty path), joining on the way."""
        key = ()
        for relation in path:
            parent = self.aliases[key]
            key = (*key, (relation.parent, relation.key))
            if key not in self.aliases:
                alias = f"j{len(self.aliases)}"
                self.aliases[key] = alias
                self.sql.append(f'LEFT JOIN "{relation.target}" AS {alias} ON {alias}."{relation.target_column}" = '
                                f'{parent}."{relation.column}"')
        return self.aliases[key]


class _View:
    """The pieces of the statement for one request."""

    def __init__(self, catalog: Catalog, definition: ListDef, request: ListRequest):
        self.catalog, self.definition, self.request = catalog, definition, request
        self.joins = _Joins(catalog)
        self.params: list = []

    def value(self, resolved: Resolved) -> str:
        """The expression for what the column shows (a relation shows the display value of its target)."""
        return f'{self.joins.alias(resolved.path)}."{resolved.column}"'

    def identity(self, resolved: Resolved) -> str:
        """The expression a filter compares: for a relation the id it points at, otherwise the value."""
        if resolved.relation is None:
            return self.value(resolved)
        return f'{self.joins.alias(resolved.path[:-1])}."{resolved.relation.column}"'

    def where(self) -> str:
        definition, request, catalog = self.definition, self.request, self.catalog
        parts = []
        if definition.scope:
            parts.append(f"({definition.scope})")
        if request.search:
            parts.append(self._search())
        for condition in request.filters:
            resolved = catalog.resolve(definition.table, condition.key)
            kind = Reference() if resolved.relation else resolved.kind
            sql, params = kind.where(self.identity(resolved), condition.operator, condition.value)
            parts.append(f"({sql})")
            self.params += params
        return " AND ".join(parts)

    def _search(self) -> str:
        """Match the searchable columns of the table and the display values of its relations."""
        catalog, base = self.catalog, self.definition.table
        expressions = [f'b."{name}"' for name, field in catalog.tables[base].fields.items() if field.searchable]
        for relation in catalog.relations(base).values():
            target = catalog.tables[relation.target]
            if isinstance(target.fields[target.display].kind, Text):
                expressions.append(f'{self.joins.alias((relation,))}."{target.display}"')
        if not expressions:
            return "0"                                  # nothing is searchable, so nothing matches
        pattern = f"%{escape_like(self.request.search)}%"
        self.params += [pattern] * len(expressions)
        return "(" + " OR ".join(f"{e} LIKE ? ESCAPE '\\'" for e in expressions) + ")"

    def order(self, resolved: Resolved) -> str:
        expression = self.value(resolved)
        collate = " COLLATE NOCASE" if resolved.kind.sorts_without_case else ""
        return f"({expression} IS NULL), {expression}{collate}"


def run(conn: sqlite3.Connection, catalog: Catalog, definition: ListDef, request: ListRequest) -> ListResult:
    """The page of rows the request asks for, with the count of every matching row. Rows are dicts by key, with the record's
    id as `_id`, and (when grouped) `_group` and `_group_count`, the group's size across all pages."""
    view = _View(catalog, definition, request)
    base = definition.table
    pk = catalog.primary_key[base]
    source = definition.source or base

    where = view.where()
    where_joins = list(view.joins.sql)
    where_params = list(view.params)

    selected = [f'b."{pk}" AS _id']
    resolved_columns = [catalog.resolve(base, key) for key in request.columns]
    for position, resolved in enumerate(resolved_columns):
        selected.append(f'{view.value(resolved)} AS c{position}')
    order = []
    if request.group is not None:
        group = catalog.resolve(base, request.group)
        selected.append(f'{view.value(group)} AS _g')
        selected.append(f'COUNT(*) OVER (PARTITION BY {view.value(group)}) AS _gn')
        order.append(view.order(group))
    sort = catalog.resolve(base, request.sort_key)
    order.append(f"{view.order(sort)} {request.direction.upper()}")
    order.append(f'b."{pk}" ASC')

    frm = f'FROM "{source}" AS b ' + " ".join(view.joins.sql)
    where_sql = f" WHERE {where}" if where else ""
    count_sql = f'SELECT COUNT(*) FROM "{source}" AS b {" ".join(where_joins)}{where_sql}'
    total = conn.execute(count_sql, where_params).fetchone()[0]

    pages = max(1, math.ceil(total / request.page_size))
    page = min(request.page, pages)                     # a page past the end shows the last
    sql = f'SELECT {", ".join(selected)} {frm}{where_sql} ORDER BY {", ".join(order)} LIMIT ? OFFSET ?'
    fetched = conn.execute(sql, [*view.params, request.page_size, (page - 1) * request.page_size]).fetchall()
    rows = []
    for record in fetched:
        row = {key: record[f"c{position}"] for position, key in enumerate(request.columns)}
        row["_id"] = record["_id"]
        if request.group is not None:
            row["_group"], row["_group_count"] = record["_g"], record["_gn"]
        rows.append(row)
    return ListResult(rows, total, page, request.page_size, pages, request.columns, request.group)
