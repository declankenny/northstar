"""A report's filters: what it may be filtered by, checked, and the narrowing of its population.

A report filters by everything the registry offers from its population, except what it explicitly excludes. It declares no list of
allowed fields: the registry already decides what may be offered at all (a column is offered only when it is added there, and a
denied column is never reachable), so a report only adds restrictions and never new access. The consequence is a rule: a field or
relation added to the registry is available to every report that does not exclude it. Two things can be excluded: dates (by kind, on
any path, so a date column added later is excluded without anyone remembering) and named fields (on whole path segments:
excluding `type` excludes `type` and everything beneath it, excluding `type.name` leaves the type's other fields).

Everything here is checked when the definition is used, on every endpoint that uses it: an exclusion that names nothing the
registry offers, or a default filter that the rules refuse, is a fault in the report and never a restriction that quietly stops
applying.

Filtering only narrows. The framework builds the population the person is authorized to see, and this keeps the accounts of it that
match: a calculation is handed a `Population` and never a filter.
"""

import dataclasses
import sqlite3
from dataclasses import dataclass

from northstar.errors import ValidationError
from northstar.listdefs import catalog as household_catalog
from northstar.lists.kinds import Date
from northstar.lists.query import field_choices, matching_ids
from northstar.lists.registry import Catalog
from northstar.lists.request import Condition, ConditionProblem, parse_conditions
from northstar.lists.tree import field_tree_for
from northstar.reports.errors import ReportDefectError, ReportInputError
from northstar.reports.population import FixedPopulation, Population

# What a report's population is made of, in the registry: the table whose fields and relations a filter may use, and the view the
# rows are read from, which leaves out what is deleted.
POPULATION_SOURCES = {"accounts": ("accounts", "live_accounts")}


def catalog_for(conn: sqlite3.Connection) -> Catalog:
    """The registry read against this database."""
    return household_catalog(conn)


def _wire(item: dict) -> dict:
    """A condition as it is sent and shown: a field, an operator and, when there is one, a value."""
    return {name: item[name] for name in ("field", "operator", "value") if name in item}


@dataclass(frozen=True)
class ReportFilters:
    report: str
    catalog: Catalog
    table: str
    source: str
    exclude_dates: bool
    exclude: tuple[tuple[str, ...], ...]               # whole path segments
    defaults: tuple[dict, ...] = ()                    # the opening conditions, as declared
    default_conditions: tuple[Condition, ...] = ()     # and as read

    def refusal(self, key: str) -> str | None:
        """Why this key may not be used to filter the report, or None. It looks at every step of the path, so a field is refused when
        anything it is reached through is."""
        parts = key.split(".")
        if any(parts[:len(excluded)] == list(excluded) for excluded in self.exclude):
            return f"“{self.catalog.resolve(self.table, key).label}” is not available as a filter for this report."
        if self.exclude_dates:
            for end in range(1, len(parts) + 1):
                resolved = self.catalog.resolve(self.table, ".".join(parts[:end]))
                if isinstance(resolved.kind, Date):                    # a timestamp is a date
                    return f"“{resolved.label}” is a date, and this report cannot be filtered by dates."
        return None

    def read(self, raw) -> tuple[tuple[Condition, ...], list[dict]]:
        """The conditions of a request and what to say was applied, or a ReportInputError that says which condition and which part of it."""
        try:
            conditions = parse_conditions(self.catalog, self.table, raw, self.refusal)
        except ConditionProblem as problem:
            raise ReportInputError(str(problem), ["filters", problem.index, *([problem.part] if problem.part else [])]) from None
        except ValidationError as problem:
            raise ReportInputError(str(problem), ["filters"]) from None
        return conditions, [_wire(item) for item in raw]

    def opening(self) -> tuple[tuple[Condition, ...], list[dict]]:
        """What a request that names no filters means: the report's own opening conditions."""
        return self.default_conditions, [_wire(item) for item in self.defaults]

    def narrow(self, conn: sqlite3.Connection, population: Population, conditions: tuple[Condition, ...]) -> Population:
        """The accounts of the population that meet every condition. Never more than the population was."""
        if not conditions:
            return population
        return FixedPopulation(matching_ids(conn, self.catalog, self.table, self.source, conditions, within=population.account_ids()))

    def describe(self) -> dict:
        """What the page needs to offer filters: the fields (as a list's are, so the same drawer takes them) and the opening conditions.
        Nothing about the population or how it is found."""
        return {"enabled": True, "fields": field_tree_for(self.catalog, self.table, self.refusal), "defaults": [_wire(item) for item in self.defaults]}

    def choices(self, conn: sqlite3.Connection, field: object, population: Population) -> dict:
        """What can be picked when filtering by `field`, drawn from the accounts the person may see and not from every record."""
        try:
            if not isinstance(field, str):
                raise ValidationError("That field does not exist.")
            self.catalog.resolve(self.table, field)
            if why := self.refusal(field):
                raise ValidationError(why)
            return field_choices(conn, self.catalog, self.table, self.source, field, within=population.account_ids())
        except ValidationError as problem:
            raise ReportInputError(str(problem), ["field"]) from None


def prepare(conn: sqlite3.Connection, definition) -> ReportFilters | None:
    """The report's filter rules, checked against the registry, or None when the report cannot be filtered. Every endpoint that uses a
    report's filters comes through here, so a fault in the declaration is found whichever one is asked first. A fault is a
    ReportDefectError: the person did nothing wrong."""
    declared = definition.filters
    if declared is None:
        return None
    table, source = POPULATION_SOURCES[definition.population]
    catalog = catalog_for(conn)
    unknown, exclude = [], []
    for key in declared.exclude:
        try:
            catalog.resolve(table, key)
        except ValidationError:
            unknown.append(key)
            continue
        exclude.append(tuple(key.split(".")))
    if unknown:
        raise ReportDefectError(f"report {definition.key}: it excludes {', '.join(map(repr, unknown))}, which the registry does not offer from {table}")
    rules = ReportFilters(definition.key, catalog, table, source, declared.exclude_dates, tuple(exclude))
    try:
        conditions = parse_conditions(catalog, table, list(declared.defaults), rules.refusal)
    except ValidationError as problem:
        raise ReportDefectError(f"report {definition.key}: its default filters do not hold: {problem}") from None
    return dataclasses.replace(rules, defaults=tuple(declared.defaults), default_conditions=conditions)
