"""Four small reports that exist only in tests, each exercising a distinct capability of the framework, so the contracts are proved on shapes
that are not a real report. Synthetic data only: every figure is made up from account ids."""

from northstar.reports import loader, params
from northstar.reports.params import ParamDef, Literal
from northstar.reports.reportdef import ReportDef, ReportResult
from northstar.reports.sections import SectionDef


def _value(account_id: int) -> int:
    """An account's made-up value: positive for odd ids and negative for even ones, so a negative balance is always in play."""
    return account_id * 100 if account_id % 2 else -account_id * 10


def _as_of(ctx) -> ReportResult:
    """One date; a summary and a sized hierarchy in two groups. A negative value gets size 0 and a note, as a real report would."""
    groups = {"odd": [], "even": []}
    for account_id in ctx.population.account_ids():
        value = _value(account_id)
        groups["odd" if account_id % 2 else "even"].append(
            {"id": f"account_{account_id}", "label": f"Account {account_id}", "value": value, "size": max(value, 0),
             "link": {"to": "account", "id": account_id}})
    nodes = [{"id": f"group_{name}", "label": name.title(), "value": sum(n["value"] for n in kids), "children": kids}
             for name, kids in groups.items() if kids]
    total = sum(n["value"] for n in nodes)
    notes = [{"code": "not_drawn", "text": "Accounts with a negative value are not drawn.", "section": "composition"}] if any(
        _value(i) < 0 for i in ctx.population.account_ids()) else []
    return ReportResult({"headline": {"items": [{"key": "total", "label": "Total", "kind": "money", "value": total},
                                                {"key": "as_at", "label": "As at", "kind": "date", "value": ctx.parameters["as_at"].isoformat()}]},
                         "composition": {"nodes": nodes}}, notes)


def _pair(ctx) -> ReportResult:
    rows = [{"id": f"account_{i}", "cells": {"name": f"Account {i}", "opening": _value(i), "closing": _value(i) + 50,
                                             "native": {"minor": 1234, "currency": "EUR"}}, "link": {"to": "account", "id": i}}
            for i in ctx.population.account_ids()]
    return ReportResult({"detail": {"columns": [{"key": "name", "label": "Account", "kind": "text"},
                                                {"key": "opening", "label": "Opening", "kind": "money"},
                                                {"key": "closing", "label": "Closing", "kind": "money"},
                                                {"key": "native", "label": "Native", "kind": "native_money"}], "rows": rows}})


def _none(ctx) -> ReportResult:
    ids = ctx.population.account_ids()
    return ReportResult({"counts": {"items": [{"key": "accounts", "label": "Accounts", "kind": "count", "value": len(ids)}]},
                         "listing": {"columns": [{"key": "name", "label": "Account", "kind": "text"}],
                                     "rows": [{"id": f"account_{i}", "cells": {"name": f"Account {i}"}} for i in ids]}})


def _range(ctx) -> ReportResult:
    start, end = ctx.parameters["start"], ctx.parameters["end"]
    step = 1 if ctx.parameters["interval"] == "month" else 7
    return ReportResult({"trend": {"series": [
        {"key": "total", "label": "Total", "kind": "money",
         "points": [{"x": start.isoformat(), "value": 1000 * step}, {"x": end.isoformat(), "value": 2000 * step}]}]}})


AS_OF = ReportDef(
    "synthetic_as_of", "Synthetic as-of", "An as-of date with a summary and a sized hierarchy.", params.as_of(),
    (SectionDef("headline", "summary", "tiles", "Headline"),
     SectionDef("composition", "hierarchy", "treemap", "Composition", sized=True)), _as_of)
PAIR = ReportDef(
    "synthetic_pair", "Synthetic pair", "An ordered pair of dates with a table.", params.ordered_pair(),
    (SectionDef("detail", "rows", "table", "Detail"),), _pair)
NONE = ReportDef(
    "synthetic_none", "Synthetic none", "No parameters, a summary and a table.", (),
    (SectionDef("counts", "summary", "tiles", "Counts"), SectionDef("listing", "rows", "table", "Listing")), _none, admin_only=True)
RANGE = ReportDef(
    "synthetic_range", "Synthetic range", "An inclusive range and a choice, with a series.",
    params.inclusive_range() + (ParamDef("interval", "Interval", "choice", Literal("month"), choices=(("month", "Month"), ("week", "Week"))),),
    (SectionDef("trend", "series", "line", "Trend"),), _range)

ALL = (AS_OF, PAIR, NONE, RANGE)


def register_all() -> None:
    for definition in ALL:
        loader.register(definition)


def unregister_all() -> None:
    for definition in ALL:
        loader._DEFINITIONS.pop(definition.key, None)
