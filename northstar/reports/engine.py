"""Describing a report and calculating one: the two things a request asks, checked at every step.

`describe` is what the page needs before it can ask anything: the parameters with their defaults resolved (by the server, with its own
`today`, so the page never reads the browser's clock), the sections and how each is drawn. Nothing about the calculation, the
population or any query.

`calculate` reads the request, builds the calculation's context on one consistent read, runs the calculation, checks what it returned
and packages it. The request must name every parameter: nothing is defaulted here. A request that breaks a rule is a
ReportInputError, a household whose data cannot answer yet is ReportUnavailable, and anything wrong with the report itself is a
ReportDefectError, which is logged and never becomes a partial result.
"""

import logging
import sqlite3
from datetime import date

from northstar import currencies, db
from northstar.networth import NoRate
from northstar.reports import filters as filters_module, params as params_module, sections as sections_module
from northstar.reports.errors import ReportDefectError, ReportInputError, ReportUnavailable
from northstar.reports.population import visible_accounts
from northstar.reports.reportdef import ReportContext, ReportDef, ReportResult

log = logging.getLogger(__name__)


def describe(definition: ReportDef, today: date, conn: sqlite3.Connection | None = None) -> dict:
    """The report's public metadata, with defaults resolved for `today` and checked against the rules. A default that does not hold
    on this day is a fault in the report. A report that can be filtered needs `conn`, because what it may be filtered by comes from the
    registry, and a fault in its exclusions or opening conditions is a fault in the report."""
    if definition.filters is not None and conn is None:
        raise ValueError("Describing a report that can be filtered needs the database.")
    defaults = params_module.resolve_defaults(definition.params, today)
    try:
        params_module.read(definition.params, defaults, today)
    except ReportInputError as error:
        raise ReportDefectError(f"report {definition.key}: its defaults do not hold today: {error}") from None
    return {
        "key": definition.key, "title": definition.title, "description": definition.description,
        "today": today.isoformat(),
        "parameters": [
            {"key": p.key, "label": p.label, "kind": p.kind, "default": defaults[p.key],
             "choices": [{"value": value, "label": label} for value, label in p.choices],
             "minimum": p.minimum, "maximum": p.maximum, "rules": params_module.describe_rules(p)}
            for p in definition.params],
        "sections": [{"key": s.key, "kind": s.kind, "view": s.view, "title": s.title, "sized": s.sized, "columns": s.columns, "expanded": s.expanded} for s in definition.sections],
        "filters": {"enabled": False} if definition.filters is None else filters_module.prepare(conn, definition).describe(),
    }


def _read_request(definition: ReportDef, data: object, today: date) -> tuple[dict, object]:
    """The parameters, typed, and the filters as sent (None when the request names none). What the filters mean needs the registry,
    so it is read where the report's filter rules are."""
    if not isinstance(data, dict):
        raise ReportInputError("The request must be an object.", [])
    unknown = sorted(str(key) for key in set(data) - {"parameters", "filters"})
    if unknown:
        raise ReportInputError(f"Unknown request field: {unknown[0]}.", [unknown[0]])
    if "parameters" not in data:
        raise ReportInputError("The request must name the parameters.", ["parameters"])
    filters = None                                  # not named: the report's own. Only a missing key means that; `null` is not a list
    if "filters" in data:
        filters = data["filters"]
        if not isinstance(filters, list):
            raise ReportInputError("The filters must be a list.", ["filters"])
    if filters and definition.filters is None:
        raise ReportInputError("This report cannot be filtered.", ["filters"])      # never applied and never dropped
    return params_module.read(definition.params, data["parameters"], today), filters


def calculate(conn: sqlite3.Connection, definition: ReportDef, user, data: object, today: date) -> dict:
    """The report for this request, as the answer the page shows: the effective parameters and filters, the currency, every declared
    section checked, and the notes. `today` is read once by the caller."""
    values, sent = _read_request(definition, data, today)
    with db.read_transaction(conn):                # everything read from the database below shares this one snapshot
        rules = filters_module.prepare(conn, definition)          # checked here whichever endpoint is asked first
        if rules is None:
            conditions, applied = (), []
        elif sent is None:                                         # no filters named: the report's own. An empty list is "none"
            conditions, applied = rules.opening()
        else:
            conditions, applied = rules.read(sent)
        system = currencies.system_currency(conn)
        if system is None:
            raise ReportUnavailable("An administrator has not chosen the system currency yet, so reports cannot be worked out.",
                                    "no_system_currency")
        population = visible_accounts(conn, user)                   # who may see which account, then only the ones that match
        if rules is not None:
            population = rules.narrow(conn, population, conditions)
        context = ReportContext(conn, today, values, population, system)
        try:
            result = definition.calculate(context)
        except NoRate as error:
            raise ReportUnavailable(str(error), "missing_rates", **error.details) from None
        except (ReportInputError, ReportUnavailable, ReportDefectError):
            raise
        except Exception as error:
            raise ReportDefectError(f"report {definition.key}: the calculation raised {type(error).__name__}") from error
    return _package(definition, values, applied, system, result, today)


def _package(definition: ReportDef, values: dict, applied: list, system, result: object, today: date) -> dict:
    if not isinstance(result, ReportResult):
        raise ReportDefectError(f"report {definition.key}: the calculation did not return a ReportResult")
    declared = {s.key: s for s in definition.sections}
    returned = result.sections if isinstance(result.sections, dict) else {}
    if not isinstance(result.sections, dict):
        raise ReportDefectError(f"report {definition.key}: the sections are not a mapping")
    missing = sorted(set(declared) - set(returned))
    if missing:
        raise ReportDefectError(f"report {definition.key}: the section {missing[0]} was declared and not returned")
    extra = sorted(str(key) for key in set(returned) - set(declared))
    if extra:
        raise ReportDefectError(f"report {definition.key}: the section {extra[0]} was returned and not declared")
    sections = {key: sections_module.validate(declared[key], returned[key]) for key in (s.key for s in definition.sections)}
    return {
        "report": definition.key,
        "today": today.isoformat(),
        "parameters": params_module.serialise(definition.params, values),
        "filters": applied,
        "currency": {"code": system.code, "minor_units": system.minor_units},
        "sections": sections,
        "notes": sections_module.validate_notes(result.notes, definition.sections),
    }


def choices(conn: sqlite3.Connection, definition: ReportDef, user, field: object) -> dict:
    """What can be picked when filtering the report by `field`: the declared values, or the records the accounts this person may see
    point at. The report's filter rules decide whether the field is offered, as they do for a request."""
    with db.read_transaction(conn):
        rules = filters_module.prepare(conn, definition)
        if rules is None:
            raise ReportInputError("This report cannot be filtered.", ["field"])
        return rules.choices(conn, field, visible_accounts(conn, user))
