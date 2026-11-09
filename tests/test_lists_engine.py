"""The list engine, on a schema that is not Northstar's (see lists_schema.py)."""

import sqlite3

import pytest

from lists_schema import STATUSES, TABLES, TICKETS, build, catalog
from northstar.errors import NotFoundError, ValidationError
from northstar.lists import loader, registry
from northstar.lists.listdef import ListDef, check
from northstar.lists.query import run
from northstar.lists.registry import Catalog, FieldDef, RegistryError, TableDef
from northstar.lists.kinds import Text
from northstar.lists.request import parse_request


@pytest.fixture(scope="module")
def conn():
    return build()


@pytest.fixture(scope="module")
def cat(conn):
    return catalog(conn)


def view(conn, cat, data=None, definition=TICKETS):
    return run(conn, cat, definition, parse_request(cat, definition, data))


def everything(conn, cat, data=None, definition=TICKETS):
    """Every matching row, read across all the pages."""
    rows, page = [], 1
    while True:
        result = view(conn, cat, {**(data or {}), "page": page, "page_size": 100}, definition)
        rows += result.rows
        if page >= result.pages:
            return rows
        page += 1


def live_tickets(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM ticket WHERE deleted_at IS NULL ORDER BY id")]


def person_name(conn, person_id):
    return None if person_id is None else conn.execute("SELECT name FROM person WHERE id = ?", (person_id,)).fetchone()[0]


# -- the catalog --

def test_relations_are_read_from_the_foreign_keys(cat):
    assert set(cat.relations("ticket")) == {"site", "kind", "assignee", "reviewer"}
    assert set(cat.relations("person")) == {"team"}
    assert cat.relations("ticket")["assignee"].nullable and not cat.relations("ticket")["site"].nullable


def test_a_table_a_foreign_key_points_at_must_have_an_entry(conn):
    without_unit = {name: table for name, table in TABLES.items() if name != "unit"}
    with pytest.raises(RegistryError, match="team.unit_id points at unit, which has no entry"):
        Catalog(conn, without_unit)


@pytest.mark.parametrize("table, message", [
    (TableDef("unit", "missing", {"name": FieldDef(Text())}), "display column missing is not offered"),
    (TableDef("unit", "name", {"name": FieldDef(Text())}, denied=frozenset({"name"})), "both offered and denied"),
    (TableDef("unit", "name", {"name": FieldDef(Text()), "nope": FieldDef(Text())}), "unit.nope: there is no such column"),
    (TableDef("unit", "name", {"name": FieldDef(Text())}, tell_apart="x"), "tell-apart column x is not offered"),
])
def test_a_registry_that_disagrees_with_the_database_is_a_mistake_found_at_once(conn, table, message):
    with pytest.raises(RegistryError, match=message):
        Catalog(conn, {**TABLES, "unit": table})


def test_a_list_definition_naming_something_not_offered_is_refused_when_registered(cat):
    check(cat, TICKETS)
    for bad in (ListDef("x", "ticket", ("nope",), ("code", "asc")), ListDef("x", "ticket", ("code",), ("code", "up")),
                ListDef("x", "ticket", ("code",), ("code", "asc"), page_size=7), ListDef("x", "nothing", ("code",), ("code", "asc")),
                ListDef("x", "ticket", ("assignee.secret",), ("code", "asc"))):
        with pytest.raises(RegistryError):
            check(cat, bad)


# -- keys --

def test_a_relation_means_the_display_value_of_what_it_points_at(cat):
    resolved = cat.resolve("ticket", "assignee")
    assert (resolved.column, resolved.relation.target, resolved.label) == ("name", "person", "Assigned to")
    assert cat.resolve("ticket", "reviewer").label == "Reviewer"                    # the same table in another role
    assert cat.resolve("ticket", "site.area.lead.name").label == "Site › Area › Lead › Name"


def test_a_path_can_be_as_deep_as_the_limit_and_no_deeper(cat, monkeypatch):
    assert cat.resolve("ticket", "site.area.region.head.team.unit").key == "site.area.region.head.team.unit"   # six relations
    monkeypatch.setattr(registry, "MAX_DEPTH", 3)
    assert cat.resolve("ticket", "site.area.region")
    with pytest.raises(ValidationError, match="more than 3 levels"):
        cat.resolve("ticket", "site.area.region.head")


def test_the_same_table_in_two_roles_is_joined_separately(conn, cat):
    rows = everything(conn, cat, {"columns": ["code", "assignee", "reviewer", "site.lead", "site.area.lead"]})
    expected = {t["code"]: t for t in live_tickets(conn)}
    assert len(rows) == len(expected)
    for row in rows:
        ticket = expected[row["code"]]
        assert row["assignee"] == person_name(conn, ticket["assignee_id"])
        assert row["reviewer"] == person_name(conn, ticket["reviewer_id"])
    leads = {r["site.lead"] for r in rows}
    assert leads <= {None, "Casey Dunn", "avery reed"} and {r["site.area.lead"] for r in rows} <= {None, "Blake Moss"}


def test_denied_columns_cannot_be_reached_by_any_path(cat):
    for key in ("deleted_at", "assignee.secret", "assignee.team.secret", "site.deleted_at", "id", "assignee_id", "assignee.id"):
        with pytest.raises(ValidationError, match="not a column"):
            cat.resolve("ticket", key)


def test_a_path_that_returns_to_a_table_it_has_passed_through_is_refused():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("CREATE TABLE node (id INTEGER PRIMARY KEY, name TEXT, parent_id INTEGER REFERENCES node(id));")
    cat = Catalog(conn, {"node": TableDef("node", "name", {"name": FieldDef(Text())})})
    with pytest.raises(ValidationError, match="comes back to a table"):
        cat.resolve("node", "parent")


def test_a_table_that_cannot_be_walked_into_still_shows_its_display_value(conn):
    tables = {**TABLES, "person": TableDef("person", "name", {"name": FieldDef(Text())}, walkable=False)}
    cat = Catalog(conn, tables)
    assert cat.resolve("ticket", "assignee").column == "name"
    with pytest.raises(ValidationError, match="only shows its name"):
        cat.resolve("ticket", "assignee.team")


def test_a_composite_foreign_key_is_not_a_relation_a_person_can_follow():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("CREATE TABLE a (x INTEGER, y INTEGER, name TEXT, PRIMARY KEY (x, y));")
    with pytest.raises(RegistryError, match="needs a single-column primary key"):
        Catalog(conn, {"a": TableDef("a", "name", {"name": FieldDef(Text())})})


# -- requests --

@pytest.mark.parametrize("data, message", [
    ({"surprise": 1}, "Unknown request field"),
    ("not a dict", "must be an object"),
    ({"columns": []}, "at least one column"),
    ({"columns": ["code", "code"]}, "once"),
    ({"columns": [{"a": 1}]}, "does not exist"),
    ({"columns": ["code; DROP TABLE ticket"]}, "not a column"),
    ({"sort": {"field": "nope"}}, "not a column"),
    ({"sort": {"field": "code", "direction": "sideways"}}, "ascending or descending"),
    ({"sort": "code"}, "Sort by a column"),
    ({"group": "deleted_at"}, "not a column"),
    ({"page": 0}, "page"), ({"page": "2"}, "page"), ({"page": True}, "page"),
    ({"page_size": 7}, "rows per page"),
    ({"search": "x" * 101}, "up to 100"),
    ({"filters": "x"}, "must be a list"),
    ({"filters": [{"field": "code"}]}, "Choose how to filter"),
    ({"filters": [{"field": "code", "operator": "contains"}]}, "Type the text"),
    ({"filters": [{"field": "code", "operator": ["contains"], "value": "a"}]}, "Choose how to filter"),
    ({"filters": [{"field": "code", "operator": "contains", "value": "a"}] * 2}, "one filter"),
    ({"filters": [{"field": "code", "operator": "between", "value": [1, 2]}]}, "cannot be filtered with"),
    ({"filters": [{"field": "nope", "operator": "equals", "value": 1}]}, "not a column"),
    ({"filters": [{"field": "code", "operator": "equals", "value": "a", "extra": 1}]}, "needs a field"),
])
def test_a_bad_request_is_refused_with_a_message(cat, data, message):
    with pytest.raises(ValidationError, match=message):
        parse_request(cat, TICKETS, data)


def test_values_are_parameters_so_sql_in_them_is_only_text(conn, cat):
    nasty = "x' OR 1=1; DROP TABLE ticket; --"
    result = view(conn, cat, {"filters": [{"field": "title", "operator": "contains", "value": nasty}]})
    assert result.total == 0
    assert conn.execute("SELECT COUNT(*) FROM ticket").fetchone()[0] == 300
    assert view(conn, cat, {"search": nasty}).total == 0


# -- one row for each record --

def test_every_live_ticket_appears_once_however_many_relations_are_shown(conn, cat):
    columns = ["code", "assignee", "reviewer", "site", "site.area", "site.area.region", "site.area.region.head",
               "site.area.region.head.team", "site.area.region.head.team.unit", "kind", "kind.family"]
    rows = everything(conn, cat, {"columns": columns})
    live = live_tickets(conn)
    assert len(rows) == len(live) == view(conn, cat).total
    assert sorted(r["_id"] for r in rows) == [t["id"] for t in live]


def test_soft_deleted_rows_never_appear_and_cannot_be_asked_for(conn, cat):
    deleted = {r["id"] for r in conn.execute("SELECT id FROM ticket WHERE deleted_at IS NOT NULL")}
    assert deleted
    assert not deleted & {r["_id"] for r in everything(conn, cat)}
    assert view(conn, cat, {"search": "T-0020"}).total == 0                        # ticket 20 is deleted
    with pytest.raises(ValidationError):
        parse_request(cat, TICKETS, {"filters": [{"field": "deleted_at", "operator": "is_empty"}]})


def test_a_scope_is_part_of_the_hard_exclusions(conn, cat):
    scoped = ListDef("scoped", "ticket", ("code", "items"), ("code", "asc"), source="ticket_live", scope="b.items > 3")
    rows = everything(conn, cat, definition=scoped)
    assert rows and all(r["items"] > 3 for r in rows)
    assert len(rows) == sum(1 for t in live_tickets(conn) if t["items"] > 3)


# -- sorting --

def expected_order(rows, key, descending, value=lambda row: row):
    """The sort the design describes, written independently: nulls last, text without case, then the id ascending."""
    ordered = sorted(rows, key=lambda r: r["_id"])
    present = [r for r in ordered if value(r) is not None]
    missing = [r for r in ordered if value(r) is None]
    fold = (lambda v: v.lower()) if isinstance(next(iter(value(r) for r in present), 0), str) else (lambda v: v)
    return sorted(present, key=lambda r: fold(value(r)), reverse=descending) + missing


@pytest.mark.parametrize("key, kind", [("title", "text"), ("assignee", "relation"), ("notes", "text with empty strings"),
                                       ("score_x100", "scaled integer"), ("closed_at", "timestamp"), ("passed", "nullable yes or no"),
                                       ("weight", "float"), ("status", "category"), ("site.area.lead", "deep relation")])
@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_sorting_puts_nulls_last_in_both_directions_ignores_case_and_ties_by_id(conn, cat, key, kind, direction):
    rows = everything(conn, cat, {"columns": ["code", key], "sort": {"field": key, "direction": direction}})
    got = [r["_id"] for r in rows]
    # python's stable sort keeps id order within equal values, and reverse=True keeps equal items in their original order too
    desired = expected_order(rows, key, direction == "desc", value=lambda r: r[key])
    assert got == [r["_id"] for r in desired], kind
    nulls = [r[key] is None for r in rows]
    assert nulls == sorted(nulls)                                                  # every null is after every value


def test_a_sort_column_need_not_be_shown(conn, cat):
    rows = everything(conn, cat, {"columns": ["code"], "sort": {"field": "items", "direction": "desc"}})
    by_id = {t["id"]: t for t in live_tickets(conn)}
    items = [by_id[r["_id"]]["items"] for r in rows]
    assert items == sorted(items, reverse=True)


# -- paging --

def test_paging_counts_all_matching_rows_and_clamps_a_page_past_the_end(conn, cat):
    first = view(conn, cat, {"page_size": 25})
    assert (first.total, first.pages, first.page, len(first.rows)) == (285, 12, 1, 25)
    last = view(conn, cat, {"page_size": 25, "page": 12})
    assert len(last.rows) == 10
    beyond = view(conn, cat, {"page_size": 25, "page": 99})
    assert (beyond.page, [r["_id"] for r in beyond.rows]) == (12, [r["_id"] for r in last.rows])
    empty = view(conn, cat, {"filters": [{"field": "title", "operator": "equals", "value": "no such title"}]})
    assert (empty.total, empty.pages, empty.page, empty.rows) == (0, 1, 1, [])
    pages = [view(conn, cat, {"page_size": 10, "page": n}).rows for n in (1, 2, 3)]
    ids = [r["_id"] for page in pages for r in page]
    assert len(set(ids)) == 30                                                      # no row on two pages


# -- filters --

def titles(conn):
    return {t["id"]: t["title"] for t in live_tickets(conn)}


def matching(conn, cat, field, operator, value=None):
    data = {"filters": [{"field": field, "operator": operator, **({} if value is None else {"value": value})}]}
    return {r["_id"] for r in everything(conn, cat, data)}


def test_text_filters_treat_wildcards_as_ordinary_characters_and_ignore_case(conn, cat):
    live = live_tickets(conn)
    assert matching(conn, cat, "title", "contains", "100%") == {t["id"] for t in live if "100%" in t["title"]}
    assert matching(conn, cat, "title", "contains", "a_b") == {t["id"] for t in live if "a_b" in t["title"]}
    assert matching(conn, cat, "title", "contains", "_") == {t["id"] for t in live if "_" in t["title"]}
    assert matching(conn, cat, "title", "contains", "REPLACE") == {t["id"] for t in live if "replace" in t["title"].lower()}
    assert matching(conn, cat, "title", "equals", "replace part") == {t["id"] for t in live if t["title"].lower() == "replace part"}


def test_empty_text_means_no_value_or_an_empty_one(conn, cat):
    live = live_tickets(conn)
    assert matching(conn, cat, "notes", "is_empty") == {t["id"] for t in live if not t["notes"]}
    assert matching(conn, cat, "notes", "is_not_empty") == {t["id"] for t in live if t["notes"]}
    assert any(t["notes"] == "" for t in live) and any(t["notes"] is None for t in live)


def test_a_scaled_integer_is_typed_as_a_decimal_and_refused_when_it_has_too_many_places(conn, cat):
    live = live_tickets(conn)
    assert matching(conn, cat, "score_x100", "at_least", "19.99") == {t["id"] for t in live if (t["score_x100"] or -10**9) >= 1999}
    assert matching(conn, cat, "score_x100", "equals", "-2.5") == {t["id"] for t in live if t["score_x100"] == -250}
    assert matching(conn, cat, "score_x100", "equals", "0") == {t["id"] for t in live if t["score_x100"] == 0}
    assert matching(conn, cat, "score_x100", "is_empty") == {t["id"] for t in live if t["score_x100"] is None}
    with pytest.raises(ValidationError, match="at most 2 decimal places"):
        parse_request(cat, TICKETS, {"filters": [{"field": "score_x100", "operator": "equals", "value": "0.001"}]})
    with pytest.raises(ValidationError, match="Type a number"):
        parse_request(cat, TICKETS, {"filters": [{"field": "score_x100", "operator": "equals", "value": "1e400x"}]})


def test_a_number_too_large_to_store_is_refused_not_passed_to_the_database(cat):
    huge = "9" * 30
    for field, operator in (("items", "equals"), ("score_x100", "at_least")):         # a float can hold it, so it is not refused
        with pytest.raises(ValidationError):
            parse_request(cat, TICKETS, {"filters": [{"field": field, "operator": operator, "value": huge}]})
    with pytest.raises(ValidationError):
        parse_request(cat, TICKETS, {"filters": [{"field": "items", "operator": "between", "value": ["0", huge]}]})


def test_a_range_includes_both_ends_and_before_and_after_exclude_the_day(conn, cat):
    live = live_tickets(conn)
    low, high = "2025-03-05", "2025-06-20"
    assert matching(conn, cat, "opened_on", "between", [low, high]) == {t["id"] for t in live if low <= t["opened_on"] <= high}
    assert matching(conn, cat, "opened_on", "before", low) == {t["id"] for t in live if t["opened_on"] < low}
    assert matching(conn, cat, "opened_on", "after", high) == {t["id"] for t in live if t["opened_on"] > high}
    assert matching(conn, cat, "items", "between", [2, 3]) == {t["id"] for t in live if 2 <= t["items"] <= 3}
    for bad in ([high, low], ["2025-02-30", high], ["2025-3-5", high], "2025-03-05", [low]):
        with pytest.raises(ValidationError):
            parse_request(cat, TICKETS, {"filters": [{"field": "opened_on", "operator": "between", "value": bad}]})
    with pytest.raises(ValidationError, match="ends before"):
        parse_request(cat, TICKETS, {"filters": [{"field": "items", "operator": "between", "value": [5, 1]}]})


def test_a_timestamp_is_filtered_by_its_utc_date(conn, cat):
    live = [t for t in live_tickets(conn) if t["closed_at"]]
    day = sorted(t["closed_at"][:10] for t in live)[len(live) // 2]
    assert matching(conn, cat, "closed_at", "between", [day, day]) == {t["id"] for t in live if t["closed_at"][:10] == day}
    assert matching(conn, cat, "closed_at", "before", day) == {t["id"] for t in live if t["closed_at"][:10] < day}
    assert matching(conn, cat, "closed_at", "is_empty") == {t["id"] for t in live_tickets(conn) if t["closed_at"] is None}


def test_yes_or_no_offers_empty_only_when_the_column_can_be_empty(conn, cat):
    live = live_tickets(conn)
    assert matching(conn, cat, "passed", "is_yes") == {t["id"] for t in live if t["passed"] == 1}
    assert matching(conn, cat, "passed", "is_no") == {t["id"] for t in live if t["passed"] == 0}
    assert matching(conn, cat, "passed", "is_empty") == {t["id"] for t in live if t["passed"] is None}
    assert matching(conn, cat, "flagged", "is_yes") == {t["id"] for t in live if t["flagged"] == 1}
    with pytest.raises(ValidationError, match="cannot be filtered with"):
        parse_request(cat, TICKETS, {"filters": [{"field": "flagged", "operator": "is_empty"}]})


def test_a_choice_is_any_of_the_declared_values(conn, cat):
    live = live_tickets(conn)
    assert matching(conn, cat, "status", "is_any_of", ["Open", "Closed"]) == {t["id"] for t in live if t["status"] in ("Open", "Closed")}
    for bad in ([], "Open", ["Nope"], [None]):
        with pytest.raises(ValidationError):
            parse_request(cat, TICKETS, {"filters": [{"field": "status", "operator": "is_any_of", "value": bad}]})


def test_a_relation_is_filtered_by_the_id_it_points_at_not_by_its_display_value(conn, cat):
    live = live_tickets(conn)
    names = [r[0] for r in conn.execute("SELECT name FROM person WHERE id IN (1, 8)")]
    assert names == ["Avery Reed", "Avery Reed"]                                    # two people, one display value
    assert matching(conn, cat, "assignee", "is_any_of", [8]) == {t["id"] for t in live if t["assignee_id"] == 8}
    assert matching(conn, cat, "assignee", "is_any_of", [1, 2]) == {t["id"] for t in live if t["assignee_id"] in (1, 2)}
    by_site = {r["id"]: r["lead_id"] for r in conn.execute("SELECT id, lead_id FROM site")}
    assert matching(conn, cat, "site.lead", "is_any_of", [3]) == {t["id"] for t in live if by_site[t["site_id"]] == 3}
    with pytest.raises(ValidationError, match="Choose from the list"):
        parse_request(cat, TICKETS, {"filters": [{"field": "assignee", "operator": "is_any_of", "value": ["Avery Reed"]}]})


def test_filters_combine_with_and(conn, cat):
    live = live_tickets(conn)
    data = {"filters": [{"field": "status", "operator": "is_any_of", "value": ["Closed"]},
                        {"field": "flagged", "operator": "is_yes"}, {"field": "assignee", "operator": "is_any_of", "value": [1, 2]}]}
    expected = {t["id"] for t in live if t["status"] == "Closed" and t["flagged"] == 1 and t["assignee_id"] in (1, 2)}
    assert {r["_id"] for r in everything(conn, cat, data)} == expected and expected


# -- search --

def test_search_matches_flagged_columns_and_the_names_of_related_records_and_treats_wildcards_literally(conn, cat):
    live = live_tickets(conn)
    got = {r["_id"] for r in everything(conn, cat, {"search": "avery"})}
    averys = {1, 3, 8}                                                              # "Avery Reed" twice and "avery reed"
    by_site = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM site")}
    expected = {t["id"] for t in live if t["assignee_id"] in averys or t["reviewer_id"] in averys
                or "avery" in (t["title"] + (t["notes"] or "") + t["code"]).lower()}
    assert got == expected and got
    assert {r["_id"] for r in everything(conn, cat, {"search": "100%"})} == {t["id"] for t in live if "100%" in t["title"]}
    assert {r["_id"] for r in everything(conn, cat, {"search": "site 2"})} == {t["id"] for t in live if by_site[t["site_id"]] == "Site 2"}
    assert {r["_id"] for r in everything(conn, cat, {"search": "email"})} == set()   # email is not searchable, and not searched
    both = everything(conn, cat, {"search": "avery", "filters": [{"field": "status", "operator": "is_any_of", "value": ["Open"]}]})
    assert {r["_id"] for r in both} == {t["id"] for t in live if t["id"] in got and t["status"] == "Open"}


# -- grouping --

def test_grouping_orders_by_the_group_then_the_sort_and_counts_each_group_across_all_pages(conn, cat):
    data = {"columns": ["code", "kind"], "group": "kind", "sort": {"field": "code", "direction": "desc"}}
    rows = everything(conn, cat, data)
    sizes = {}
    for ticket in live_tickets(conn):
        name = conn.execute("SELECT name FROM kind WHERE id = ?", (ticket["kind_id"],)).fetchone()[0]
        sizes[name] = sizes.get(name, 0) + 1
    assert [r["_group"] for r in rows] == sorted((r["_group"] for r in rows), key=str.lower)
    assert all(r["_group_count"] == sizes[r["_group"]] for r in rows)
    for group in sizes:
        codes = [r["code"] for r in rows if r["_group"] == group]
        assert codes == sorted(codes, reverse=True)
    first = view(conn, cat, {**data, "page_size": 10})
    assert all(r["_group_count"] == sizes[r["_group"]] for r in first.rows)         # the count is the whole group's, not the page's


def test_a_group_with_no_value_comes_last(conn, cat):
    rows = everything(conn, cat, {"columns": ["code", "assignee"], "group": "assignee"})
    groups = [r["_group"] for r in rows]
    assert groups[-1] is None and groups.index(None) == len([g for g in groups if g is not None])
    assert sum(1 for r in rows if r["_group"] is None) == rows[-1]["_group_count"]


# -- links and descriptions --

def linked(conn, cat, columns, viewer=()):
    parsed = parse_request(cat, TICKETS, {"columns": columns, "page_size": 100})
    return run(conn, cat, TICKETS, parsed, frozenset(viewer)).rows


def test_a_relation_opens_the_page_of_the_record_it_points_at_and_the_display_column_opens_the_rows_own(conn, cat):
    rows = linked(conn, cat, ["code", "site", "kind", "title"])
    by_id = {t["id"]: t for t in live_tickets(conn)}
    kinds = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM kind")}
    for row in rows:
        ticket = by_id[row["_id"]]
        assert row["_links"] == {"code": f"/tickets/{row['_id']}", "site": f"/sites/{ticket['site_id']}",
                                 "kind": f"/kinds/{kinds[ticket['kind_id']]}"}        # nothing for a plain column such as title


def test_a_relation_with_nothing_in_it_has_no_link(conn, cat):
    rows = linked(conn, cat, ["code", "assignee"], viewer={"staff"})
    by_id = {t["id"]: t for t in live_tickets(conn)}
    assert any(by_id[r["_id"]]["assignee_id"] is None for r in rows) and any(by_id[r["_id"]]["assignee_id"] for r in rows)
    for row in rows:
        assignee = by_id[row["_id"]]["assignee_id"]
        assert row["_links"].get("assignee") == (None if assignee is None else f"/people/{assignee}")


def test_a_page_that_is_for_a_role_opens_only_for_a_viewer_who_has_it(conn, cat):
    assert all("assignee" not in r["_links"] for r in linked(conn, cat, ["code", "assignee"]))
    assert all("assignee" not in r["_links"] for r in linked(conn, cat, ["code", "assignee"], viewer={"admin"}))
    assert any("assignee" in r["_links"] for r in linked(conn, cat, ["code", "assignee"], viewer={"staff"}))
    assert all(r["_links"]["site"].startswith("/sites/") for r in linked(conn, cat, ["site"]))     # for everyone


def test_a_value_in_an_address_is_quoted_so_it_cannot_change_the_path():
    big = build(tickets=5)
    big.execute("UPDATE kind SET name = '../a b/c?d#e' WHERE id = 1")
    cat_big = catalog(big)
    rows = run(big, cat_big, TICKETS, parse_request(cat_big, TICKETS, {"columns": ["kind"], "page_size": 10}))
    hrefs = {r["_links"]["kind"] for r in rows.rows}
    assert "/kinds/..%2Fa%20b%2Fc%3Fd%23e" in hrefs
    assert all("/kinds/" in h and h.count("/") == 2 for h in hrefs)


def test_the_columns_are_described_for_a_page(conn, cat):
    from northstar.lists.query import describe
    keys = ["code", "assignee", "site.area", "score_x100", "passed", "status", "opened_on", "closed_at", "weight", "items"]
    described = {d["key"]: d for d in describe(cat, TICKETS, keys, frozenset({"staff"}))}
    assert (described["code"]["label"], described["code"]["kind"], described["code"]["linked"]) == ("Code", "text", True)
    assert (described["assignee"]["label"], described["assignee"]["linked"]) == ("Assigned to", True)
    assert described["site.area"]["path_label"] == "Site › Area" and described["site.area"]["label"] == "Area"
    assert described["site.area"]["linked"] is False                       # an area has no page of its own
    assert [described[k]["kind"] for k in ("score_x100", "passed", "status", "opened_on", "closed_at", "weight", "items")] == [
        "decimal", "yes_no", "choice", "date", "timestamp", "number", "integer"]
    assert describe(cat, TICKETS, ["assignee"])[0]["linked"] is False       # the same column for a viewer without the role


# -- the loader --

def test_a_list_is_found_through_the_loader_and_an_unknown_one_is_not_found():
    with pytest.raises(NotFoundError):
        loader.get_list_definition("no such list")
    with pytest.raises(NotFoundError):
        loader.get_list_definition(["unhashable"])
    probe = ListDef("probe_for_the_loader_test", "ticket", ("code",), ("code", "asc"))
    loader.register(probe)
    assert loader.get_list_definition("probe_for_the_loader_test") is probe
    with pytest.raises(ValueError, match="already registered"):
        loader.register(probe)
    loader._DEFINITIONS.pop("probe_for_the_loader_test")
