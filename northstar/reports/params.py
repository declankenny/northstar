"""A report's parameters: what each is, its default, the rules it must meet, and reading a request against them.

A parameter defines a report's calculation (as opposed to a filter, which restricts what it counts). There are three kinds: a date,
a choice and a whole number. A date can carry two rules: that it is not in the future, and that it is after another parameter.

The date conventions are named by what they mean, and each is a small group of parameters with the right rules:

* `as_of`: one date, the valuation date.
* `ordered_pair`: two endpoints, the second strictly after the first, each valued separately.
* `inclusive_range`: a span, the start on or before the end, both days included.

Defaults are declarative: a literal, today, or another date parameter shifted by years, months and days (a day that does not exist in
the target month becomes the month's last, so one year before 2028-02-29 is 2027-02-28). They are resolved with one `today` for the
whole request. The server never fills in an omitted parameter when it calculates: a request names every parameter, so what is
calculated is what the person saw.
"""

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta

from northstar.reports.errors import ReportDefectError, ReportDefinitionError, ReportInputError

KINDS = ("date", "choice", "integer")
_KEY = re.compile(r"^[a-z][a-z0-9_]*$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Days a definition's defaults are tried against when it is registered, so a default that fails only on some date (the end of a
# month, a leap day) is found at startup and not on a person's page. The first is far enough back that "not in the future" is easy.
_SAMPLE_TODAYS = (date(2000, 1, 1), date(2024, 2, 29), date(2025, 3, 31), date(2026, 1, 1), date(2026, 12, 31), date(2028, 2, 29))


@dataclass(frozen=True)
class Literal:
    value: object


@dataclass(frozen=True)
class Today:
    """The day the request was made, read once."""


@dataclass(frozen=True)
class Offset:
    """Another date parameter, shifted. Negative numbers go back."""
    param: str
    years: int = 0
    months: int = 0
    days: int = 0


@dataclass(frozen=True)
class NotFuture:
    """The date may not be after today."""


@dataclass(frozen=True)
class After:
    """The date must be strictly after another parameter's."""
    other: str


@dataclass(frozen=True)
class OnOrAfter:
    """The date must be on or after another parameter's."""
    other: str


@dataclass(frozen=True)
class ParamDef:
    key: str
    label: str
    kind: str
    default: Literal | Today | Offset
    choices: tuple[tuple[str, str], ...] = ()        # for a choice: (value, label) pairs
    rules: tuple = ()                                # for a date: NotFuture, After, OnOrAfter
    minimum: int | None = None                       # for a whole number
    maximum: int | None = None


def as_of(key: str = "as_at", label: str = "As at") -> tuple[ParamDef, ...]:
    """One valuation date, today by default, never in the future."""
    return (ParamDef(key, label, "date", Today(), rules=(NotFuture(),)),)


def ordered_pair(first: str = "opening", second: str = "closing", first_label: str = "Opening date",
                 second_label: str = "Closing date") -> tuple[ParamDef, ...]:
    """Two endpoints valued separately: the second is today and the first a year earlier, the second strictly after the first, and
    neither in the future."""
    return (ParamDef(first, first_label, "date", Offset(second, years=-1), rules=(NotFuture(),)),
            ParamDef(second, second_label, "date", Today(), rules=(NotFuture(), After(first))))


def inclusive_range(first: str = "start", second: str = "end", first_label: str = "Start date",
                    second_label: str = "End date") -> tuple[ParamDef, ...]:
    """A span with both days included: the start on or before the end, neither in the future."""
    return (ParamDef(first, first_label, "date", Offset(second, years=-1), rules=(NotFuture(),)),
            ParamDef(second, second_label, "date", Today(), rules=(NotFuture(), OnOrAfter(first))))


# -- the definition --

def check(report_key: str, params: tuple[ParamDef, ...]) -> None:
    """Raise ReportDefinitionError if the parameters are not sound. Run when a report is registered."""
    problems = []
    keys = [p.key for p in params]
    if len(set(keys)) != len(keys):
        problems.append("a parameter key is used twice")
    by_key = {p.key: p for p in params}
    for p in params:
        name = f"{report_key}: parameter {p.key!r}"
        if not isinstance(p.key, str) or not _KEY.match(p.key):
            problems.append(f"{name} is not a plain lowercase name")
        if not isinstance(p.label, str) or not p.label.strip():
            problems.append(f"{name} has no label")
        if p.kind not in KINDS:
            problems.append(f"{name} has the unknown kind {p.kind!r}")
            continue
        if p.kind == "choice":
            values = [value for value, _ in p.choices]
            if not p.choices:
                problems.append(f"{name} offers no choices")
            if len(set(values)) != len(values) or not all(isinstance(v, str) and v for v in values):
                problems.append(f"{name} has empty or repeated choices")
        elif p.choices:
            problems.append(f"{name} is not a choice but offers choices")
        if p.kind == "integer":
            if p.minimum is not None and p.maximum is not None and p.minimum > p.maximum:
                problems.append(f"{name} has a minimum above its maximum")
        elif p.minimum is not None or p.maximum is not None:
            problems.append(f"{name} is not a whole number but has a limit")
        if p.rules and p.kind != "date":
            problems.append(f"{name} has date rules but is not a date")
        for rule in p.rules:
            if not isinstance(rule, (NotFuture, After, OnOrAfter)):
                problems.append(f"{name} has an unknown rule")
            elif isinstance(rule, (After, OnOrAfter)):
                other = by_key.get(rule.other)
                if other is None or other.kind != "date" or other.key == p.key:
                    problems.append(f"{name} must come after {rule.other!r}, which is not another date parameter")
        default = p.default
        if isinstance(default, Today) and p.kind != "date":
            problems.append(f"{name} defaults to today but is not a date")
        elif isinstance(default, Offset):
            other = by_key.get(default.param)
            if p.kind != "date":
                problems.append(f"{name} defaults to an offset but is not a date")
            elif other is None or other.kind != "date" or other.key == p.key:
                problems.append(f"{name} defaults from {default.param!r}, which is not another date parameter")
        elif not isinstance(default, (Literal, Today, Offset)):
            problems.append(f"{name} has no default")
    if problems:
        raise ReportDefinitionError("; ".join(problems))
    cycle = _cycle(by_key)
    if cycle:
        raise ReportDefinitionError(f"{report_key}: the defaults of {', '.join(cycle)} depend on each other in a circle")
    for today in _SAMPLE_TODAYS:                    # the defaults must hold on every kind of day
        try:
            values = resolve_defaults(params, today)
            read(params, values, today)
        except (ReportDefectError, ReportInputError) as error:
            raise ReportDefinitionError(f"{report_key}: the defaults do not hold when today is {today.isoformat()}: {error}") from None


def _cycle(by_key: dict[str, ParamDef]) -> list[str]:
    """The keys of a circle of defaults that depend on each other, or none. A default depends on at most one other parameter, so
    following the chain from each parameter finds every circle."""
    for start in by_key:
        seen: list[str] = []
        key = start
        while key in by_key and isinstance(by_key[key].default, Offset):
            if key in seen:
                return seen[seen.index(key):]
            seen.append(key)
            key = by_key[key].default.param
    return []


# -- defaults --

def shift(day: date, years: int = 0, months: int = 0, days: int = 0) -> date:
    """A date moved by calendar years and months, then by days. A day the target month lacks becomes its last day."""
    index = day.year * 12 + (day.month - 1) + years * 12 + months
    year, month0 = divmod(index, 12)
    month = month0 + 1
    if not 1 <= year <= 9999:
        raise ValueError("outside the calendar")
    moved = date(year, month, min(day.day, calendar.monthrange(year, month)[1]))
    return moved + timedelta(days=days)


def resolve_defaults(params: tuple[ParamDef, ...], today: date) -> dict[str, object]:
    """Each parameter's default, as the values a request carries (dates as YYYY-MM-DD text). Uses the one `today` it is given."""
    by_key = {p.key: p for p in params}
    resolved: dict[str, object] = {}

    def value_of(key: str, trail: tuple[str, ...]) -> object:
        if key in resolved:
            return resolved[key]
        if key in trail:
            raise ReportDefectError(f"the defaults of {', '.join(trail)} depend on each other in a circle")
        default = by_key[key].default
        if isinstance(default, Literal):
            result = default.value
        elif isinstance(default, Today):
            result = today.isoformat()
        else:
            base = date.fromisoformat(str(value_of(default.param, trail + (key,))))
            try:
                result = shift(base, default.years, default.months, default.days).isoformat()
            except (ValueError, OverflowError):
                raise ReportDefectError(f"the default of parameter {key} falls outside the calendar") from None
        resolved[key] = result
        return result

    for p in params:
        value_of(p.key, ())
    return {p.key: resolved[p.key] for p in params}


# -- a request --

def _path(key: str) -> list[str]:
    return ["parameters", key]


def read(params: tuple[ParamDef, ...], data: object, today: date) -> dict[str, object]:
    """The request's `parameters` as typed values (dates as `date`), or a ReportInputError that says which one and why. Every
    parameter must be named and none may be missing or unknown; nothing is filled in. Then each date's rules are checked."""
    if not isinstance(data, dict):
        raise ReportInputError("The parameters must be an object.", ["parameters"])
    known = {p.key for p in params}
    unknown = sorted(str(key) for key in set(data) - known)
    if unknown:
        raise ReportInputError(f"This report has no parameter {unknown[0]}.", _path(unknown[0]))
    values: dict[str, object] = {}
    for p in params:
        if p.key not in data:
            raise ReportInputError(f"The {p.label.lower()} is required.", _path(p.key))
        values[p.key] = _read_one(p, data[p.key])
    labels = {p.key: p.label.lower() for p in params}
    for p in params:
        for rule in p.rules:
            value = values[p.key]
            if isinstance(rule, NotFuture) and value > today:
                raise ReportInputError(f"The {labels[p.key]} cannot be in the future.", _path(p.key))
            if isinstance(rule, After) and not value > values[rule.other]:
                raise ReportInputError(f"The {labels[p.key]} must be after the {labels[rule.other]}.", _path(p.key))
            if isinstance(rule, OnOrAfter) and value < values[rule.other]:
                raise ReportInputError(f"The {labels[p.key]} cannot be before the {labels[rule.other]}.", _path(p.key))
    return values


def _read_one(p: ParamDef, raw: object) -> object:
    label = p.label.lower()
    if p.kind == "date":
        if not isinstance(raw, str) or not _ISO_DATE.match(raw):
            raise ReportInputError(f"The {label} must be a date written YYYY-MM-DD.", _path(p.key))
        try:
            return date.fromisoformat(raw)
        except ValueError:
            raise ReportInputError(f"The {label} is not a real date.", _path(p.key)) from None
    if p.kind == "choice":
        if not isinstance(raw, str) or raw not in {value for value, _ in p.choices}:
            raise ReportInputError(f"Choose one of the offered values for the {label}.", _path(p.key))
        return raw
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ReportInputError(f"The {label} must be a whole number.", _path(p.key))
    if p.minimum is not None and raw < p.minimum:
        raise ReportInputError(f"The {label} must be {p.minimum} or more.", _path(p.key))
    if p.maximum is not None and raw > p.maximum:
        raise ReportInputError(f"The {label} must be {p.maximum} or less.", _path(p.key))
    return raw


def describe_rules(p: ParamDef) -> list[dict]:
    """A parameter's rules as public metadata, so the page can tell a strict ordering from an inclusive one and check a date before it
    asks, without knowing anything about the report. `after` is strictly after the other parameter; `on_or_after` allows the same day."""
    names = {NotFuture: "not_future", After: "after", OnOrAfter: "on_or_after"}
    return [{"rule": names[type(rule)], **({"other": rule.other} if hasattr(rule, "other") else {})} for rule in p.rules]


def serialise(params: tuple[ParamDef, ...], values: dict[str, object]) -> dict[str, object]:
    """Typed values back to what a request carries, for echoing the effective parameters."""
    return {p.key: (values[p.key].isoformat() if p.kind == "date" else values[p.key]) for p in params}
