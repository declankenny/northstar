"""The sections of a report's result: what a calculation may return, and the checks that make a wrong answer impossible to show.

A report declares its sections: each has a stable key, a data `kind` with a typed shape, and a `view`, which is only the name of how
the page draws it. The contract never carries any chart configuration. The server and the TypeScript files in
`frontend/src/reports/views.ts` each list the views of every kind, and a test fails if the two lists disagree.

Kinds: `summary` (headline figures), `series` (values over dates), `hierarchy` (groups with exact amounts) and `rows` (a table).
`flows` is reserved and refused until it is designed.

Money is an integer of minor units with the currency stated once in the result, except a value in another currency, which names its
own. Every amount, and every total made from amounts, is a whole number that is not a boolean and whose size is at most
2**53 - 1, so JavaScript reads it exactly.

A hierarchy's `value` is signed financial value and stays so: a negative balance is negative. Its parents' values are supplied and
checked to equal the sum of their children, in the same unit. Area is a separate thing: in a `sized` section every leaf carries a
non-negative `size`, chosen by the report, and the framework adds each parent's size as the sum of its leaves. A view that needs size
refuses a section that has none, so it can never fall back to `value`.

A check that fails here is a fault in the report (ReportDefectError), never the person's mistake. Messages name a place, never an
amount or a name.
"""

import re
from dataclasses import dataclass
from datetime import date

from northstar.errors import NotFoundError
from northstar.lists import loader
from northstar.reports.errors import ReportDefectError, ReportDefinitionError

MAX_SAFE = 2 ** 53 - 1                              # JavaScript's Number.MAX_SAFE_INTEGER
KINDS = ("summary", "series", "hierarchy", "rows")
RESERVED = ("flows",)
# What a page can draw of each kind. frontend/src/reports/views.ts holds the same lists, and a test compares them.
VIEWS = {
    "summary": ("tiles",),
    "series": ("line",),
    "hierarchy": ("treemap", "table"),
    "rows": ("table",),
}
NEEDS_SIZE = frozenset({"treemap"})                 # views that draw by size, and so need a sized section
SUMMARY_KINDS = ("money", "date", "count", "text")
SERIES_KINDS = ("money", "count")
COLUMN_KINDS = ("text", "money", "native_money", "date", "count")
LINK_TARGETS = ("account", "balance", "list")
MAX_DEPTH = 8
GRID_COLUMNS = 12                                  # the page lays a report's sections out on this many columns
MAX_NODES = 10_000
_KEY = re.compile(r"^[a-z][a-z0-9_]*$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")


@dataclass(frozen=True)
class SectionDef:
    key: str
    kind: str
    view: str
    title: str
    sized: bool = False                             # a hierarchy only: its leaves carry a size
    unit: str = "money"                             # a hierarchy only: what its values are
    additive: bool = True                           # a hierarchy only: a parent equals the sum of its children
    columns: int = GRID_COLUMNS                     # how many of the page's 12 columns the section takes: 12 is the whole width, 6 half, 4 a third, 3 a quarter


def check(report_key: str, sections: tuple[SectionDef, ...]) -> None:
    """Raise ReportDefinitionError if the declared sections are not sound. Run when a report is registered."""
    problems = []
    if not sections:
        problems.append(f"{report_key}: a report declares at least one section")
    keys = [s.key for s in sections]
    if len(set(keys)) != len(keys):
        problems.append(f"{report_key}: a section key is used twice")
    for s in sections:
        name = f"{report_key}: section {s.key!r}"
        if not isinstance(s.key, str) or not _KEY.match(s.key):
            problems.append(f"{name} is not a plain lowercase name")
        if not isinstance(s.title, str) or not s.title.strip():
            problems.append(f"{name} has no title")
        if s.kind in RESERVED:
            problems.append(f"{name} is of the kind {s.kind!r}, which is reserved and not available yet")
            continue
        if s.kind not in KINDS:
            problems.append(f"{name} has the unknown kind {s.kind!r}")
            continue
        if isinstance(s.columns, bool) or not isinstance(s.columns, int) or not 1 <= s.columns <= GRID_COLUMNS:
            problems.append(f"{name} takes {s.columns!r} columns; a section takes a whole number from 1 to {GRID_COLUMNS}")
        if s.view not in VIEWS[s.kind]:
            problems.append(f"{name} has the view {s.view!r}, which a {s.kind} cannot be drawn as")
        if s.view in NEEDS_SIZE and not (s.kind == "hierarchy" and s.sized):
            problems.append(f"{name} is drawn as {s.view!r}, which needs a sized hierarchy")
        if s.kind != "hierarchy" and (s.sized or s.unit != "money" or not s.additive):
            problems.append(f"{name} is not a hierarchy but declares hierarchy settings")
        if s.kind == "hierarchy":
            if s.unit != "money":
                problems.append(f"{name} has the unit {s.unit!r}; only money is supported")
            if not s.additive:
                problems.append(f"{name} is not additive; only additive hierarchies are supported")
    if problems:
        raise ReportDefinitionError("; ".join(problems))


# -- values --

def _fail(where: str, what: str):
    raise ReportDefectError(f"{where}: {what}")


def whole(value: object, where: str, *, low: int | None = None) -> int:
    """A whole number that is not a boolean and that JavaScript reads exactly. `low` is the least it may be."""
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(where, "is not a whole number")
    if abs(value) > MAX_SAFE:
        _fail(where, "is larger than a browser can read exactly")
    if low is not None and value < low:
        _fail(where, f"is below {low}")
    return value


def _text(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(where, "is not text")
    return value


def _identifier(value: object, where: str) -> str:
    if not isinstance(value, str) or not _KEY.match(value):
        _fail(where, "is not a plain lowercase name")
    return value


def _iso_date(value: object, where: str) -> str:
    if not isinstance(value, str) or not _ISO_DATE.match(value):
        _fail(where, "is not a date written YYYY-MM-DD")
    try:
        date.fromisoformat(value)
    except ValueError:
        _fail(where, "is not a real date")
    return value


def _currency(value: object, where: str) -> str:
    if not isinstance(value, str) or not _CURRENCY.match(value):
        _fail(where, "is not a currency code")
    return value


def _only(data: object, allowed: set[str], where: str, required: set[str] = frozenset()) -> dict:
    if not isinstance(data, dict):
        _fail(where, "is not an object")
    extra = sorted(str(k) for k in set(data) - allowed)
    if extra:
        _fail(where, f"has the unknown field {extra[0]}")
    missing = sorted(required - set(data))
    if missing:
        _fail(where, f"lacks {missing[0]}")
    return data


def _list(value: object, where: str) -> list:
    if not isinstance(value, list):
        _fail(where, "is not a list")
    return value


def link(value: object, where: str) -> dict:
    """A symbolic drill target. The page maps it to a route. An account or balance is named by id; a list by its key, and the
    filters it opens with, whose conditions the list checks when it is opened."""
    if not isinstance(value, dict) or value.get("to") not in LINK_TARGETS:
        _fail(where, "is not a known link")
    target = value["to"]
    if target in ("account", "balance"):
        _only(value, {"to", "id"}, where, {"id"})
        return {"to": target, "id": whole(value["id"], f"{where}.id", low=1)}
    _only(value, {"to", "list", "filters"}, where, {"list"})
    key = value["list"]
    try:
        loader.get_list_definition(key)
    except NotFoundError:
        _fail(where, "names a list that does not exist")
    filters = _list(value.get("filters", []), f"{where}.filters")
    for index, condition in enumerate(filters):
        _only(condition, {"field", "operator", "value"}, f"{where}.filters[{index}]", {"field", "operator"})
    return {"to": "list", "list": key, "filters": list(filters)}


# -- the kinds --

def _summary(data: object, where: str) -> dict:
    data = _only(data, {"items"}, where, {"items"})
    items, seen = [], set()
    for index, item in enumerate(_list(data["items"], f"{where}.items")):
        at = f"{where}.items[{index}]"
        _only(item, {"key", "label", "kind", "value", "currency", "note"}, at, {"key", "label", "kind", "value"})
        key = _identifier(item["key"], f"{at}.key")
        if key in seen:
            _fail(at, "repeats a key")
        seen.add(key)
        kind = item["kind"]
        if kind not in SUMMARY_KINDS:
            _fail(at, "has an unknown kind")
        if kind != "money" and "currency" in item:
            _fail(at, "names a currency but is not money")
        out = {"key": key, "label": _text(item["label"], f"{at}.label"), "kind": kind}
        if kind == "money":
            out["value"] = whole(item["value"], f"{at}.value")
            if "currency" in item:
                out["currency"] = _currency(item["currency"], f"{at}.currency")
        elif kind == "count":
            out["value"] = whole(item["value"], f"{at}.value", low=0)
        elif kind == "date":
            out["value"] = _iso_date(item["value"], f"{at}.value")
        else:
            out["value"] = _text(item["value"], f"{at}.value")
        if "note" in item:
            out["note"] = _text(item["note"], f"{at}.note")
        items.append(out)
    return {"items": items}


def _series(data: object, where: str) -> dict:
    data = _only(data, {"series"}, where, {"series"})
    result, seen = [], set()
    for index, one in enumerate(_list(data["series"], f"{where}.series")):
        at = f"{where}.series[{index}]"
        _only(one, {"key", "label", "kind", "points"}, at, {"key", "label", "kind", "points"})
        key = _identifier(one["key"], f"{at}.key")
        if key in seen:
            _fail(at, "repeats a key")
        seen.add(key)
        if one["kind"] not in SERIES_KINDS:
            _fail(at, "has an unknown kind")
        points, last = [], None
        for number, point in enumerate(_list(one["points"], f"{at}.points")):
            here = f"{at}.points[{number}]"
            _only(point, {"x", "value"}, here, {"x", "value"})
            x = _iso_date(point["x"], f"{here}.x")
            if last is not None and x <= last:
                _fail(here, "is not after the point before it")
            last = x
            points.append({"x": x, "value": whole(point["value"], f"{here}.value", low=0 if one["kind"] == "count" else None)})
        result.append({"key": key, "label": _text(one["label"], f"{at}.label"), "kind": one["kind"], "points": points})
    return {"series": result}


def _hierarchy(section: SectionDef, data: object, where: str) -> dict:
    data = _only(data, {"nodes"}, where, {"nodes"})
    seen: set[str] = set()
    count = [0]

    def node(raw: object, depth: int, at: str) -> tuple[dict, int, int]:
        """The checked node, its value and its size (sum of its leaves' sizes; 0 in an unsized section)."""
        if depth > MAX_DEPTH:
            _fail(at, f"is deeper than {MAX_DEPTH} levels")
        count[0] += 1
        if count[0] > MAX_NODES:
            _fail(where, f"has more than {MAX_NODES} nodes")
        _only(raw, {"id", "label", "value", "size", "link", "children"}, at, {"id", "label", "value"})
        ident = raw["id"]
        if not isinstance(ident, str) or not ident.strip():
            _fail(at, "has no id")
        if ident in seen:
            _fail(at, "repeats a node id")
        seen.add(ident)
        value = whole(raw["value"], f"{at}.value")
        out = {"id": ident, "label": _text(raw["label"], f"{at}.label"), "value": value}
        children = _list(raw.get("children", []), f"{at}.children")
        size = 0
        if children:
            if "size" in raw:
                _fail(at, "is a parent with its own size; the framework sums a parent's size")
            kids, total_value = [], 0
            for number, child in enumerate(children):
                checked, child_value, child_size = node(child, depth + 1, f"{at}.children[{number}]")
                kids.append(checked)
                total_value += child_value
                size += child_size
            if total_value != value:
                _fail(at, "has a value that is not the sum of its children")
            whole(total_value, f"{at} (sum of its children)")
            out["children"] = kids
        elif section.sized:
            if "size" not in raw:
                _fail(at, "is a leaf of a sized section with no size")
            size = whole(raw["size"], f"{at}.size", low=0)
        elif "size" in raw:
            _fail(at, "has a size but its section is not sized")
        if section.sized:
            out["size"] = whole(size, f"{at} (sum of its leaves' sizes)", low=0)
        if "link" in raw:
            out["link"] = link(raw["link"], f"{at}.link")
        return out, value, size

    nodes = [node(raw, 1, f"{where}.nodes[{index}]")[0] for index, raw in enumerate(_list(data["nodes"], f"{where}.nodes"))]
    return {"nodes": nodes}


def _rows(data: object, where: str) -> dict:
    data = _only(data, {"columns", "rows"}, where, {"columns", "rows"})
    columns, keys = [], {}
    for index, column in enumerate(_list(data["columns"], f"{where}.columns")):
        at = f"{where}.columns[{index}]"
        _only(column, {"key", "label", "kind"}, at, {"key", "label", "kind"})
        key = _identifier(column["key"], f"{at}.key")
        if key in keys:
            _fail(at, "repeats a key")
        if column["kind"] not in COLUMN_KINDS:
            _fail(at, "has an unknown kind")
        keys[key] = column["kind"]
        columns.append({"key": key, "label": _text(column["label"], f"{at}.label"), "kind": column["kind"]})
    rows, seen = [], set()
    for index, row in enumerate(_list(data["rows"], f"{where}.rows")):
        at = f"{where}.rows[{index}]"
        _only(row, {"id", "cells", "link"}, at, {"id", "cells"})
        ident = row["id"]
        if not isinstance(ident, str) or not ident.strip():
            _fail(at, "has no id")
        if ident in seen:
            _fail(at, "repeats a row id")
        seen.add(ident)
        cells = _only(row["cells"], set(keys), f"{at}.cells")
        out_cells = {key: _cell(keys[key], cells.get(key), f"{at}.cells.{key}") for key in keys}
        out = {"id": ident, "cells": out_cells}
        if "link" in row:
            out["link"] = link(row["link"], f"{at}.link")
        rows.append(out)
    return {"columns": columns, "rows": rows}


def _cell(kind: str, value: object, where: str) -> object:
    if value is None:
        return None
    if kind == "text":
        return _text(value, where)
    if kind == "money":
        return whole(value, where)
    if kind == "count":
        return whole(value, where, low=0)
    if kind == "date":
        return _iso_date(value, where)
    _only(value, {"minor", "currency"}, where, {"minor", "currency"})
    return {"minor": whole(value["minor"], f"{where}.minor"), "currency": _currency(value["currency"], f"{where}.currency")}


def validate(section: SectionDef, data: object) -> dict:
    """The section's data as checked and completed (a hierarchy's parent sizes added), or a ReportDefectError."""
    where = f"section {section.key}"
    if section.kind == "summary":
        return _summary(data, where)
    if section.kind == "series":
        return _series(data, where)
    if section.kind == "hierarchy":
        return _hierarchy(section, data, where)
    return _rows(data, where)


def validate_notes(notes: object, sections: tuple[SectionDef, ...]) -> list[dict]:
    """A note is a sentence the page shows beside a section, or the whole report, that the report wants said (a leaf not drawn, say)."""
    declared = {s.key for s in sections}
    result = []
    for index, note in enumerate(_list(notes, "notes")):
        at = f"notes[{index}]"
        _only(note, {"code", "text", "section"}, at, {"code", "text"})
        out = {"code": _identifier(note["code"], f"{at}.code"), "text": _text(note["text"], f"{at}.text")}
        if "section" in note:
            if note["section"] not in declared:
                _fail(at, "names a section the report does not declare")
            out["section"] = note["section"]
        result.append(out)
    return result
