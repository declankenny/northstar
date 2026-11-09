"""One view of a list as one parameterised statement.

Every name in the SQL comes from the registry or the database's own schema (checked as plain identifiers when the catalog is
built), and every value is a parameter. Each path of relations gets its own join, so one table reached in several roles is
joined once per role, and every join is on a primary key, so there is exactly one row for each row of the table.

The order is always: hard exclusions and scope, then search and filters, then the count, then the sort (nulls last, then the
record's id), then the page.

A computed column is worked out by a function the list's definition supplies. When a request sorts, groups or filters by one,
the values for every row the list could show are worked out first and handed to the statement as one JSON parameter that it
reads with `json_each`, so the statement still does all the sorting and filtering and nothing is written. Otherwise only the
rows of the page are worked out, after the page is fetched.
"""

import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import date

from northstar.lists.kinds import COMMON_SCALE, Computed, Reference, Text, escape_like, normalise
from northstar.lists.listdef import ListDef
from northstar.lists.registry import Catalog, Resolved
from northstar.lists.request import ListRequest


@dataclass(frozen=True)
class ListContext:
    """What a computed column may need to know that the database does not: today's date, in the installation's own zone."""

    today: date


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

    def __init__(self, conn, catalog: Catalog, definition: ListDef, request: ListRequest, context: ListContext):
        self.conn, self.catalog, self.definition, self.request, self.context = conn, catalog, definition, request, context
        self.joins = _Joins(catalog)
        self.params: list = []
        self.ctes: list[tuple[str, str]] = []              # (alias, json) for each computed column worked out in full
        self.computed_aliases: dict[str, str] = {}
        self.deferred: list[str] = []                      # computed columns worked out for the page only
        self.full: set[str] = set()                        # computed columns the request sorts, groups or filters by

    # -- what the kinds ask for --

    def plain(self, resolved: Resolved) -> str:
        """The column itself (for a relation, the display column of what it points at)."""
        return f'{self.joins.alias(resolved.path)}."{resolved.column}"'

    def alias_via(self, resolved: Resolved, keys) -> str:
        """The alias of the table a kind's own path of relations leads to, from the table the column is on."""
        return self.joins.alias((*resolved.path, *self.catalog.follow(resolved.table, keys)))

    def computed_columns(self, resolved: Resolved) -> list[str]:
        if resolved.key in self.full:
            alias = self._computed_alias(resolved)
            return [f"{alias}.value", f"{alias}.scale", f"{alias}.unit", f"{alias}.note"]
        if resolved.key not in self.deferred:
            self.deferred.append(resolved.key)
        return ["NULL", "NULL", "NULL", "NULL"]

    def computed_compare(self, resolved: Resolved) -> str:
        return f"{self._computed_alias(resolved)}.norm"

    # -- computed columns --

    def _computed_alias(self, resolved: Resolved) -> str:
        if resolved.key not in self.computed_aliases:
            alias = f"cv{len(self.computed_aliases) + 1}"
            self.computed_aliases[resolved.key] = alias
            answers = compute(self.conn, self.catalog, self.definition, self.context, resolved, None)
            rows = [[row_id, normalise(a.value, a.scale), a.value, a.scale, a.unit, a.note] for row_id, a in answers]
            self.ctes.append((alias, json.dumps(rows)))
            pk = self.catalog.primary_key[self.definition.table]
            # An inner join, because it holds an answer for every row of the source within the scope, and because the
            # planner can then look each row up by its key instead of scanning the answers for every row (minutes for 20,000).
            self.joins.sql.append(f'JOIN {alias} ON {alias}.id = b."{pk}"')
        return self.computed_aliases[resolved.key]

    def with_clause(self, wanted: list[str] | None = None) -> tuple[str, list]:
        chosen = [(alias, text) for alias, text in self.ctes if wanted is None or alias in wanted]
        if not chosen:
            return "", []
        parts = [f"{alias}(id, norm, value, scale, unit, note) AS MATERIALIZED (SELECT json_extract(j.value, '$[0]'), "
                 f"json_extract(j.value, '$[1]'), json_extract(j.value, '$[2]'), json_extract(j.value, '$[3]'), "
                 f"json_extract(j.value, '$[4]'), json_extract(j.value, '$[5]') FROM json_each(?) AS j)"
                 for alias, _ in chosen]
        return "WITH " + ", ".join(parts) + " ", [text for _, text in chosen]

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
        expressions = [f'b."{name}"' for name, field in catalog.tables[base].fields.items()
                       if field.searchable and not field.kind.virtual]
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


def compute(conn, catalog: Catalog, definition: ListDef, context: ListContext, resolved: Resolved,
            ids: list | None) -> list[tuple]:
    """Work out a computed column for the rows of the list, or for `ids` only. Returns (id, Answer) in the order asked for."""
    kind: Computed = resolved.kind
    base = definition.table
    pk = catalog.primary_key[base]
    joins = _Joins(catalog)
    columns = [f'b."{pk}" AS _id']
    for position, key in enumerate(kind.inputs):
        item = catalog.resolve(base, key)
        columns.append(f'{joins.alias(item.path)}."{item.column}" AS i{position}')       # the stored value, as it is
    where, params = [], []
    if definition.scope:
        where.append(f"({definition.scope})")
    if ids is not None:
        where.append(f"b.\"{pk}\" IN ({', '.join('?' * len(ids))})")
        params += ids
    sql = (f'SELECT {", ".join(columns)} FROM "{definition.source or base}" AS b {" ".join(joins.sql)}'
           f'{" WHERE " + " AND ".join(where) if where else ""} ORDER BY b."{pk}"')
    fetched = conn.execute(sql, params).fetchall()
    rows = [{key: record[f"i{position}"] for position, key in enumerate(kind.inputs)} for record in fetched]
    answers = kind.compute(conn, context, rows)
    if len(answers) != len(rows):
        raise RuntimeError("A computed column must answer once for every row it is given.")
    return [(record["_id"], answer) for record, answer in zip(fetched, answers)]


def run(conn: sqlite3.Connection, catalog: Catalog, definition: ListDef, request: ListRequest,
        context: ListContext) -> ListResult:
    """The page of rows the request asks for, with the count of every matching row. Rows are dicts by key, with the record's
    id as `_id`, and (when grouped) `_group` and `_group_count`, the group's size across all pages."""
    base = definition.table
    pk = catalog.primary_key[base]
    source = definition.source or base
    view = _View(conn, catalog, definition, request, context)

    # Which computed columns does the statement itself depend on? Those are worked out in full.
    touched = {condition.key for condition in request.filters}
    touched.add(request.sort_key)
    if request.group is not None:
        touched.add(request.group)
    view.full = {key for key in touched if catalog.resolve(base, key).kind.virtual}

    where = view.where()
    where_joins = list(view.joins.sql)
    where_params = list(view.params)
    where_ctes = [alias for alias, _ in view.ctes]

    selected = [f'b."{pk}" AS _id']
    shaped = []                                         # (key, kind, first position, how many) of each column in `selected`
    for key in request.columns:
        resolved = catalog.resolve(base, key)
        expressions = resolved.kind.select(view, resolved)
        shaped.append((key, resolved.kind, len(selected) - 1, len(expressions)))
        selected += [f"{expression} AS c{len(selected) - 1 + n}" for n, expression in enumerate(expressions)]
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
    count_prefix, count_cte_params = view.with_clause(where_ctes)
    count_sql = f'{count_prefix}SELECT COUNT(*) FROM "{source}" AS b {" ".join(where_joins)}{where_sql}'
    total = conn.execute(count_sql, [*count_cte_params, *where_params]).fetchone()[0]

    pages = max(1, math.ceil(total / request.page_size))
    page = min(request.page, pages)                     # a page past the end shows the last
    prefix, cte_params = view.with_clause()
    sql = (f'{prefix}SELECT {", ".join(selected)} FROM "{source}" AS b {" ".join(view.joins.sql)}{where_sql} '
           f'ORDER BY {", ".join(order)} LIMIT ? OFFSET ?')
    fetched = conn.execute(sql, [*cte_params, *view.params, request.page_size, (page - 1) * request.page_size]).fetchall()

    rows = []
    for record in fetched:
        row = {key: kind.shape([record[f"c{start + n}"] for n in range(count)]) for key, kind, start, count in shaped}
        row["_id"] = record["_id"]
        if request.group is not None:
            row["_group"], row["_group_count"] = record["_g"], record["_gn"]
        rows.append(row)

    for key in view.deferred:                           # worked out for this page only
        resolved = catalog.resolve(base, key)
        answers = dict(compute(conn, catalog, definition, context, resolved, [row["_id"] for row in rows])) if rows else {}
        for row in rows:
            answer = answers[row["_id"]]
            row[key] = resolved.kind.shape([answer.value, answer.scale, answer.unit, answer.note])
    return ListResult(rows, total, page, request.page_size, pages, request.columns, request.group)
