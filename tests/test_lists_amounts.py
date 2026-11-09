"""Amounts whose scale differs from row to row (ScaledBy), including a value the database works out with a function it has been
given, which the engine sees as an ordinary column of a view. Nothing here knows what the scale or the value means."""

import time
from decimal import Decimal

import pytest

import lists_schema
from lists_schema import READINGS, build, catalog
from northstar.errors import ValidationError
from northstar.lists.kinds import ScaledBy, normalise
from northstar.lists.query import run
from northstar.lists.registry import Catalog, FieldDef, RegistryError, TableDef
from northstar.lists.request import parse_request


@pytest.fixture(scope="module")
def conn():
    return build()


@pytest.fixture(scope="module")
def cat(conn):
    return catalog(conn)


def go(conn, cat, data=None, definition=READINGS):
    return run(conn, cat, definition, parse_request(cat, definition, data))


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
        record = dict(r)
        record["norm"] = normalise(r["amount"], r["decimals"])
        factor = next((f for f in sorted(lists_schema.FACTORS, key=lambda f: f[1], reverse=True)
                       if f[0] == r["symbol"] and f[1] <= r["taken_on"]), None)
        record["worked"] = None if r["amount"] is None or factor is None else int(Decimal(r["amount"]) * Decimal(factor[2]))
        record["worked_norm"] = normalise(record["worked"], r["decimals"])
        out.append(record)
    return out


# -- ScaledBy --

def test_a_row_shows_its_value_its_scale_and_its_unit_and_the_page_decides_how_to_write_them(conn, cat):
    rows = {r["_id"]: r for r in everything(conn, cat, {"columns": ["label", "amount"]})}
    for record in readings(conn):
        shown = rows[record["id"]]["amount"]
        if record["amount"] is None:
            assert shown is None
        else:
            assert shown == {"value": record["amount"], "scale": record["decimals"], "unit": record["symbol"]}


@pytest.mark.parametrize("key, norm", [("amount", "norm"), ("worked", "worked_norm")])
@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_amounts_are_sorted_by_the_number_shown_whatever_their_scale_and_empty_ones_come_last(conn, cat, key, norm, direction):
    rows = everything(conn, cat, {"columns": ["label"], "sort": {"field": key, "direction": direction}})
    by_id = {r["id"]: r for r in readings(conn)}
    norms = [by_id[r["_id"]][norm] for r in rows]
    present = [n for n in norms if n is not None]
    assert present == sorted(present, reverse=direction == "desc")
    assert norms[len(present):] == [None] * (len(norms) - len(present))
    assert len({by_id[r["_id"]]["symbol"] for r in rows[:50]}) > 1                       # the scales really are mixed


def matching(conn, cat, operator, value=None, key="amount"):
    data = {"filters": [{"field": key, "operator": operator, **({} if value is None else {"value": value})}]}
    return {r["_id"] for r in everything(conn, cat, data)}


@pytest.mark.parametrize("key, norm", [("amount", "norm"), ("worked", "worked_norm")])
def test_an_amount_filter_compares_the_number_shown_exactly(conn, cat, key, norm):
    live = readings(conn)
    ids = lambda test: {r["id"] for r in live if r[norm] is not None and test(r[norm])}
    assert matching(conn, cat, "at_least", "10", key) == ids(lambda n: n >= 10_000)
    assert matching(conn, cat, "at_most", "-1.5", key) == ids(lambda n: n <= -1_500)
    assert matching(conn, cat, "between", ["5", "1000"], key) == ids(lambda n: 5_000 <= n <= 1_000_000)
    assert matching(conn, cat, "equals", "0", key) == ids(lambda n: n == 0)
    assert matching(conn, cat, "is_empty", None, key) == {r["id"] for r in live if r[norm] is None}
    assert matching(conn, cat, "at_least", "10", key) and matching(conn, cat, "is_empty", None, key)


def test_a_typed_amount_with_a_third_decimal_place_can_only_equal_a_row_with_that_many(conn, cat):
    live = readings(conn)
    thousandths = matching(conn, cat, "equals", "5.005")
    assert thousandths == {r["id"] for r in live if r["norm"] == 5_005}
    assert all(r["decimals"] == 3 for r in live if r["id"] in thousandths)


def test_an_amount_with_more_than_three_places_is_refused_and_so_is_text_and_a_number_too_large_to_store(cat):
    for bad in ("1.0001", "abc", "", None, True, [1], "1e999", "NaN", "9" * 30, "-" + "9" * 30):
        with pytest.raises(ValidationError):
            parse_request(cat, READINGS, {"filters": [{"field": "amount", "operator": "equals", "value": bad}]})


def test_filtering_by_a_value_the_database_works_out_gives_the_same_rows_whether_it_is_shown_or_not(conn, cat):
    data = {"filters": [{"field": "worked", "operator": "between", "value": ["0", "50"]}]}
    shown = {r["_id"] for r in everything(conn, cat, {**data, "columns": ["label", "worked"]})}
    hidden = {r["_id"] for r in everything(conn, cat, {**data, "columns": ["label"]})}
    assert shown == hidden and shown


def test_grouping_by_a_value_the_database_works_out(conn, cat):
    live = {r["id"]: r for r in readings(conn)}
    rows = everything(conn, cat, {"columns": ["label"], "group": "worked", "sort": {"field": "label", "direction": "asc"}})
    sizes = {}
    for record in live.values():
        sizes[record["worked_norm"]] = sizes.get(record["worked_norm"], 0) + 1
    groups = [r["_group"] for r in rows]
    present = [g for g in groups if g is not None]
    assert present == sorted(present) and groups[len(present):] == [None] * (len(groups) - len(present))
    assert all(r["_group_count"] == sizes[normalise(live[r["_id"]]["worked"], live[r["_id"]]["decimals"])] for r in rows)


def test_sorting_twenty_thousand_rows_by_a_value_the_database_works_out_is_the_databases_own_work():
    big = build(tickets=5, readings=20_000)
    cat_big = catalog(big)
    before = big.total_changes
    started = time.perf_counter()
    result = go(big, cat_big, {"columns": ["label", "worked"], "sort": {"field": "worked", "direction": "desc"}, "page_size": 100})
    took = time.perf_counter() - started
    assert big.total_changes == before and result.total == 20_000 and len(result.rows) == 100
    assert took < 1, f"{took:.2f} s for 20,000 rows"


# -- a view as an entry --

def test_a_kinds_own_paths_are_checked_when_the_catalog_is_built(conn):
    tables = dict(lists_schema.TABLES)
    label = tables["reading_values"].fields["label"]
    for path, message in ((("measure", "nope"), "has no column nope"), (("nowhere", "decimals"), "has no relation nowhere")):
        tables["reading_values"] = TableDef("reading_values", "label", {
            "label": label, "amount": FieldDef(ScaledBy(scale_from=path))}, based_on="reading")
        with pytest.raises(RegistryError, match=message):
            Catalog(conn, tables)


def test_a_view_takes_its_key_and_its_relations_from_the_table_it_is_based_on(cat):
    assert cat.primary_key["reading_values"] == "id"
    assert set(cat.relations("reading_values")) == {"measure"}
    assert cat.relations("reading_values")["measure"].parent == "reading_values"
    assert cat.resolve("reading_values", "measure").column == "symbol"


def test_a_view_that_leaves_out_a_column_leaves_its_relation_out(conn):
    tables = dict(lists_schema.TABLES)
    tables["reading_without_measure"] = TableDef("reading_without_measure", "label",
                                                 {"label": tables["reading_values"].fields["label"]}, based_on="reading")
    assert Catalog(conn, tables).relations("reading_without_measure") == {}


def test_a_view_must_have_the_key_of_the_table_it_is_based_on_and_a_table_must_exist(conn):
    conn.execute("CREATE VIEW IF NOT EXISTS reading_no_key AS SELECT label FROM reading")
    tables = dict(lists_schema.TABLES)
    label = tables["reading_values"].fields["label"]
    tables["reading_no_key"] = TableDef("reading_no_key", "label", {"label": label}, based_on="reading")
    with pytest.raises(RegistryError, match="does not have reading's key id"):
        Catalog(conn, tables)
    tables = dict(lists_schema.TABLES)
    tables["reading_values"] = TableDef("reading_values", "label", {"label": label}, based_on="nothing")
    with pytest.raises(RegistryError, match="needs a single-column primary key"):
        Catalog(conn, tables)
