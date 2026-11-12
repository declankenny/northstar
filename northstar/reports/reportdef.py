"""A report's definition: its identity, parameters, declared sections and calculation. Code, not only data, because a report computes."""

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

from northstar.currencies import Currency
from northstar.reports import params as params_module, sections as sections_module
from northstar.reports.errors import ReportDefinitionError
from northstar.reports.params import ParamDef
from northstar.reports.payloads import Note, SectionPayload
from northstar.reports.population import Population
from northstar.reports.sections import SectionDef

POPULATIONS = ("accounts",)
_KEY = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class FilterDecl:
    """How a report may be filtered. A report with no declaration cannot be filtered. With one, it can be filtered by everything the
    registry offers from its population except what it excludes: `exclude_dates` (every date or timestamp, on any path, including
    those of related records) and `exclude` (field keys, on whole path segments: "type" excludes "type" and everything beneath it,
    "type.name" only that field). `defaults` are the conditions the report opens with, as they are sent: {"field", "operator",
    "value"}. They are checked against the registry, and so are the exclusions, whenever the report is used (see filters.py)."""
    exclude_dates: bool = False
    exclude: tuple[str, ...] = ()
    defaults: tuple = ()


@dataclass(frozen=True)
class ReportContext:
    """Everything a calculation may use, and nothing else. It never sees a request's raw filters, and it does not see who is signed in:
    who may see which account is decided once, when the population is built, so a report has no authorization logic of its own."""
    conn: sqlite3.Connection        # one consistent read: nothing may be written through it
    today: date                     # read once for the request
    parameters: dict[str, Any]      # typed: dates are `date`, choices text, whole numbers `int`
    population: Population          # the accounts to count: authorized and filtered by the framework
    currency: Currency              # the system currency, which every figure is in (read inside the same snapshot)


@dataclass(frozen=True)
class ReportResult:
    """What a calculation returns: the data of each declared section by key, and any notes the report wants said."""
    sections: dict[str, SectionPayload]
    notes: list[Note] = field(default_factory=list)


@dataclass(frozen=True)
class ReportDef:
    key: str
    title: str
    description: str
    params: tuple[ParamDef, ...]
    sections: tuple[SectionDef, ...]
    calculate: Callable[[ReportContext], ReportResult]
    population: str = "accounts"
    admin_only: bool = False
    filters: FilterDecl | None = None


def check(definition: ReportDef) -> None:
    """Raise ReportDefinitionError if the definition is not sound. Run when a report is registered, so the application does not start
    with a report that could only fail on a person's page."""
    problems = []
    if not isinstance(definition.key, str) or not _KEY.match(definition.key):
        problems.append(f"{definition.key!r} is not a plain lowercase report key")
    if not isinstance(definition.title, str) or not definition.title.strip():
        problems.append(f"{definition.key}: no title")
    if not isinstance(definition.description, str) or not definition.description.strip():
        problems.append(f"{definition.key}: no description")
    if definition.population not in POPULATIONS:
        problems.append(f"{definition.key}: the population {definition.population!r} is not one a report can count")
    if not callable(definition.calculate):
        problems.append(f"{definition.key}: no calculation")
    declared = definition.filters
    if declared is not None:
        if not isinstance(declared, FilterDecl):
            problems.append(f"{definition.key}: the filters declaration is not a FilterDecl")
        else:
            # Only the shape is checked here. What the exclusions and defaults mean needs the registry, which needs the database, so
            # that is checked whenever the report is used (filters.prepare) and by a test over every registered report.
            if not isinstance(declared.exclude_dates, bool):
                problems.append(f"{definition.key}: exclude_dates is yes or no")
            if not isinstance(declared.exclude, tuple) or not all(isinstance(key, str) and key for key in declared.exclude):
                problems.append(f"{definition.key}: the exclusions are a tuple of field keys")
            if not isinstance(declared.defaults, tuple) or not all(isinstance(item, dict) for item in declared.defaults):
                problems.append(f"{definition.key}: the default filters are a tuple of conditions")
    if problems:
        raise ReportDefinitionError("; ".join(problems))
    params_module.check(definition.key, definition.params)
    sections_module.check(definition.key, definition.sections)
