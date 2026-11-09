"""Saved filters: who may make, see and change them, the default a list opens with, and what the database refuses by itself.
Synthetic data only."""

import json
import sqlite3

import pytest

from northstar import list_filters
from northstar.errors import NotAllowedError, NotFoundError, ValidationError
from northstar.listdefs import catalog as household_catalog
from northstar.lists.listdef import ListDef
from northstar.writer import Operation

DEFINITION = ListDef("filters_test", "live_balance_values", ("as_of_date", "account"), ("as_of_date", "desc"))
OTHER = ListDef("filters_other", "live_balance_values", ("as_of_date", "account"), ("as_of_date", "desc"))
SYSTEM = "(SELECT id FROM users WHERE is_system = 1)"
TYPES = [{"field": "account.type", "operator": "is_any_of", "value": [1]}]
RECENT = [{"field": "as_of_date", "operator": "after", "value": "2025-12-31"}]


def person(conn, email, admin=False):
    return conn.execute(f"INSERT INTO users (email, display_name, password_hash, is_admin, created_by, updated_by) "
                        f"VALUES (?, ?, '!', ?, {SYSTEM}, {SYSTEM})", (email, email.split("@")[0], int(admin))).lastrowid


@pytest.fixture
def people(conn):
    return {"ann": person(conn, "ann@example.test"), "ben": person(conn, "ben@example.test"), "root": person(conn, "root@example.test", True)}


@pytest.fixture
def cat(conn):
    return household_catalog(conn)


def op(conn, user):
    return Operation(conn, user, "ui_edit")


def save(conn, cat, user, name, conditions=TYPES, *, shared=False, admin=False, definition=DEFINITION):
    return list_filters.create(op(conn, user), cat, definition, name, conditions, shared=shared, is_admin=admin)


def row(conn, filter_id):
    return conn.execute("SELECT * FROM list_filters WHERE id = ?", (filter_id,)).fetchone()


def operations(conn):
    return conn.execute("SELECT COUNT(*) FROM sys_operations").fetchone()[0]


# -- saving --

def test_a_person_saves_a_private_filter_and_it_is_logged(conn, cat, people):
    start = operations(conn)
    filter_id = save(conn, cat, people["ann"], "  Savings  ", TYPES + RECENT)
    saved = row(conn, filter_id)
    assert (saved["owner_id"], saved["list_key"], saved["name"], saved["is_default"]) == (people["ann"], "filters_test", "Savings", 0)
    assert json.loads(saved["conditions"]) == TYPES + RECENT
    assert saved["conditions"] == json.dumps(TYPES + RECENT, separators=(",", ":"))      # compact, and the same however it was sent
    assert operations(conn) == start + 1
    change = conn.execute("SELECT * FROM sys_record_changes WHERE tablename = 'list_filters'").fetchone()
    assert change["change"] == "INSERT" and json.loads(change["new_json"])["name"] == "Savings"


@pytest.mark.parametrize("conditions, message", [
    ("not a list", "list of conditions"),
    ([{"field": "no_such_column", "operator": "equals", "value": 1}], "not a column"),
    ([{"field": "note", "operator": "no_such_operator", "value": "x"}], "cannot be filtered with"),
    ([{"field": "account.created_by.email", "operator": "contains", "value": "x"}], "only shows its name"),
    ([{"field": "note", "operator": "contains", "value": "x", "extra": 1}], "needs a field"),
    ([{"field": "as_of_date", "operator": "between", "value": ["2026-02-01", "2026-01-01"]}], "ends before"),
    ([{"field": "account", "operator": "is_any_of", "value": ["Test"]}], "Choose from the list"),
    ([{"field": "note", "operator": "contains", "value": "x"}] * 2, "one filter"),
    ([{"field": "note", "operator": "contains", "value": "x" * 200}] * 1 + [{"field": "source", "operator": "contains", "value": "y"}] * 0, None),
])
def test_conditions_the_list_would_refuse_are_refused_when_they_are_saved(conn, cat, people, conditions, message):
    if message is None:
        save(conn, cat, people["ann"], "Long value")            # a long value is allowed up to the size of the whole filter
        return
    with pytest.raises(ValidationError, match=message):
        save(conn, cat, people["ann"], "Bad", conditions)
    assert conn.execute("SELECT COUNT(*) FROM list_filters").fetchone()[0] == 0


def test_a_filter_too_big_to_store_is_refused(conn, cat, people):
    huge = [{"field": "account", "operator": "is_any_of", "value": list(range(1, 6000))}]
    with pytest.raises(ValidationError, match="too long to save"):
        save(conn, cat, people["ann"], "Huge", huge)


@pytest.mark.parametrize("name, message", [("", "Give the filter a name"), ("   ", "Give the filter a name"), (None, "Give the filter a name"),
                                           ("x" * 81, "at most 80"), ("bad\nname", "control characters"), (5, "Give the filter a name")])
def test_a_name_is_a_few_ordinary_characters(conn, cat, people, name, message):
    with pytest.raises(ValidationError, match=message):
        save(conn, cat, people["ann"], name)
    save(conn, cat, people["ann"], "x" * 80)                              # exactly the limit


def test_a_name_is_unique_for_one_owner_and_list_ignoring_case_but_not_across_them(conn, cat, people):
    save(conn, cat, people["ann"], "Savings")
    with pytest.raises(ValidationError, match='already a filter called "SAVINGS"'):
        save(conn, cat, people["ann"], "SAVINGS")
    save(conn, cat, people["ben"], "savings")                               # another person's own
    save(conn, cat, people["ann"], "Savings", definition=OTHER)             # another list
    save(conn, cat, people["root"], "Savings", shared=True, admin=True)     # a shared one is separate from a private one
    with pytest.raises(ValidationError, match="already a filter called"):
        save(conn, cat, people["root"], "SAVINGS", shared=True, admin=True)


def test_there_is_a_limit_to_how_many_a_person_keeps_for_one_list(conn, cat, people, monkeypatch):
    monkeypatch.setattr(list_filters, "MAX_PER_SCOPE", 3)
    for number in range(3):
        save(conn, cat, people["ann"], f"Filter {number}")
    with pytest.raises(ValidationError, match="at most 3 saved filters"):
        save(conn, cat, people["ann"], "One too many")
    save(conn, cat, people["ben"], "Ben's own")                             # the limit is for one person and one list
    save(conn, cat, people["ann"], "Elsewhere", definition=OTHER)


# -- who may see and change what --

def test_a_filter_for_everyone_is_for_admins_to_make_change_and_remove_and_everyone_sees_it(conn, cat, people):
    with pytest.raises(NotAllowedError, match="Only admins can save a filter for everyone"):
        save(conn, cat, people["ann"], "For all", shared=True, admin=False)
    shared = save(conn, cat, people["root"], "For all", shared=True, admin=True)
    assert row(conn, shared)["owner_id"] is None
    for user in people.values():
        assert [r["name"] for r in list_filters.visible(conn, user, "filters_test")] == ["For all"]
    ann = op(conn, people["ann"])
    with pytest.raises(NotAllowedError, match="Only admins can change"):
        list_filters.update(ann, cat, DEFINITION, shared, is_admin=False, name="Mine now")
    with pytest.raises(NotAllowedError):
        list_filters.delete(ann, DEFINITION, shared, is_admin=False)
    list_filters.update(op(conn, people["root"]), cat, DEFINITION, shared, is_admin=True, name="Everyone's")
    assert row(conn, shared)["name"] == "Everyone's"


def test_another_persons_private_filter_is_not_found_not_forbidden_even_to_an_admin(conn, cat, people):
    private = save(conn, cat, people["ann"], "Ann's")
    assert [r["name"] for r in list_filters.visible(conn, people["ann"], "filters_test")] == ["Ann's"]
    for user, admin in ((people["ben"], False), (people["root"], True)):
        assert list_filters.visible(conn, user, "filters_test") == []
        with pytest.raises(NotFoundError):
            list_filters.get(conn, user, "filters_test", private)
        with pytest.raises(NotFoundError):
            list_filters.update(op(conn, user), cat, DEFINITION, private, is_admin=admin, name="Stolen")
        with pytest.raises(NotFoundError):
            list_filters.delete(op(conn, user), DEFINITION, private, is_admin=admin)
    assert row(conn, private)["name"] == "Ann's"


def test_a_filter_belongs_to_its_list(conn, cat, people):
    filter_id = save(conn, cat, people["ann"], "Savings")
    with pytest.raises(NotFoundError):
        list_filters.get(conn, people["ann"], "filters_other", filter_id)
    assert list_filters.visible(conn, people["ann"], "filters_other") == []


def test_visible_filters_are_in_order_by_name_without_regard_to_case(conn, cat, people):
    for name in ("banana", "Apple", "cherry"):
        save(conn, cat, people["ann"], name)
    save(conn, cat, people["root"], "Almond", shared=True, admin=True)
    assert [r["name"] for r in list_filters.visible(conn, people["ann"], "filters_test")] == ["Almond", "Apple", "banana", "cherry"]


# -- changing one --

def test_a_filter_is_renamed_and_its_conditions_replaced_and_each_is_logged(conn, cat, people):
    filter_id = save(conn, cat, people["ann"], "Savings", TYPES)
    start = operations(conn)
    list_filters.update(op(conn, people["ann"]), cat, DEFINITION, filter_id, is_admin=False, name="Savings 2026", conditions=RECENT)
    assert (row(conn, filter_id)["name"], json.loads(row(conn, filter_id)["conditions"])) == ("Savings 2026", RECENT)
    assert operations(conn) == start + 1
    change = conn.execute("SELECT * FROM sys_record_changes WHERE tablename = 'list_filters' AND change = 'UPDATE'").fetchone()
    assert set(json.loads(change["new_json"])) == {"name", "conditions"}


def test_a_save_that_changes_nothing_writes_nothing_and_renaming_to_its_own_name_is_fine(conn, cat, people):
    filter_id = save(conn, cat, people["ann"], "Savings", TYPES)
    start = operations(conn)
    list_filters.update(op(conn, people["ann"]), cat, DEFINITION, filter_id, is_admin=False, name="Savings", conditions=TYPES)
    list_filters.update(op(conn, people["ann"]), cat, DEFINITION, filter_id, is_admin=False, name="SAVINGS")      # case alone is a change
    assert operations(conn) == start + 1 and row(conn, filter_id)["name"] == "SAVINGS"


def test_renaming_to_another_filters_name_is_refused_and_changes_nothing(conn, cat, people):
    save(conn, cat, people["ann"], "First")
    second = save(conn, cat, people["ann"], "Second")
    with pytest.raises(ValidationError, match="already a filter called"):
        list_filters.update(op(conn, people["ann"]), cat, DEFINITION, second, is_admin=False, name="first", conditions=RECENT)
    assert (row(conn, second)["name"], json.loads(row(conn, second)["conditions"])) == ("Second", TYPES)         # not half done


# -- the default --

def test_a_default_is_one_per_person_and_list_and_making_another_moves_the_mark(conn, cat, people):
    first, second = save(conn, cat, people["ann"], "First"), save(conn, cat, people["ann"], "Second")
    update = lambda filter_id, flag: list_filters.update(op(conn, people["ann"]), cat, DEFINITION, filter_id, is_admin=False, is_default=flag)
    update(first, True)
    assert list_filters.default_id(conn, people["ann"], "filters_test") == first
    update(second, True)
    assert (row(conn, first)["is_default"], row(conn, second)["is_default"]) == (0, 1)
    assert list_filters.default_id(conn, people["ann"], "filters_test") == second
    update(second, False)
    assert list_filters.default_id(conn, people["ann"], "filters_test") is None
    with pytest.raises(ValidationError, match="the default or it is not"):
        list_filters.update(op(conn, people["ann"]), cat, DEFINITION, first, is_admin=False, is_default="yes")


def test_a_list_opens_with_the_persons_own_default_else_the_shared_one_else_nothing(conn, cat, people):
    shared = save(conn, cat, people["root"], "Shared", shared=True, admin=True)
    own = save(conn, cat, people["ann"], "Own")
    assert list_filters.default_id(conn, people["ann"], "filters_test") is None
    list_filters.update(op(conn, people["root"]), cat, DEFINITION, shared, is_admin=True, is_default=True)
    assert [list_filters.default_id(conn, people[u], "filters_test") for u in ("ann", "ben", "root")] == [shared, shared, shared]
    list_filters.update(op(conn, people["ann"]), cat, DEFINITION, own, is_admin=False, is_default=True)
    assert list_filters.default_id(conn, people["ann"], "filters_test") == own            # her own wins
    assert list_filters.default_id(conn, people["ben"], "filters_test") == shared         # and does not change anyone else's
    list_filters.update(op(conn, people["ann"]), cat, DEFINITION, own, is_admin=False, is_default=False)
    assert list_filters.default_id(conn, people["ann"], "filters_test") == shared
    assert list_filters.default_id(conn, people["ann"], "filters_other") is None


def test_the_shared_default_moves_too_and_the_marks_are_logged(conn, cat, people):
    first = save(conn, cat, people["root"], "One", shared=True, admin=True)
    second = save(conn, cat, people["root"], "Two", shared=True, admin=True)
    for filter_id in (first, second):
        list_filters.update(op(conn, people["root"]), cat, DEFINITION, filter_id, is_admin=True, is_default=True)
    assert (row(conn, first)["is_default"], row(conn, second)["is_default"]) == (0, 1)
    logged = [json.loads(r["new_json"]) for r in conn.execute("SELECT new_json FROM sys_record_changes WHERE tablename = 'list_filters' AND change = 'UPDATE'")]
    assert logged.count({"is_default": 1}) == 2 and logged.count({"is_default": 0}) == 1


def test_removing_the_default_means_the_list_opens_with_none(conn, cat, people):
    filter_id = save(conn, cat, people["ann"], "Mine")
    list_filters.update(op(conn, people["ann"]), cat, DEFINITION, filter_id, is_admin=False, is_default=True)
    list_filters.delete(op(conn, people["ann"]), DEFINITION, filter_id, is_admin=False)
    assert list_filters.default_id(conn, people["ann"], "filters_test") is None
    assert conn.execute("SELECT COUNT(*) FROM list_filters").fetchone()[0] == 0
    assert conn.execute("SELECT change FROM sys_record_changes WHERE tablename = 'list_filters' ORDER BY id DESC").fetchone()[0] == "DELETE"


# -- what the database refuses even if the application is bypassed --

def test_the_database_allows_one_default_for_each_person_and_list_and_one_shared_default(conn, cat, people):
    def insert(owner, name, default, key="filters_test"):
        conn.execute(f"INSERT INTO list_filters (owner_id, list_key, name, conditions, is_default, created_by, updated_by) "
                     f"VALUES (?, ?, ?, '[]', ?, {SYSTEM}, {SYSTEM})", (owner, key, name, default))
    insert(people["ann"], "A1", 1)
    insert(people["ann"], "A2", 0)
    insert(people["ann"], "A3", 1, key="filters_other")                      # another list
    insert(people["ben"], "B1", 1)                                           # another person
    insert(None, "S1", 1)
    for owner, name in ((people["ann"], "A4"), (None, "S2")):
        with pytest.raises(sqlite3.IntegrityError):
            insert(owner, name, 1)
    insert(None, "S3", 0)                                                    # any number that are not the default


def test_the_database_allows_one_name_for_each_owner_and_list_ignoring_ascii_case(conn, people):
    def insert(owner, name):
        conn.execute(f"INSERT INTO list_filters (owner_id, list_key, name, conditions, created_by, updated_by) "
                     f"VALUES (?, 'filters_test', ?, '[]', {SYSTEM}, {SYSTEM})", (owner, name))
    insert(None, "Same")
    insert(people["ann"], "Same")
    for owner in (None, people["ann"]):
        with pytest.raises(sqlite3.IntegrityError):
            insert(owner, "SAME")


@pytest.mark.parametrize("conditions, name, default", [("not json", "n", 0), ('{"a": 1}', "n", 0), ('"text"', "n", 0), ("[]", "", 0),
                                                       ("[]", "x" * 81, 0), ("[]", "n", 2), ("[" + "1," * 10_000 + "1]", "n", 0)])
def test_the_database_refuses_conditions_that_are_not_a_list_and_names_and_flags_out_of_range(conn, conditions, name, default):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(f"INSERT INTO list_filters (owner_id, list_key, name, conditions, is_default, created_by, updated_by) "
                     f"VALUES (NULL, 'filters_test', ?, ?, ?, {SYSTEM}, {SYSTEM})", (name, conditions, default))


# -- applying a stored filter --

def test_a_stored_filter_is_applied_condition_by_condition_and_one_that_no_longer_fits_is_skipped_with_its_reason(conn, cat, people):
    stored = json.dumps(TYPES + [{"field": "a_column_since_removed", "operator": "equals", "value": 1}] + RECENT)
    kept, skipped = list_filters.usable(cat, DEFINITION, stored)
    assert kept == TYPES + RECENT
    assert len(skipped) == 1 and skipped[0]["field"] == "a_column_since_removed" and "not a column" in skipped[0]["reason"]
    assert list_filters.usable(cat, DEFINITION, "[]") == ([], [])
