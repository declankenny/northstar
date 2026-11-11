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
from northstar.reports.population import Population
from northstar.reports.sections import SectionDef

POPULATIONS = ("accounts",)
_KEY = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class FilterDecl:
    """What a report will let a person filter by: a named set of fields (its `preset`) and the conditions it opens with. Declared here
    so the place is fixed; the engine enforces it with the filter capabilities, and until then refuses any filter."""
    preset: str
    defaults: tuple = ()


@dataclass(frozen=True)
class ReportContext:
    """Everything a calculation may use, and nothing else. It never sees a request's raw filters or who is signed in beyond `user`."""
    conn: sqlite3.Connection        # one consistent read: nothing may be written through it
    user: Any                       # the signed-in person (id, is_admin), for a rule that depends on who asks
    today: date                     # read once for the request
    parameters: dict[str, Any]      # typed: dates are `date`, choices text, whole numbers `int`
    population: Population
    currency: Currency              # the system currency, which every figure is in


@dataclass(frozen=True)
class ReportResult:
    """What a calculation returns: the data of each declared section by key, and any notes the report wants said."""
    sections: dict[str, Any]
    notes: list = field(default_factory=list)


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
    if definition.filters is not None and (not isinstance(definition.filters, FilterDecl) or not definition.filters.preset):
        problems.append(f"{definition.key}: the filters declaration needs a preset")
    if problems:
        raise ReportDefinitionError("; ".join(problems))
    params_module.check(definition.key, definition.params)
    sections_module.check(definition.key, definition.sections)
