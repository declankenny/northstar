"""The tree of columns a list offers, and the choices a filter can pick from, on the generated schema (lists_schema.py)."""

import pytest

from lists_schema import READINGS, TABLES, TICKETS, build, catalog
from northstar.errors import ValidationError
from northstar.lists import query, registry
from northstar.lists.listdef import ListDef
from northstar.lists.registry import Catalog, FieldDef, TableDef
from northstar.lists.kinds import Text
from northstar.lists.tree import field_tree


@pytest.fixture(scope="module")
def conn():
    return build()


@pytest.fixture(scope="module")
def cat(conn):
    return catalog(conn)


def keys(node):
    """Every key in a tree, branches and leaves."""
    found = [f["key"] for f in node["fields"]]
    for relation in node["relations"]:
        found.append(relation["key"])
        if relation["children"]:
            found += keys(relation["children"])
    return found


def find(node, key):
    for field in node["fields"]:
        if field["key"] == key:
            return field
    for relation in node["relations"]:
        if relation["key"] == key:
            return relation
        if relation["children"] and key.startswith(relation["key"] + "."):
            return find(relation["children"], key)
    raise KeyError(key)


# -- the tree --

def test_the_tree_offers_the_columns_of_the_table_and_a_relation_for_each_foreign_key(cat):
    tree = field_tree(cat, TICKETS)
    assert [f["key"] for f in tree["fields"]] == ["code", "title", "notes", "opened_on", "closed_at", "score_x100", "weight",
                                                  "items", "passed", "flagged", "status"]
    assert [r["key"] for r in tree["relations"]] == ["assignee", "kind", "reviewer", "site"]      # by label: Assigned to, Kind, Reviewer, Site


def test_a_relation_is_a_column_that_shows_a_display_value_and_a_branch_to_the_rest_of_its_record(cat):
    tree = field_tree(cat, TICKETS)
    assignee = find(tree, "assignee")
    assert (assignee["label"], assignee["path_label"], assignee["kind"], assignee["choices"]) == ("Assigned to", "Assigned to", "text", "records")
    assert [o["name"] for o in assignee["operators"]] == ["is_any_of"]            # a relation is filtered by a choice of records
    children = assignee["children"]
    assert [f["key"] for f in children["fields"]] == ["assignee.email"]           # not assignee.name: that is the relation itself
    assert [r["key"] for r in children["relations"]] == ["assignee.team"]
    assert find(tree, "assignee.team.unit")["path_label"] == "Assigned to › Team › Unit"


def test_every_key_offered_is_one_a_request_accepts_and_nothing_denied_is_offered(cat):
    offered = keys(field_tree(cat, TICKETS))
    for key in offered:
        assert cat.resolve("ticket", key)
    assert len(offered) == len(set(offered))                                       # each column once
    for hidden in ("deleted_at", "assignee.secret", "assignee.team.secret", "site.deleted_at", "id", "assignee_id", "assignee.id"):
        assert hidden not in offered


def test_the_same_table_in_several_roles_is_offered_under_each_role(cat):
    offered = keys(field_tree(cat, TICKETS))
    assert {"assignee.email", "reviewer.email", "site.lead.email", "site.area.lead.email", "site.area.region.head.email"} <= set(offered)
    assert "site.area.region.head.team.unit" in offered                             # six relations deep, the limit


def test_the_depth_limit_and_a_table_that_cannot_be_entered_cut_the_tree(conn, monkeypatch):
    monkeypatch.setattr(registry, "MAX_DEPTH", 3)
    short = keys(field_tree(catalog(conn), TICKETS))
    assert "site.area.region" in short and "site.area.region.head" not in short
    tables = {**TABLES, "person": TableDef("person", "name", {"name": FieldDef(Text())}, walkable=False)}
    closed = field_tree(Catalog(conn, tables), TICKETS)
    assignee = find(closed, "assignee")
    assert assignee["children"] is None and assignee["choices"] == "records"       # still a column, with nothing to enter


def test_the_kind_of_each_column_decides_its_operators_and_choices(cat):
    tree = field_tree(cat, TICKETS)
    operators = lambda key: [o["name"] for o in find(tree, key)["operators"]]
    assert operators("title") == ["contains", "equals", "is_empty", "is_not_empty"]
    assert operators("items") == ["equals", "at_least", "at_most", "between", "is_empty"]
    assert operators("opened_on") == ["before", "after", "between", "is_empty"]
    assert operators("closed_at") == ["before", "after", "between", "is_empty"]
    assert operators("passed") == ["is_yes", "is_no", "is_empty"]                  # it can be empty
    assert operators("flagged") == ["is_yes", "is_no"]                             # it cannot
    status = find(tree, "status")
    assert (status["choices"], status["values"], operators("status")) == ("values", ["Open", "Active", "Closed"], ["is_any_of"])
    assert find(tree, "title")["choices"] is None
    assert find(tree, "score_x100")["scale"] == 2 and find(tree, "items")["scale"] is None
    assert find(tree, "opened_on")["operators"][0] == {"name": "before", "label": "is before"}


def test_a_view_that_works_a_value_out_is_offered_like_any_table(conn):
    tree = field_tree(catalog(conn), READINGS)
    assert {"worked", "amount", "label", "taken_on"} <= {f["key"] for f in tree["fields"]}
    assert find(tree, "worked")["kind"] == "amount" and find(tree, "measure")["choices"] == "records"


# -- choices --

def options(conn, cat, key, definition=TICKETS):
    result = query.choices(conn, cat, definition, key)
    return result["options"]


def test_a_relation_offers_the_records_the_lists_rows_point_at_and_never_a_null(conn, cat):
    live = [r for r in conn.execute("SELECT assignee_id FROM ticket WHERE deleted_at IS NULL")]
    expected = {r["assignee_id"] for r in live if r["assignee_id"] is not None}
    result = query.choices(conn, cat, TICKETS, "assignee")
    assert result["kind"] == "records" and result["more"] is False
    assert {o["id"] for o in result["options"]} == expected
    assert all(o["id"] is not None and o["value"] for o in result["options"])


def test_a_record_only_the_hidden_rows_point_at_is_not_offered():
    fresh = build(tickets=40)
    fresh.execute("INSERT INTO person (name, email, team_id) VALUES ('Only Deleted', 'only@example.test', 1)")
    only = fresh.execute("SELECT id FROM person WHERE name = 'Only Deleted'").fetchone()[0]
    fresh.execute("UPDATE ticket SET assignee_id = ?, deleted_at = '2026-01-01T00:00:00Z' WHERE id = 1", (only,))
    cat_fresh = catalog(fresh)
    assert only not in {o["id"] for o in query.choices(fresh, cat_fresh, TICKETS, "assignee")["options"]}   # the list leaves ticket 1 out
    assert only in {r["id"] for r in fresh.execute("SELECT id FROM person")}                                  # though the record exists


def test_choices_are_in_order_without_regard_to_case_and_a_shared_name_is_told_apart(conn, cat):
    result = options(conn, cat, "assignee")
    assert result == sorted(result, key=lambda o: (o["value"].lower(), o["id"]))                # by name without case, then by id
    by_name = {}
    for o in result:
        by_name.setdefault(o["value"], []).append(o)
    twins = by_name["Avery Reed"]
    assert len(twins) == 2 and len({t["id"] for t in twins}) == 2                              # two people, one display value
    assert {t["detail"] for t in twins} == {"p0@example.test", "p7@example.test"}              # the table's tell-apart column


def test_a_table_with_no_tell_apart_column_gives_no_detail(conn, cat):
    assert all(o["detail"] is None for o in options(conn, cat, "site"))


def test_a_relation_deep_in_a_path_offers_what_the_rows_reach_through_it(conn, cat):
    reached = {r[0] for r in conn.execute(
        "SELECT DISTINCT a.lead_id FROM ticket t JOIN site s ON s.id = t.site_id JOIN area a ON a.id = s.area_id "
        "WHERE t.deleted_at IS NULL AND a.lead_id IS NOT NULL")}
    assert {o["id"] for o in options(conn, cat, "site.area.lead")} == reached


def test_the_lists_own_scope_applies(conn, cat):
    scoped = ListDef("scoped", "ticket", ("code",), ("code", "asc"), source="ticket_live", scope="b.items > 4")
    reached = {r[0] for r in conn.execute("SELECT DISTINCT kind_id FROM ticket WHERE deleted_at IS NULL AND items > 4")}
    assert {o["id"] for o in options(conn, cat, "kind", scoped)} == reached and reached
    nothing = ListDef("nothing", "ticket", ("code",), ("code", "asc"), source="ticket_live", scope="b.items > 99")
    assert options(conn, cat, "kind", nothing) == []                                   # a scope that leaves no rows offers no choices


def test_a_choice_of_declared_values_is_those_values(conn, cat):
    assert query.choices(conn, cat, TICKETS, "status") == {"kind": "values", "values": ["Open", "Active", "Closed"], "options": [], "more": False}


@pytest.mark.parametrize("key", ["title", "items", "passed", "opened_on", "score_x100"])
def test_a_column_with_nothing_to_pick_from_has_no_choices(conn, cat, key):
    with pytest.raises(ValidationError, match="no list of choices"):
        query.choices(conn, cat, TICKETS, key)


@pytest.mark.parametrize("key", ["nope", "deleted_at", "assignee.secret", "assignee.team.secret", "", "a" * 300])
def test_a_column_that_is_not_one_is_refused(conn, cat, key):
    with pytest.raises(ValidationError):
        query.choices(conn, cat, TICKETS, key)


def test_a_long_list_of_choices_is_cut_and_says_so(conn, cat, monkeypatch):
    monkeypatch.setattr(query, "CHOICE_LIMIT", 3)
    result = query.choices(conn, cat, TICKETS, "assignee")
    assert len(result["options"]) == 3 and result["more"] is True
    monkeypatch.setattr(query, "CHOICE_LIMIT", 1000)
    assert query.choices(conn, cat, TICKETS, "assignee")["more"] is False
