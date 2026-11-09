"""Amounts whose scale differs from row to row (ScaledBy) and columns worked out by a function (Computed), on the generated
schema. Nothing here knows what the scale or the value means: that is the point."""

import time
from datetime import date
from decimal import Decimal

import pytest

import lists_schema
from lists_schema import READINGS, build, catalog
from northstar.errors import ValidationError
from northstar.lists.kinds import normalise
from northstar.lists.query import ListContext, run
from northstar.lists.request import parse_request

CONTEXT = ListContext(today=date(2026, 6, 15))


@pytest.fixture(scope="module")
def conn():
    return build()


@pytest.fixture(scope="module")
def cat(conn):
    return catalog(conn)


def go(conn, cat, data=None, definition=READINGS):
    return run(conn, cat, definition, parse_request(cat, definition, data), CONTEXT)


def everything(conn, cat, data=None):
    rows, page = [], 1
    while True:
        result = go(conn, cat, {**(data or {}), "page": page, "page_size": 100})
        rows += result.rows
        if page >= result.pages:
            return rows
        page += 1


def readings(conn):
    out = []
    for r in conn.execute("SELECT r.*, m.symbol, m.decimals FROM reading r JOIN measure m ON m.id = r.measure_id ORDER BY r.id"):
        out.append({**dict(r), "norm": normalise(r["amount"], r["decimals"])})
    return out


def answer(row):
    """What lists_schema._work answers for a row, worked out here from the raw data."""
    factor = lists_schema.FACTORS.get(row["symbol"])
    if row["amount"] is None:
        return None
    if factor is None or row["taken_on"] < factor[1]:
        return None
    return int(Decimal(row["amount"]) * Decimal(factor[0]))


# -- ScaledBy --

def test_a_row_shows_its_value_its_scale_and_its_unit_and_the_page_decides_how_to_write_them(conn, cat):
    rows = {r["_id"]: r for r in everything(conn, cat, {"columns": ["label", "amount"]})}
    for record in readings(conn):
        shown = rows[record["id"]]["amount"]
        if record["amount"] is None:
            assert shown is None
        else:
            assert shown == {"value": record["amount"], "scale": record["decimals"], "unit": record["symbol"]}


@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_amounts_are_sorted_by_the_number_shown_whatever_their_scale(conn, cat, direction):
    rows = everything(conn, cat, {"columns": ["label"], "sort": {"field": "amount", "direction": direction}})
    by_id = {r["id"]: r for r in readings(conn)}
    norms = [by_id[r["_id"]]["norm"] for r in rows]
    present = [n for n in norms if n is not None]
    assert present == sorted(present, reverse=direction == "desc")
    assert norms[len(present):] == [None] * (len(norms) - len(present))                  # nulls last
    assert len({by_id[r["_id"]]["symbol"] for r in rows[:50]}) > 1                       # the scales really are mixed


def matching(conn, cat, operator, value=None, key="amount"):
    data = {"filters": [{"field": key, "operator": operator, **({} if value is None else {"value": value})}]}
    return {r["_id"] for r in everything(conn, cat, data)}


def test_an_amount_filter_compares_the_number_shown_exactly(conn, cat):
    live = readings(conn)
    ids = lambda test: {r["id"] for r in live if r["norm"] is not None and test(r["norm"])}
    assert matching(conn, cat, "at_least", "10") == ids(lambda n: n >= 10_000)
    assert matching(conn, cat, "at_most", "-1.5") == ids(lambda n: n <= -1_500)
    assert matching(conn, cat, "between", ["5", "1000"]) == ids(lambda n: 5_000 <= n <= 1_000_000)
    assert matching(conn, cat, "equals", "5") == ids(lambda n: n == 5_000)
    assert matching(conn, cat, "equals", "0") == ids(lambda n: n == 0)
    assert matching(conn, cat, "is_empty") == {r["id"] for r in live if r["amount"] is None}
    only_thousandths = matching(conn, cat, "equals", "5.005")
    assert only_thousandths == ids(lambda n: n == 5_005) and all(by["decimals"] == 3 for by in live if by["id"] in only_thousandths)


def test_an_amount_with_more_than_three_places_is_refused_and_so_is_text(conn, cat):
    for bad in ("1.0001", "abc", "", None, True, [1], "1e999", "NaN", "9" * 30, "-" + "9" * 30):
        with pytest.raises(ValidationError):
            parse_request(cat, READINGS, {"filters": [{"field": "amount", "operator": "equals", "value": bad}]})


def test_a_kinds_own_paths_are_checked_when_the_catalog_is_built(conn):
    from northstar.lists.kinds import ScaledBy
    from northstar.lists.registry import Catalog, FieldDef, RegistryError, TableDef
    tables = dict(lists_schema.TABLES)
    tables["reading"] = TableDef("reading", "label", {
        "label": tables["reading"].fields["label"], "amount": FieldDef(ScaledBy(scale_from=("measure", "nope")))})
    with pytest.raises(RegistryError, match="has no column nope"):
        Catalog(conn, tables)
    tables["reading"] = TableDef("reading", "label", {
        "label": tables["reading"].fields["label"], "amount": FieldDef(ScaledBy(scale_from=("nowhere", "decimals")))})
    with pytest.raises(RegistryError, match="has no relation nowhere"):
        Catalog(conn, tables)


# -- Computed --

def worked(row):
    return row["worked"]


def test_a_worked_out_column_shows_a_value_a_scale_a_unit_and_a_note_when_it_cannot_be_worked_out(conn, cat):
    rows = {r["_id"]: r for r in everything(conn, cat, {"columns": ["label", "worked"]})}
    saw = {"value": 0, "note": 0, "empty": 0}
    for record in readings(conn):
        shown = rows[record["id"]]["worked"]
        expected = answer(record)
        if record["amount"] is None:
            assert shown is None
            saw["empty"] += 1
        elif expected is None:
            assert shown == {"value": None, "scale": 2, "unit": "W", "note": f"No factor for {record['symbol']}"}
            saw["note"] += 1
        else:
            assert shown == {"value": expected, "scale": record["decimals"], "unit": "W", "note": None}
            saw["value"] += 1
    assert all(saw.values())


def test_when_only_shown_it_is_worked_out_for_the_page_alone(conn, cat):
    lists_schema.WORK_CALLS.clear()
    result = go(conn, cat, {"columns": ["label", "worked"], "page_size": 10})
    assert lists_schema.WORK_CALLS == [10] and len(result.rows) == 10


@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_sorting_by_a_worked_out_column_works_it_out_for_every_row_and_puts_empty_last(conn, cat, direction):
    lists_schema.WORK_CALLS.clear()
    rows = everything(conn, cat, {"columns": ["label", "worked"], "sort": {"field": "worked", "direction": direction}})
    by_id = {r["id"]: r for r in readings(conn)}
    normalised = [normalise(answer(by_id[r["_id"]]), by_id[r["_id"]]["decimals"]) for r in rows]
    present = [n for n in normalised if n is not None]
    assert present == sorted(present, reverse=direction == "desc")
    assert normalised[len(present):] == [None] * (len(normalised) - len(present))
    assert len(rows) == 400 and max(lists_schema.WORK_CALLS) == 400                   # every row, once, however many pages


def test_filtering_and_grouping_by_a_worked_out_column(conn, cat):
    live = readings(conn)
    by_id = {r["id"]: r for r in live}
    norm = lambda r: normalise(answer(r), r["decimals"])
    got = matching(conn, cat, "at_least", "100", key="worked")
    assert got == {r["id"] for r in live if norm(r) is not None and norm(r) >= 100_000} and got
    assert matching(conn, cat, "is_empty", key="worked") == {r["id"] for r in live if answer(r) is None}
    rows = everything(conn, cat, {"columns": ["label"], "group": "worked", "sort": {"field": "label", "direction": "asc"}})
    groups = [None if r["_group"] is None else r["_group"] for r in rows]
    present = [g for g in groups if g is not None]
    assert present == sorted(present) and groups[len(present):] == [None] * (len(groups) - len(present))
    sizes = {}
    for r in live:
        sizes[norm(r)] = sizes.get(norm(r), 0) + 1
    assert all(r["_group_count"] == sizes[r["_group"]] for r in rows)
    assert {r["_id"] for r in rows} == set(by_id)


def test_the_same_filter_gives_the_same_rows_whether_the_column_is_shown_or_not(conn, cat):
    data = {"filters": [{"field": "worked", "operator": "between", "value": ["0", "50"]}]}
    shown = {r["_id"] for r in everything(conn, cat, {**data, "columns": ["label", "worked"]})}
    hidden = {r["_id"] for r in everything(conn, cat, {**data, "columns": ["label"]})}
    assert shown == hidden and shown


def test_a_worked_out_column_can_only_be_used_from_its_own_table(conn):
    from northstar.lists.kinds import Text
    from northstar.lists.registry import Catalog, FieldDef, TableDef
    conn.execute("CREATE TABLE IF NOT EXISTS holder (id INTEGER PRIMARY KEY, name TEXT, reading_id INTEGER REFERENCES reading(id))")
    tables = {**lists_schema.TABLES, "holder": TableDef("holder", "name", {"name": FieldDef(Text())})}
    holders = Catalog(conn, tables)
    assert holders.resolve("reading", "worked")                         # from its own table
    with pytest.raises(ValidationError, match="its own table only"):
        holders.resolve("holder", "reading.worked")


def test_working_a_column_out_for_every_row_reads_and_writes_nothing_else_and_is_fast_enough():
    big = build(tickets=5, readings=20_000)
    cat_big = catalog(big)
    before = big.total_changes
    started = time.perf_counter()
    result = go(big, cat_big, {"columns": ["label", "worked"], "sort": {"field": "worked", "direction": "desc"}, "page_size": 100},
                READINGS)
    took = time.perf_counter() - started
    assert big.total_changes == before                                                   # no table was written
    assert result.total == 20_000 and len(result.rows) == 100
    assert took < 2, f"{took:.2f} s for 20,000 rows"


def test_a_function_that_answers_the_wrong_number_of_times_is_a_mistake(conn):
    from northstar.lists.kinds import Computed
    from northstar.lists.registry import Catalog, FieldDef, TableDef
    tables = dict(lists_schema.TABLES)
    tables["reading"] = TableDef("reading", "label", {
        "label": tables["reading"].fields["label"],
        "worked": FieldDef(Computed(inputs=("label",), compute=lambda conn, context, rows: []))})
    bad = Catalog(conn, tables)
    definition = READINGS.__class__("bad", "reading", ("label",), ("label", "asc"))
    with pytest.raises(RuntimeError, match="answer once for every row"):
        run(conn, bad, definition, parse_request(bad, definition, {"columns": ["label", "worked"]}), CONTEXT)
