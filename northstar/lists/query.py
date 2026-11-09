"""One view of a list as one parameterised statement.

Every name in the SQL comes from the registry or the database's own schema (checked as plain identifiers when the catalog is
built), and every value is a parameter. Each path of relations gets its own join, so one table reached in several roles is
joined once per role, and every join is on a primary key, so there is exactly one row for each row of the table.

The order is always: hard exclusions and scope, then search and filters, then the count, then the sort (nulls last, then the
record's id), then the page.

A column that has to be worked out is a column of a view the list reads from, so sorting, grouping and filtering by it are the
database's own work like any other.
"""

import math
import sqlite3
from dataclasses import dataclass
from urllib.parse import quote

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

    # -- what the kinds ask for --

    def plain(self, resolved: Resolved) -> str:
        """The column itself (for a relation, the display column of what it points at)."""
        return f'{self.joins.alias(resolved.path)}."{resolved.column}"'

    def alias_via(self, resolved: Resolved, keys) -> str:
        """The alias of the table a kind's own path of relations leads to, from the table the column is on."""
        return self.joins.alias((*resolved.path, *self.catalog.follow(resolved.table, keys)))

    # -- the statement --

    def where(self) -> str:
        definition, request, catalog = self.definition, self.request, self.catalog
        parts = []
        if definition.scope:
            parts.append(f"({definition.scope})")
        if request.search:
            parts.append(self._search())
        for condition in request.filters:
            resolved = catalog.resolve(definition.table, condition.key)
            if resolved.relation:                       # a relation is filtered by the id it points at
                sql, params = Reference().where(self.identity(resolved), condition.operator, condition.value)
            else:
                sql, params = resolved.kind.where(resolved.kind.compare(self, resolved), condition.operator, condition.value)
            parts.append(f"({sql})")
            self.params += params
        return " AND ".join(parts)

    def identity(self, resolved: Resolved) -> str:
        """The expression a relation is filtered by: the id it points at."""
        return f'{self.joins.alias(resolved.path[:-1])}."{resolved.relation.column}"'

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
        expression = resolved.kind.compare(self, resolved)
        collate = " COLLATE NOCASE" if resolved.kind.sorts_without_case else ""
        return f"({expression} IS NULL), {expression}{collate}"


def link_pattern(catalog: Catalog, base: str, resolved: Resolved, viewer) -> str | None:
    """The route pattern a column opens, if it opens one this viewer may use. A relation opens the record page of the table it
    points at, and the display column of the list's own table opens that table's page. `viewer` is the set of roles the person
    has, and a page that is for a role only opens for one who has it."""
    if resolved.relation is not None:
        table = catalog.tables[resolved.relation.target]
    elif not resolved.path and resolved.column == catalog.tables[base].display:
        table = catalog.tables[base]
    else:
        return None
    if not table.record_page or (table.record_page_for and table.record_page_for not in viewer):
        return None
    return table.record_page


def describe(catalog: Catalog, definition: ListDef, keys, viewer=frozenset()) -> list[dict]:
    """What a page needs to draw the columns: the key, a label (and the full path of labels), the kind's code and whether the
    column opens a record page for this viewer."""
    described = []
    for key in keys:
        resolved = catalog.resolve(definition.table, key)
        described.append({"key": key, "label": resolved.labels[-1], "path_label": resolved.label, "kind": resolved.kind.code,
                          "linked": link_pattern(catalog, definition.table, resolved, viewer) is not None})
    return described


def _href(pattern: str, record_id, value) -> str | None:
    if ("{id}" in pattern and record_id is None) or ("{value}" in pattern and value is None):
        return None                                     # nothing to open: the relation is empty
    return pattern.replace("{id}", str(record_id)).replace("{value}", quote(str(value), safe=""))


def run(conn: sqlite3.Connection, catalog: Catalog, definition: ListDef, request: ListRequest,
        viewer=frozenset()) -> ListResult:
    """The page of rows the request asks for, with the count of every matching row. Rows are dicts by key, with the record's
    id as `_id`, `_links` (the route each linked column opens, for this viewer) and, when grouped, `_group` and `_group_count`,
    the group's size across all pages."""
    base = definition.table
    pk = catalog.primary_key[base]
    source = definition.source or base
    view = _View(catalog, definition, request)

    where = view.where()
    where_joins = list(view.joins.sql)
    where_params = list(view.params)

    selected = [f'b."{pk}" AS _id']
    shaped = []                                         # (key, kind, first position, how many) of each column in `selected`
    linked = []                                         # (key, pattern, position of the id selected for it, or None for the row's own)
    for key in request.columns:
        resolved = catalog.resolve(base, key)
        expressions = resolved.kind.select(view, resolved)
        shaped.append((key, resolved.kind, len(selected) - 1, len(expressions)))
        selected += [f"{expression} AS c{len(selected) - 1 + n}" for n, expression in enumerate(expressions)]
        pattern = link_pattern(catalog, base, resolved, viewer)
        if pattern is not None:
            if resolved.relation is not None:
                linked.append((key, pattern, len(selected)))
                selected.append(f"{view.identity(resolved)} AS l{len(selected)}")
            else:
                linked.append((key, pattern, None))
    order = []
    if request.group is not None:
        group = catalog.resolve(base, request.group)
        expression = group.kind.compare(view, group)
        selected.append(f"{expression} AS _g")
        selected.append(f"COUNT(*) OVER (PARTITION BY {expression}) AS _gn")
        order.append(view.order(group))
    sort = catalog.resolve(base, request.sort_key)
    order.append(f"{view.order(sort)} {request.direction.upper()}")
    order.append(f'b."{pk}" ASC')

    where_sql = f" WHERE {where}" if where else ""
    count_sql = f'SELECT COUNT(*) FROM "{source}" AS b {" ".join(where_joins)}{where_sql}'
    total = conn.execute(count_sql, where_params).fetchone()[0]

    pages = max(1, math.ceil(total / request.page_size))
    page = min(request.page, pages)                     # a page past the end shows the last
    sql = (f'SELECT {", ".join(selected)} FROM "{source}" AS b {" ".join(view.joins.sql)}{where_sql} '
           f'ORDER BY {", ".join(order)} LIMIT ? OFFSET ?')
    fetched = conn.execute(sql, [*view.params, request.page_size, (page - 1) * request.page_size]).fetchall()

    rows = []
    for record in fetched:
        row = {key: kind.shape([record[f"c{start + n}"] for n in range(count)]) for key, kind, start, count in shaped}
        row["_id"] = record["_id"]
        row["_links"] = {}
        for key, pattern, position in linked:
            href = _href(pattern, record["_id"] if position is None else record[f"l{position}"], row[key])
            if href is not None:
                row["_links"][key] = href
        if request.group is not None:
            row["_group"], row["_group_count"] = record["_g"], record["_gn"]
        rows.append(row)
    return ListResult(rows, total, page, request.page_size, pages, request.columns, request.group)
