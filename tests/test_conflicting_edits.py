"""Conflicting edits of a balance (#10): a change is refused, writing nothing, unless the balance is still what the person
opened. Synthetic data only."""

from datetime import date

import pytest

from northstar import balances, db, sessions, users
from conftest import add_account, op, with_db
from test_concurrency import Other, Paused, path_of

ASSET = 1
TODAY = date(2026, 10, 30)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr("northstar.clock.today", lambda: TODAY)


@pytest.fixture
def account(client):
    with with_db(client) as conn:
        account_id = add_account(conn, "Demo Savings", ASSET, "Savings")
        conn.commit()
    for day, amount in (("2026-02-28", "900.00"), ("2026-03-31", "1000.00")):
        assert client.post(f"/api/accounts/{account_id}/balances", json={"date": day, "amount": amount}).status_code == 200
    return account_id


def page(client, account_id):
    return client.get(f"/api/accounts/{account_id}").json()


def loaded(client, account_id, day):
    """The balance as the account page shows it, with the version a page would send back."""
    return next(b for b in page(client, account_id)["balances"] if b["as_of_date"] == day)


def edit(client, balance, amount, **over):
    return client.patch(f"/api/balances/{balance['id']}", json={
        "date": balance["as_of_date"], "amount": amount, "version": balance["version"], **over})


def remove(client, balance, version=None):
    return client.delete(f"/api/balances/{balance['id']}", params={"version": balance["version"] if version is None else version})


def everything(client):
    with with_db(client) as conn:
        return ([tuple(row) for row in conn.execute("SELECT * FROM balances ORDER BY id")],
                conn.execute("SELECT COUNT(*) FROM sys_operations").fetchone()[0],
                conn.execute("SELECT COUNT(*) FROM sys_record_changes").fetchone()[0])


@pytest.fixture
def second_admin(client):
    """A second admin, and a way to act as them. The client acts as the first until it is told otherwise."""
    with with_db(client) as conn:
        first = conn.execute("SELECT id FROM users WHERE email = 'test@example.com'").fetchone()[0]
        other = users.create_user(op(conn), "second@example.com", "Sam Example", "test-password-123", is_admin=True)
        conn.commit()

    def act_as(who):
        with with_db(client) as conn:
            client.cookies.set("northstar_session", sessions.create_session(conn, first if who == "first" else other))
    return act_as


def sams_edit(client, second_admin, account_id, day, amount):
    """Sam changes a balance, then the first admin carries on."""
    second_admin("second")
    assert edit(client, loaded(client, account_id, day), amount).status_code == 200
    second_admin("first")


# -- the account page carries versions, and they are sent back --

def test_the_account_page_and_the_update_screen_carry_each_balances_version(client, account):
    entry = loaded(client, account, "2026-03-31")
    assert isinstance(entry["version"], int) and entry["version"] > 0
    rows = client.get("/api/balances/update", params={"date": "2026-03-31"}).json()["rows"]
    assert rows[0]["existing_version"] == entry["version"]
    assert client.get("/api/balances/update", params={"date": "2026-04-01"}).json()["rows"][0]["existing_version"] is None


def test_an_edit_and_a_delete_must_say_which_version_they_loaded(client, account):
    entry = loaded(client, account, "2026-03-31")
    before = everything(client)
    assert client.patch(f"/api/balances/{entry['id']}", json={"date": "2026-03-31", "amount": "1"}).status_code == 422
    assert client.delete(f"/api/balances/{entry['id']}").status_code == 422
    assert client.post("/api/balances/update", json={"date": "2026-03-31", "amounts": {str(account): "1"}}).status_code == 422
    assert everything(client) == before


# -- edit --

def test_an_edit_at_the_version_it_loaded_is_saved_and_the_next_one_needs_the_new_version(client, account):
    entry = loaded(client, account, "2026-03-31")
    assert edit(client, entry, "1100.00").status_code == 200
    assert edit(client, entry, "1200.00").status_code == 409                       # still holding the old version
    assert edit(client, loaded(client, account, "2026-03-31"), "1200.00").status_code == 200


def test_an_edit_of_a_balance_changed_since_is_refused_and_says_what_it_is_now_and_who_changed_it(client, account, second_admin):
    entry = loaded(client, account, "2026-03-31")
    sams_edit(client, second_admin, account, "2026-03-31", "1200.00")
    before = everything(client)
    response = edit(client, entry, "1050.00", note="mine")
    assert response.status_code == 409
    [conflict] = response.json()["conflicts"]
    assert response.json()["reason"] == "conflict"
    assert (conflict["kind"], conflict["account_name"], conflict["date"], conflict["amount_cents"], conflict["by"]) == (
        "changed", "Demo Savings", "2026-03-31", 120000, "Sam Example")
    assert conflict["currency"] == {"code": "USD", "name": "US Dollar", "minor_units": 2}
    assert len(conflict["on"]) == 10 and conflict["balance_id"] == entry["id"]
    assert conflict["version"] == loaded(client, account, "2026-03-31")["version"]    # what "Use the current value" sends next
    assert everything(client) == before                                                # nothing was written


def test_the_check_comes_first_even_when_the_new_values_equal_the_current_ones(client, account, second_admin):
    entry = loaded(client, account, "2026-03-31")
    sams_edit(client, second_admin, account, "2026-03-31", "1200.00")
    assert edit(client, entry, "1200.00").status_code == 409


def test_an_edit_of_a_balance_deleted_since_is_refused_and_says_who_deleted_it(client, account, second_admin):
    entry = loaded(client, account, "2026-03-31")
    second_admin("second")
    assert remove(client, loaded(client, account, "2026-03-31")).status_code == 200
    second_admin("first")
    before = everything(client)
    response = edit(client, entry, "1050.00")
    assert response.status_code == 409
    [conflict] = response.json()["conflicts"]
    assert (conflict["kind"], conflict["date"], conflict["amount_cents"], conflict["by"], conflict["account_name"]) == (
        "deleted", "2026-03-31", None, "Sam Example", "Demo Savings")
    assert everything(client) == before


def test_a_deleted_user_is_still_named(client, account, second_admin):
    entry = loaded(client, account, "2026-03-31")
    sams_edit(client, second_admin, account, "2026-03-31", "1200.00")
    with with_db(client) as conn:
        conn.execute("UPDATE users SET deleted = 1 WHERE email = 'second@example.com'")
        conn.commit()
    assert edit(client, entry, "1.00").json()["conflicts"][0]["by"] == "Sam Example"


def test_a_balance_that_never_existed_is_not_found_and_a_closed_account_is_still_refused_as_before(client, account):
    assert client.patch("/api/balances/9999", json={"date": "2026-01-01", "amount": "1", "version": 0}).status_code == 404
    with with_db(client) as conn:
        conn.execute("UPDATE accounts SET is_open = 0 WHERE id = ?", (account,))
        conn.commit()
    entry = loaded(client, account, "2026-03-31")
    response = edit(client, entry, "1.00")
    assert response.status_code == 422 and "closed" in response.text


# -- delete --

def test_a_delete_at_the_version_it_loaded_goes_through(client, account):
    assert remove(client, loaded(client, account, "2026-03-31")).status_code == 200
    assert [b["as_of_date"] for b in page(client, account)["balances"]] == ["2026-02-28"]


def test_a_delete_of_a_balance_changed_since_is_refused_and_nothing_is_deleted(client, account, second_admin):
    entry = loaded(client, account, "2026-03-31")
    sams_edit(client, second_admin, account, "2026-03-31", "1200.00")
    before = everything(client)
    response = remove(client, entry)
    assert response.status_code == 409 and response.json()["conflicts"][0]["kind"] == "changed"
    assert everything(client) == before


def test_a_delete_of_a_balance_already_deleted_is_a_conflict_not_a_not_found(client, account, second_admin):
    entry = loaded(client, account, "2026-03-31")
    second_admin("second")
    remove(client, loaded(client, account, "2026-03-31"))
    second_admin("first")
    response = remove(client, entry)
    assert response.status_code == 409 and response.json()["conflicts"][0]["kind"] == "deleted"


# -- the Update screen --

def update(client, day, amounts, versions):
    return client.post("/api/balances/update", json={
        "date": day, "amounts": {str(k): v for k, v in amounts.items()}, "versions": {str(k): v for k, v in versions.items()}})


@pytest.fixture
def household(client, account):
    with with_db(client) as conn:
        other = add_account(conn, "Demo Brokerage", ASSET, "Brokerage")
        third = add_account(conn, "Demo Checking", ASSET, "Checking")
        conn.commit()
    return {"savings": account, "brokerage": other, "checking": third}


def versions_on(client, day):
    rows = client.get("/api/balances/update", params={"date": day}).json()["rows"]
    return {row["id"]: row["existing_version"] for row in rows}


def test_a_save_with_the_versions_it_loaded_goes_through(client, household):
    got = update(client, "2026-03-31", {household["savings"]: "1,100.00", household["brokerage"]: "5000"}, versions_on(client, "2026-03-31"))
    assert got.status_code == 200 and got.json()["saved"] == {"added": 1, "updated": 1, "unchanged": 0}


def test_a_balance_changed_since_refuses_the_whole_save_and_names_it(client, household, second_admin):
    versions = versions_on(client, "2026-03-31")
    sams_edit(client, second_admin, household["savings"], "2026-03-31", "1200.00")
    before = everything(client)
    got = update(client, "2026-03-31", {household["savings"]: "1,050.00", household["checking"]: "2400"}, versions)
    assert got.status_code == 409
    [conflict] = got.json()["conflicts"]
    assert (conflict["kind"], conflict["account_id"], conflict["amount_cents"], conflict["by"]) == (
        "changed", household["savings"], 120000, "Sam Example")
    assert everything(client) == before          # the checking balance that did not conflict was not saved either


def test_a_balance_added_since_to_a_date_that_had_none_is_a_conflict(client, household, second_admin):
    versions = versions_on(client, "2026-03-31")
    assert versions[household["brokerage"]] is None
    second_admin("second")
    assert update(client, "2026-03-31", {household["brokerage"]: "5000"}, versions_on(client, "2026-03-31")).status_code == 200
    second_admin("first")
    before = everything(client)
    got = update(client, "2026-03-31", {household["brokerage"]: "5100"}, versions)
    assert got.status_code == 409
    [conflict] = got.json()["conflicts"]
    assert (conflict["kind"], conflict["amount_cents"], conflict["by"]) == ("added", 500000, "Sam Example")
    assert everything(client) == before


def test_a_balance_deleted_since_is_a_conflict_that_says_who_deleted_it(client, household, second_admin):
    versions = versions_on(client, "2026-03-31")
    second_admin("second")
    assert remove(client, loaded(client, household["savings"], "2026-03-31")).status_code == 200
    second_admin("first")
    got = update(client, "2026-03-31", {household["savings"]: "1,050.00"}, versions)
    assert got.status_code == 409
    [conflict] = got.json()["conflicts"]
    assert (conflict["kind"], conflict["date"], conflict["by"]) == ("deleted", "2026-03-31", "Sam Example")


def test_every_conflicting_row_is_named_in_one_refusal(client, household, second_admin):
    update(client, "2026-03-31", {household["brokerage"]: "5000"}, versions_on(client, "2026-03-31"))
    versions = versions_on(client, "2026-03-31")
    sams_edit(client, second_admin, household["savings"], "2026-03-31", "1200.00")
    sams_edit(client, second_admin, household["brokerage"], "2026-03-31", "5001.00")
    got = update(client, "2026-03-31", {household["savings"]: "1", household["brokerage"]: "2", household["checking"]: "3"}, versions)
    assert got.status_code == 409
    assert {c["account_id"] for c in got.json()["conflicts"]} == {household["savings"], household["brokerage"]}
    assert "2 balances changed" in got.json()["detail"]


def test_a_row_that_is_not_sent_is_never_checked(client, household, second_admin):
    versions = versions_on(client, "2026-03-31")
    sams_edit(client, second_admin, household["savings"], "2026-03-31", "1200.00")
    got = update(client, "2026-03-31", {household["checking"]: "2400"}, {household["checking"]: versions[household["checking"]]})
    assert got.status_code == 200


def test_saving_again_with_the_newer_versions_replaces_what_the_other_person_did(client, household, second_admin):
    versions = versions_on(client, "2026-03-31")
    sams_edit(client, second_admin, household["savings"], "2026-03-31", "1200.00")
    assert update(client, "2026-03-31", {household["savings"]: "1,050.00"}, versions).status_code == 409
    assert update(client, "2026-03-31", {household["savings"]: "1,050.00"}, versions_on(client, "2026-03-31")).status_code == 200
    assert loaded(client, household["savings"], "2026-03-31")["amount_cents"] == 105000


def test_a_sent_row_with_no_version_listed_is_taken_to_expect_no_balance(client, household):
    got = client.post("/api/balances/update", json={"date": "2026-03-31", "amounts": {str(household["savings"]): "1"}, "versions": {}})
    assert got.status_code == 409 and got.json()["conflicts"][0]["kind"] == "added"


# -- the check and the write are one step --

def test_a_change_made_while_an_edit_is_between_its_check_and_its_write_waits_and_lands_after_it(client, account):
    entry = loaded(client, account, "2026-03-31")
    with with_db(client) as conn:
        path = path_of(conn)
        other = Other(path, lambda c: balances.update_balance(op(c), entry["id"], "2026-03-31", "7777.00", None, TODAY))
        paused = Paused(db.connect(path), "FROM live_balances WHERE id = ?", other.start_and_wait_a_moment)
        balances.update_balance(op(paused), entry["id"], "2026-03-31", "1100.00", None, TODAY, entry["version"])
        other.join()
        changes = [tuple(row) for row in conn.execute(
            "SELECT json_extract(old_json, '$.amount_cents'), json_extract(new_json, '$.amount_cents') FROM sys_record_changes "
            "WHERE tablename = 'balances' AND record_id = ? AND change = 'UPDATE' ORDER BY id", (entry["id"],))]
    assert changes == [(100000, 110000), (110000, 777700)]       # mine first, then the other, which waited for it
