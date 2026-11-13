"""The sections of a result: what is accepted, and every way a calculation can return something that must never be shown. Synthetic data only."""

import copy

import pytest

from northstar.reports import sections
from northstar.reports.errors import ReportDefectError, ReportDefinitionError
from northstar.reports.sections import MAX_SAFE, SectionDef

SUMMARY = SectionDef("s", "summary", "tiles", "S")
SERIES = SectionDef("t", "series", "line", "T")
TREE = SectionDef("h", "hierarchy", "treemap", "H", sized=True)
UNSIZED = SectionDef("h", "hierarchy", "table", "H")
ROWS = SectionDef("r", "rows", "table", "R")


def leaf(ident, value, size=None, **extra):
    node = {"id": ident, "label": ident.title(), "value": value, **extra}
    if size is not None:
        node["size"] = size
    return node


def tree():
    return {"nodes": [
        {"id": "a", "label": "A", "value": 300, "children": [leaf("a1", 500, 500), leaf("a2", -200, 0)]},
        {"id": "b", "label": "B", "value": 40, "children": [leaf("b1", 40, 40)]},
        leaf("c", 7, 7)]}


# -- the declaration --

def test_a_view_must_be_one_the_kind_can_be_drawn_as():
    with pytest.raises(ReportDefinitionError, match="cannot be drawn"):
        sections.check("r", (SectionDef("s", "summary", "treemap", "S"),))


def test_a_view_that_needs_size_needs_a_sized_hierarchy():
    with pytest.raises(ReportDefinitionError, match="needs a sized hierarchy"):
        sections.check("r", (SectionDef("h", "hierarchy", "treemap", "H"),))
    sections.check("r", (TREE,))
    sections.check("r", (UNSIZED,))                       # a table needs no size


def test_only_additive_money_hierarchies_are_supported_and_flows_is_reserved():
    for bad in (SectionDef("h", "hierarchy", "table", "H", additive=False), SectionDef("h", "hierarchy", "table", "H", unit="percent"),
                SectionDef("f", "flows", "sankey", "F"), SectionDef("s", "summary", "tiles", "S", sized=True),
                SectionDef("x", "pie", "pie", "X")):
        with pytest.raises(ReportDefinitionError):
            sections.check("r", (bad,))


def test_a_report_declares_sections_once_each_with_plain_keys_and_titles():
    for bad in ((), (SUMMARY, SUMMARY), (SectionDef("S", "summary", "tiles", "S"),), (SectionDef("s", "summary", "tiles", " "),)):
        with pytest.raises(ReportDefinitionError):
            sections.check("r", bad)


# -- money --

@pytest.mark.parametrize("value", [True, False, 1.0, "5", None, MAX_SAFE + 1, -MAX_SAFE - 1])
def test_money_is_a_whole_number_that_is_not_a_boolean_and_that_a_browser_reads_exactly(value):
    data = {"items": [{"key": "a", "label": "A", "kind": "money", "value": value}]}
    with pytest.raises(ReportDefectError):
        sections.validate(SUMMARY, data)


def test_the_largest_exact_value_is_accepted_in_both_directions():
    for value in (MAX_SAFE, -MAX_SAFE, 0):
        data = {"items": [{"key": "a", "label": "A", "kind": "money", "value": value}]}
        assert sections.validate(SUMMARY, data)["items"][0]["value"] == value


def test_a_total_made_from_amounts_is_held_to_the_same_bound_as_each_amount():
    each = MAX_SAFE // 2 + 1                              # each fits, their sum does not
    data = {"nodes": [{"id": "p", "label": "P", "value": each * 2, "children": [leaf("x", each, each), leaf("y", each, each)]}]}
    with pytest.raises(ReportDefectError):
        sections.validate(TREE, data)


# -- summary, series and rows --

def test_a_summary_checks_each_kind_of_item():
    ok = {"items": [{"key": "m", "label": "M", "kind": "money", "value": -5, "currency": "EUR", "note": "n"},
                    {"key": "c", "label": "C", "kind": "count", "value": 3}, {"key": "d", "label": "D", "kind": "date", "value": "2026-02-28"},
                    {"key": "t", "label": "T", "kind": "text", "value": "hello"}]}
    assert sections.validate(SUMMARY, ok) == ok
    for bad in ({"key": "m", "label": "M", "kind": "money", "value": 1, "currency": "eur"},
                {"key": "c", "label": "C", "kind": "count", "value": -1},
                {"key": "d", "label": "D", "kind": "date", "value": "2026-02-30"},
                {"key": "x", "label": "X", "kind": "text", "value": "", "extra": 1},
                {"key": "c", "label": "C", "kind": "count", "value": 1, "currency": "USD"},
                {"key": "u", "label": "U", "kind": "other", "value": 1}):
        with pytest.raises(ReportDefectError):
            sections.validate(SUMMARY, {"items": [bad]})
    with pytest.raises(ReportDefectError):                   # a repeated key
        sections.validate(SUMMARY, {"items": [ok["items"][0], ok["items"][0]]})


def test_a_series_has_dates_in_strict_order_and_integer_values():
    good = {"series": [{"key": "a", "label": "A", "kind": "money", "points": [{"x": "2026-01-01", "value": -5}, {"x": "2026-01-02", "value": 7}]}]}
    assert sections.validate(SERIES, good) == good
    for points in ([{"x": "2026-01-02", "value": 1}, {"x": "2026-01-01", "value": 1}], [{"x": "2026-01-01", "value": 1}] * 2,
                   [{"x": "2026-01-01", "value": 1.5}], [{"x": "January", "value": 1}]):
        bad = {"series": [{"key": "a", "label": "A", "kind": "money", "points": points}]}
        with pytest.raises(ReportDefectError):
            sections.validate(SERIES, bad)


def test_rows_check_columns_cells_and_ids():
    ok = {"columns": [{"key": "n", "label": "N", "kind": "text"}, {"key": "m", "label": "M", "kind": "money"},
                      {"key": "x", "label": "X", "kind": "native_money"}, {"key": "c", "label": "C", "kind": "count"}],
          "rows": [{"id": "r1", "cells": {"n": "a", "m": -5, "x": {"minor": 1, "currency": "EUR"}}, "link": {"to": "balance", "id": 3}}]}
    result = sections.validate(ROWS, ok)
    assert result["rows"][0]["cells"]["c"] is None            # a cell that is left out is empty
    column = {"key": "n", "label": "N", "kind": "text"}
    for bad in ({"columns": [column, column], "rows": []},                                           # a repeated column
                {"columns": [column], "rows": [{"id": "r", "cells": {"zz": "a"}}]},                  # a cell with no column
                {"columns": [column], "rows": [{"id": "r", "cells": {}}, {"id": "r", "cells": {}}]},  # a repeated row id
                {"columns": [column], "rows": [{"id": "r", "cells": {"n": 5}}]},                     # the wrong kind of cell
                {"columns": [{"key": "m", "label": "M", "kind": "money"}], "rows": [{"id": "r", "cells": {"m": True}}]},
                {"columns": [{"key": "x", "label": "X", "kind": "native_money"}], "rows": [{"id": "r", "cells": {"x": 5}}]},
                {"columns": [{"key": "q", "label": "Q", "kind": "weird"}], "rows": []}):
        with pytest.raises(ReportDefectError):
            sections.validate(ROWS, bad)


# -- the hierarchy: value is signed and additive --

def test_a_hierarchy_keeps_signed_values_and_its_parents_equal_the_sum_of_their_children():
    result = sections.validate(TREE, tree())
    a = result["nodes"][0]
    assert a["value"] == 300 and [c["value"] for c in a["children"]] == [500, -200]        # the negative stays negative


def test_a_parent_whose_value_is_not_the_sum_of_its_children_is_a_defect():
    data = tree()
    data["nodes"][0]["value"] = 301
    with pytest.raises(ReportDefectError, match="not the sum of its children"):
        sections.validate(TREE, data)


def test_node_ids_are_unique_across_the_whole_hierarchy():
    data = tree()
    data["nodes"][1]["children"][0]["id"] = "a1"
    with pytest.raises(ReportDefectError, match="repeats a node id"):
        sections.validate(TREE, data)
    with pytest.raises(ReportDefectError):
        sections.validate(TREE, {"nodes": [leaf("", 1, 1)]})


def test_a_hierarchy_is_bounded_in_depth_and_size():
    deep = leaf("n0", 1, 1)
    for number in range(1, sections.MAX_DEPTH + 1):
        deep = {"id": f"n{number}", "label": "N", "value": 1, "children": [deep]}
    with pytest.raises(ReportDefectError, match="deeper"):
        sections.validate(TREE, {"nodes": [deep]})
    with pytest.raises(ReportDefectError, match="more than"):
        sections.validate(UNSIZED, {"nodes": [leaf(f"n{i}", 0) for i in range(sections.MAX_NODES + 1)]})


# -- the hierarchy: size is a leaf's, and a parent's is derived --

def test_the_framework_adds_each_parents_size_as_the_sum_of_its_leaves():
    result = sections.validate(TREE, tree())
    a, b, c = result["nodes"]
    assert (a["size"], b["size"], c["size"]) == (500, 40, 7)
    assert [child["size"] for child in a["children"]] == [500, 0]


def test_a_value_is_never_turned_into_a_size_and_a_negative_leaf_has_the_size_the_report_gave_it():
    result = sections.validate(TREE, tree())
    assert result["nodes"][0]["children"][1]["value"] == -200 and result["nodes"][0]["children"][1]["size"] == 0


def test_a_parent_may_not_supply_its_own_size():
    data = tree()
    data["nodes"][0]["size"] = 300
    with pytest.raises(ReportDefectError, match="sums a parent's size"):
        sections.validate(TREE, data)


def test_every_leaf_of_a_sized_section_needs_a_size():
    for mutate in (lambda d: d["nodes"][2].pop("size"), lambda d: d["nodes"][0]["children"][0].pop("size")):
        data = tree()
        mutate(data)
        with pytest.raises(ReportDefectError, match="no size"):
            sections.validate(TREE, data)


@pytest.mark.parametrize("size", [-1, True, 2.5, "5", MAX_SAFE + 1])
def test_a_size_is_a_non_negative_whole_number_a_browser_reads_exactly(size):
    data = tree()
    data["nodes"][2]["size"] = size
    with pytest.raises(ReportDefectError):
        sections.validate(TREE, data)


def test_an_unsized_section_takes_no_sizes_and_adds_none():
    data = tree()
    for node in data["nodes"]:
        node.pop("size", None)
        for child in node.get("children", []):
            child.pop("size", None)
    result = sections.validate(UNSIZED, data)
    assert all("size" not in node for node in result["nodes"])
    with pytest.raises(ReportDefectError, match="is not sized"):
        sections.validate(UNSIZED, tree())


def test_the_checked_copy_is_a_new_object_and_the_calculations_data_is_not_changed():
    data = tree()
    before = copy.deepcopy(data)
    result = sections.validate(TREE, data)
    assert data == before and result is not data


# -- links --

def test_a_link_names_an_account_a_balance_or_a_list():
    assert sections.link({"to": "account", "id": 7}, "x") == {"to": "account", "id": 7}
    assert sections.link({"to": "balance", "id": 7}, "x") == {"to": "balance", "id": 7}
    got = sections.link({"to": "list", "list": "balances", "filters": [{"field": "account", "operator": "is", "value": 3}]}, "x")
    assert got["list"] == "balances" and got["filters"][0]["field"] == "account"


@pytest.mark.parametrize("bad", [
    {"to": "elsewhere"}, {"to": "account"}, {"to": "account", "id": 0}, {"to": "account", "id": True}, {"to": "account", "id": 1, "x": 2},
    {"to": "list", "list": "no_such_list"}, {"to": "list"}, {"to": "list", "list": "balances", "filters": [{"field": "a"}]},
    {"to": "list", "list": "balances", "filters": "nope"}, "account", None,
])
def test_a_link_that_names_nothing_real_is_a_defect(bad):
    with pytest.raises(ReportDefectError):
        sections.link(bad, "x")


def test_a_bad_link_inside_a_node_or_a_row_is_found():
    data = tree()
    data["nodes"][2]["link"] = {"to": "account", "id": 0}
    with pytest.raises(ReportDefectError):
        sections.validate(TREE, data)


# -- a node's note and colour --

def test_a_node_may_carry_a_short_note_and_the_entity_its_colour_comes_from():
    data = tree()
    data["nodes"][0]["note"] = "2 accounts"
    data["nodes"][0]["children"][0]["colour"] = {"kind": "account_type", "id": 7}
    got = sections.validate(TREE, data)["nodes"][0]
    assert got["note"] == "2 accounts" and got["children"][0]["colour"] == {"kind": "account_type", "id": 7}
    assert "note" not in got["children"][1] and "colour" not in got["children"][1]


@pytest.mark.parametrize("bad", ["", "   ", 5, None, "two\nlines", "x" * 121])
def test_a_note_is_one_short_line_of_text(bad):
    data = tree()
    data["nodes"][2]["note"] = bad
    with pytest.raises(ReportDefectError):
        sections.validate(TREE, data)


def test_a_note_of_the_longest_allowed_length_is_accepted():
    data = tree()
    data["nodes"][2]["note"] = "x" * 120
    assert sections.validate(TREE, data)["nodes"][2]["note"] == "x" * 120


@pytest.mark.parametrize("bad", [
    {"kind": "account_type"}, {"id": 3}, {"kind": "account_type", "id": 0}, {"kind": "account_type", "id": -1}, {"kind": "account_type", "id": True},
    {"kind": "account_type", "id": 1.5}, {"kind": "Account Type", "id": 3}, {"kind": "", "id": 3}, {"kind": "account_type", "id": 3, "slot": 2},
    {"kind": "account_type", "id": 2 ** 53}, "account_type", 3, None,
])
def test_a_colour_names_a_kind_and_an_id_from_1_and_nothing_else(bad):
    data = tree()
    data["nodes"][2]["colour"] = bad
    with pytest.raises(ReportDefectError):
        sections.validate(TREE, data)


# -- notes --

def test_a_note_has_a_code_a_text_and_may_name_a_declared_section():
    declared = (SUMMARY, TREE)
    good = [{"code": "not_drawn", "text": "Two accounts are not drawn.", "section": "h"}, {"code": "all", "text": "Everything."}]
    assert sections.validate_notes(good, declared) == good
    for bad in ([{"code": "x", "text": "t", "section": "nowhere"}], [{"code": "X", "text": "t"}], [{"code": "x", "text": ""}],
                [{"code": "x", "text": "t", "other": 1}], "not a list"):
        with pytest.raises(ReportDefectError):
            sections.validate_notes(bad, declared)


# -- how wide a section is on the page --

def test_a_section_takes_the_whole_width_unless_it_says_otherwise_and_may_take_any_whole_number_of_the_twelve_columns():
    assert SectionDef("r", "rows", "table", "R").columns == 12
    for columns in range(1, 13):
        sections.check("probe", (SectionDef("r", "rows", "table", "R", columns=columns),))


@pytest.mark.parametrize("columns", [0, 13, -1, 100, True, False, 6.0, 6.5, "6", None])
def test_a_section_that_takes_no_columns_more_than_twelve_or_not_a_whole_number_is_a_fault_in_the_report(columns):
    with pytest.raises(ReportDefinitionError, match="columns"):
        sections.check("probe", (SectionDef("r", "rows", "table", "R", columns=columns),))
