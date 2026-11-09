"""The registry: what may be offered from each table, and how a key such as `room.building.manager` is followed.

One entry per table (not per list). A table's relations are read from the database's foreign keys, so nothing about a
relation is written twice. Only what the schema cannot say is declared: the display column, the columns that may be offered
and their kinds, which are searchable, whether people may walk into the table, and what is never offered.

A key is a path of relation names ending in a column or a relation: `title`, `assignee` (the display value of the person it
points at), `site.area.lead.name`. A relation's name is its foreign key column without `_id`, so one table reached in several
roles (`assignee_id`, `reviewer_id`) has a separate name, label and join for each.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from northstar.errors import ValidationError
from northstar.lists.kinds import Kind

MAX_DEPTH = 6                       # relations followed from the base table; a safety limit, not a design target
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class RegistryError(RuntimeError):
    """The registry disagrees with the database: a mistake in the code, found when the catalog is built."""


@dataclass(frozen=True)
class FieldDef:
    kind: Kind
    searchable: bool = False
    label: str | None = None


@dataclass(frozen=True)
class TableDef:
    name: str
    display: str                                    # the column a relation to this table shows
    fields: Mapping[str, FieldDef]                  # the columns that may be offered, and no others
    tell_apart: str | None = None                   # what the picker adds when two display values are the same
    walkable: bool = True                           # may a person expand into this table's other columns?
    denied: frozenset[str] = frozenset()            # never offered, searched, filtered or exported
    labels: Mapping[str, str] = field(default_factory=dict)      # relation name -> label, where the default is wrong
    record_page: str | None = None                  # the route of the table's own page, if it has one
    based_on: str | None = None                     # for a view: the table it has one row for each row of


@dataclass(frozen=True)
class Relation:
    key: str                                        # the foreign key column without `_id`: `assignee`
    parent: str
    column: str
    target: str
    target_column: str
    nullable: bool


@dataclass(frozen=True)
class Resolved:
    """What a key means for a list that starts at `base`."""

    key: str
    path: tuple[Relation, ...]                      # the relations walked to reach the value
    table: str                                      # the table the column is on (the last table of the path)
    column: str                                     # the column read
    kind: Kind
    relation: Relation | None                       # set when the key is a relation: its display value
    labels: tuple[str, ...]

    @property
    def label(self) -> str:
        return " › ".join(self.labels)


def humanize(name: str) -> str:
    text = name.replace("_", " ").strip()
    return text[:1].upper() + text[1:]


class Catalog:
    """The registry read against a database: tables with their primary keys and relations."""

    def __init__(self, conn, tables: Mapping[str, TableDef], excluded=()):
        """`excluded` names tables that are deliberately not offered: a foreign key to one is not a relation a person can follow.
        A foreign key to any other table without an entry is a mistake, found here."""
        self.tables = dict(tables)
        self.excluded = frozenset(excluded)
        self.primary_key: dict[str, str] = {}
        self.columns: dict[str, set[str]] = {}
        self.owners: dict[str, str] = {}              # the table whose keys an entry uses: itself, or the one a view is based on
        self._relations: dict[str, dict[str, Relation]] = {}
        problems: list[str] = []
        columns_of: dict[str, dict] = {}
        for name, table in self.tables.items():
            if not _IDENTIFIER.match(name):
                problems.append(f"{name}: not a plain table name")
                continue
            columns = conn.execute(f'PRAGMA table_info("{name}")').fetchall()
            if not columns:
                problems.append(f"{name}: there is no such table or view")
                continue
            owner = table.based_on or name          # a view takes its key and its relations from the table it is based on
            if table.based_on is not None and not _IDENTIFIER.match(owner):
                problems.append(f"{name}: not a plain table name")
                continue
            keys = [c["name"] for c in conn.execute(f'PRAGMA table_info("{owner}")').fetchall() if c["pk"]]
            if len(keys) != 1:
                problems.append(f"{owner}: needs a single-column primary key")
                continue
            if table.based_on is not None and keys[0] not in {c["name"] for c in columns}:
                problems.append(f"{name}: the view does not have {owner}'s key {keys[0]}")
                continue
            self.primary_key[name] = keys[0]
            self.owners[name] = owner
            columns_of[name] = {c["name"]: c for c in columns}
            self.columns[name] = set(columns_of[name])
            problems += self._check_table(table, self.columns[name])
        for name, columns in columns_of.items():                   # once every primary key is known
            self._relations[name] = self._read_relations(conn, name, columns)
        for name, relations in self._relations.items():
            for relation in relations.values():
                if relation.target not in self.tables:
                    problems.append(f"{name}.{relation.column} points at {relation.target}, which has no entry")
        for name in columns_of:
            problems += self._check_kinds(self.tables[name])
        if problems:
            raise RegistryError("; ".join(problems))

    def _check_kinds(self, table: TableDef) -> list[str]:
        """The paths and inputs a kind names must lead somewhere."""
        problems = []
        for name, definition in table.fields.items():
            kind = definition.kind
            for path in (getattr(kind, "scale_from", None), getattr(kind, "unit_from", None)):
                if path:
                    try:
                        end = self.follow(table.name, path[:-1])
                        last = end[-1].target if end else table.name
                        if path[-1] not in self.columns.get(last, ()):
                            problems.append(f"{table.name}.{name}: {last} has no column {path[-1]}")
                    except ValidationError as error:
                        problems.append(f"{table.name}.{name}: {error}")
        return problems

    def follow(self, table: str, keys) -> tuple[Relation, ...]:
        """The relations a path of names leads through, from `table`. Not limited by depth: a kind's own paths are code."""
        path, current = [], table
        for key in keys:
            relation = self.relations(current).get(key)
            if relation is None:
                raise ValidationError(f"{current} has no relation {key}.")
            path.append(relation)
            current = relation.target
        return tuple(path)

    def _check_table(self, table: TableDef, names: set[str]) -> list[str]:
        problems = []
        for column in (*table.fields, *table.denied):
            if not _IDENTIFIER.match(column) or column not in names:
                problems.append(f"{table.name}.{column}: there is no such column")
        for column in table.denied & set(table.fields):
            problems.append(f"{table.name}.{column} is both offered and denied")
        if table.display not in table.fields:
            problems.append(f"{table.name}: the display column {table.display} is not offered")
        if table.tell_apart is not None and table.tell_apart not in table.fields:
            problems.append(f"{table.name}: the tell-apart column {table.tell_apart} is not offered")
        return problems

    def _read_relations(self, conn, table: str, columns: dict) -> dict[str, Relation]:
        owner = self.owners[table]
        owner_columns = {c["name"]: c for c in conn.execute(f'PRAGMA table_info("{owner}")').fetchall()}
        rows = conn.execute(f'PRAGMA foreign_key_list("{owner}")').fetchall()
        by_id: dict[int, list] = {}
        for row in rows:
            by_id.setdefault(row["id"], []).append(row)
        relations: dict[str, Relation] = {}
        for parts in by_id.values():
            if len(parts) != 1:                     # a composite key is not a many-to-one a person can follow
                continue
            row = parts[0]
            column, target = row["from"], row["table"]
            if column not in columns:               # a view that leaves a column out leaves its relation out
                continue
            if column in self.tables[table].denied or not _IDENTIFIER.match(column) or not _IDENTIFIER.match(target):
                continue
            if target in self.excluded:
                continue
            if target in self.primary_key and (row["to"] or self.primary_key[target]) != self.primary_key[target]:
                continue                            # only a key to the primary key is sure to give one row, not several
            key = column[:-3] if column.endswith("_id") and len(column) > 3 else column
            if key in self.tables[table].fields or key in relations:
                raise RegistryError(f"{table}: the relation {key} clashes with another column or relation")
            relations[key] = Relation(key, table, column, target, self.primary_key.get(target, ""),
                                      not owner_columns[column]["notnull"])
        return relations

    def relations(self, table: str) -> dict[str, Relation]:
        return self._relations.get(table, {})

    def resolve(self, base: str, key: str) -> Resolved:
        """What `key` means for a list starting at table `base`, or a ValidationError if it means nothing allowed."""
        if not isinstance(key, str) or not key or len(key) > 200:
            raise ValidationError("That column does not exist.")
        parts = key.split(".")
        current, seen = base, {base}
        path: list[Relation] = []
        labels: list[str] = []
        for part in parts[:-1]:
            relation = self.relations(current).get(part)
            if relation is None:
                raise ValidationError(f"“{key}” is not a column of this list.")
            self._step(current, relation, key, seen, len(path) + 1, walking=True)
            path.append(relation)
            labels.append(self._label(current, relation))
            current = relation.target
        last = parts[-1]
        relation = self.relations(current).get(last)
        if relation is not None:                    # the display value of the record the relation points at
            self._step(current, relation, key, seen, len(path) + 1, walking=False)
            target = self.tables[relation.target]
            return Resolved(key, (*path, relation), relation.target, target.display, target.fields[target.display].kind,
                            relation, (*labels, self._label(current, relation)))
        definition = self.tables[current].fields.get(last)
        if definition is None:
            raise ValidationError(f"“{key}” is not a column of this list.")
        return Resolved(key, tuple(path), current, last, definition.kind, None,
                        (*labels, definition.label or humanize(last)))

    def _step(self, current: str, relation: Relation, key: str, seen: set, depth: int, *, walking: bool) -> None:
        if depth > MAX_DEPTH:
            raise ValidationError(f"“{key}” goes more than {MAX_DEPTH} levels deep.")
        if relation.target in seen:
            raise ValidationError(f"“{key}” comes back to a table it has already passed through.")
        if walking and not self.tables[relation.target].walkable:
            raise ValidationError(f"“{key}” goes into a table that only shows its name.")
        seen.add(relation.target)

    def _label(self, table: str, relation: Relation) -> str:
        return self.tables[table].labels.get(relation.key) or humanize(relation.key)
