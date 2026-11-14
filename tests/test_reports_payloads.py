"""The named payload types of each section kind agree with what the runtime validators accept, so the annotations cannot drift from the
checks. Synthetic data only."""

import typing

from northstar.reports import payloads, sections
from northstar.reports.sections import SectionDef

TREE = SectionDef("h", "hierarchy", "treemap", "H", sized=True)


def fields(typed_dict) -> set[str]:
    return set(typing.get_type_hints(typed_dict))


def test_every_section_kind_has_a_payload_type_and_nothing_else_does():
    assert set(payloads.PAYLOADS) == set(sections.KINDS)


def test_the_payload_fields_are_the_fields_the_validators_accept():
    """A payload that uses every field the type names is accepted, and the checked copy has exactly those fields."""
    link = {"to": "list", "list": "balances", "filters": [{"field": "a", "operator": "is", "value": 1}]}
    node = {"id": "n", "label": "N", "value": 1, "link": link, "note": "A note", "opening": 5, "closing": 6, "colour": {"kind": "account_type", "id": 3},
            "children": [{"id": "c", "label": "C", "value": 1, "size": 1, "opening": 5, "closing": 6}]}
    checked = sections.validate(TREE, {"nodes": [node]})["nodes"][0]
    assert set(checked) == fields(payloads.HierarchyNode) and set(checked["children"][0]) == fields(payloads.HierarchyNode) - {"link", "children", "note", "colour"}
    assert set(sections.link({"to": "account", "id": 1}, "x")) == fields(payloads.EntityLink)
    assert set(sections.link(link, "x")) == fields(payloads.ListLink)

    item = {"key": "m", "label": "M", "kind": "money", "value": 1, "currency": "EUR", "note": "n", "signed": True}
    assert set(sections.validate(SectionDef("s", "summary", "tiles", "S"), {"items": [item]})["items"][0]) == fields(payloads.SummaryItem)

    whole = sections.validate(SectionDef("c", "hierarchy", "table", "C", sized=True), {"nodes": [node], "opening": 100, "closing": 101})
    assert set(whole) == fields(payloads.HierarchyData)

    line = {"key": "a", "label": "A", "kind": "money", "points": [{"x": "2026-01-01", "value": 1}]}
    checked = sections.validate(SectionDef("t", "series", "line", "T"), {"series": [line]})["series"][0]
    assert set(checked) == fields(payloads.SeriesLine) and set(checked["points"][0]) == fields(payloads.SeriesPoint)

    rows = {"columns": [{"key": "n", "label": "N", "kind": "text"}], "rows": [{"id": "r", "cells": {"n": "a"}, "link": {"to": "account", "id": 1}}]}
    checked = sections.validate(SectionDef("r", "rows", "table", "R"), rows)
    assert set(checked) == fields(payloads.RowsData) and set(checked["columns"][0]) == fields(payloads.Column)
    assert set(checked["rows"][0]) == fields(payloads.Row)


def test_the_note_type_names_what_a_note_may_carry():
    assert set(sections.validate_notes([{"code": "x", "text": "t", "section": "h"}], (TREE,))[0]) == fields(payloads.Note)
