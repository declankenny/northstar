"""The admin Deleted accounts list and restoring an account (#270): what is listed and when it goes, a restore that brings back the balances its
deletion hid and no others, a name used since, an account that stays closed, and who may do any of it. Synthetic data only."""

from datetime import date, datetime, timedelta, timezone

from northstar import accounts, balances
from conftest import add_account, op, with_db

ASSET = 1
URL = "/api/deleted-accounts"


def stamp(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def make(client, name, deleted_days_ago=None, balances_on=("2026-01-31",), closed=False):
    with with_db(client) as conn:
        account_id = add_account(conn, name, ASSET, "Savings")
        for i, day in enumerate(balances_on):
            balances.record_balance(op(conn), account_id, date.fromisoformat(day), 100_000 + i)
        if closed:
            conn.execute("UPDATE accounts SET is_open = 0 WHERE id = ?", (account_id,))
        if deleted_days_ago is not None:
            accounts.delete_account(op(conn), account_id)
            conn.execute("UPDATE accounts SET updated_at = ? WHERE id = ?", (stamp(deleted_days_ago), account_id))
        conn.commit()
    return account_id


def listed(client):
    response = client.get(URL)
    assert response.status_code == 200
    return response.json()


def live(client, account_id):
    with with_db(client) as conn:
        return conn.execute("SELECT 1 FROM live_accounts WHERE id = ?", (account_id,)).fetchone() is not None


def restore(client, account_id, **body):
    return client.post(f"{URL}/{account_id}/restore", json=body)


def row(client, account_id):
    with with_db(client) as conn:
        return tuple(conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone())


# -- the list --

def test_it_lists_deleted_accounts_newest_first_and_never_a_live_one(client):
    older = make(client, "Older", 40)
    newer = make(client, "Newer", 3)
    make(client, "Still here")
    data = listed(client)
    assert [a["id"] for a in data["accounts"]] == [newer, older]
    assert data["cleanup_on"] is True and data["retention_days"] == 90


def test_each_row_says_when_it_was_deleted_and_when_it_goes_for_good(client):
    gone = make(client, "Gone", 10, balances_on=("2026-01-31", "2026-02-28"))
    [entry] = listed(client)["accounts"]
    assert entry["id"] == gone and entry["type_name"] == "Savings" and entry["balance_count"] == 2
    assert entry["deleted_on"] == stamp(10)[:10]


def purge_on(client, deleted_at, zone=None, start="03:00", days=None):
    """The date the list gives for an account deleted at a fixed UTC moment, under a zone and a start time (90 days unless `days`)."""
    gone = make(client, "Gone", 5)
    with with_db(client) as conn:
        conn.execute("UPDATE accounts SET updated_at = ? WHERE id = ?", (deleted_at, gone))
        conn.execute("UPDATE system_properties SET value = ? WHERE name = 'data.deleted.cleanup_time'", (start,))
        if zone:
            conn.execute("UPDATE system_properties SET value = ? WHERE name = 'system.timezone'", (zone,))
        if days:
            conn.execute("UPDATE system_properties SET value = ? WHERE name = 'data.deleted.retention_days'", (str(days),))
        conn.commit()
    return listed(client)["accounts"][0]["purge_on"]


def test_the_date_is_the_first_cleanup_run_after_the_period_ends_not_the_day_it_ends(client):
    # 90 days after August 17 is November 15. Deleted at noon, the period ends at noon, after that day's 03:00 run, so the run is on the 16th.
    assert purge_on(client, "2026-08-17T12:00:00Z") == "2026-11-16"


def test_a_period_that_ends_before_the_start_time_is_removed_by_that_days_run(client):
    assert purge_on(client, "2026-08-17T01:00:00Z") == "2026-11-15"


def test_the_start_time_is_read_in_the_installations_zone(client):
    # The period ends at 06:00 UTC on November 15: after the 03:00 run in UTC (so the 16th), but 01:00 in New York in November, before it (so the 15th).
    assert purge_on(client, "2026-08-17T06:00:00Z", zone="America/New_York") == "2026-11-15"


def test_the_same_moment_in_utc_gives_the_next_date(client):
    assert purge_on(client, "2026-08-17T06:00:00Z") == "2026-11-16"


def test_a_period_that_is_beyond_a_date_has_no_date(client):
    assert purge_on(client, "2026-08-17T12:00:00Z", days=999999999) is None


def test_with_the_cleanup_switched_off_nothing_is_scheduled(client):
    make(client, "Gone", 10)
    with with_db(client) as conn:
        conn.execute("UPDATE system_properties SET value = NULL WHERE name = 'data.deleted.cleanup_time'")
        conn.commit()
    data = listed(client)
    assert data["cleanup_on"] is False and data["accounts"][0]["purge_on"] is None


def test_the_list_is_empty_when_nothing_is_deleted(client):
    make(client, "Live")
    assert listed(client)["accounts"] == []


def test_a_closed_account_is_shown_as_closed(client):
    make(client, "Closed one", 5, closed=True)
    assert listed(client)["accounts"][0]["is_open"] is False


# -- restoring --

def test_restoring_brings_the_account_back_with_the_balances_its_deletion_hid(client):
    gone = make(client, "Gone", 10, balances_on=("2026-01-31", "2026-02-28"))
    response = restore(client, gone)
    assert response.status_code == 200 and response.json() == {"id": gone, "name": "Gone", "balance_count": 2}
    assert live(client, gone) and listed(client)["accounts"] == []
    with with_db(client) as conn:
        assert conn.execute("SELECT COUNT(*) FROM live_balances WHERE account_id = ?", (gone,)).fetchone()[0] == 2


def test_a_balance_deleted_on_its_own_before_the_account_stays_deleted(client):
    gone = make(client, "Gone", None, balances_on=("2026-01-31", "2026-02-28"))
    with with_db(client) as conn:
        first = conn.execute("SELECT id FROM balances WHERE account_id = ? AND as_of_date = '2026-01-31'", (gone,)).fetchone()[0]
        balances.delete_balance(op(conn), first)
        accounts.delete_account(op(conn), gone)
        conn.commit()
    assert restore(client, gone).json()["balance_count"] == 1
    with with_db(client) as conn:
        assert [r[0] for r in conn.execute("SELECT as_of_date FROM live_balances WHERE account_id = ?", (gone,))] == ["2026-02-28"]


def test_a_closed_account_is_restored_closed(client):
    gone = make(client, "Closed one", 5, closed=True)
    assert restore(client, gone).status_code == 200
    with with_db(client) as conn:
        assert conn.execute("SELECT is_open FROM live_accounts WHERE id = ?", (gone,)).fetchone()[0] == 0


def test_the_restore_is_one_operation_of_its_kind_by_the_person_who_did_it(client):
    gone = make(client, "Gone", 5)
    restore(client, gone)
    with with_db(client) as conn:
        kind, detail, user = conn.execute("SELECT kind, detail, user_id FROM sys_operations ORDER BY id DESC LIMIT 1").fetchone()
        assert kind == "restore" and f'"record_id": {gone}' in detail
        assert user == conn.execute("SELECT id FROM users WHERE email = 'test@example.com'").fetchone()[0]
        assert conn.execute("SELECT old_json FROM sys_record_changes WHERE tablename = 'accounts' AND record_id = ? "
                            "ORDER BY id DESC LIMIT 1", (gone,)).fetchone()[0] == '{"deleted": 1}'


def test_an_account_that_is_not_deleted_cannot_be_restored(client):
    live_one = make(client, "Live")
    assert restore(client, live_one).status_code == 404
    assert restore(client, 9999).status_code == 404


def test_restoring_twice_refuses_the_second(client):
    gone = make(client, "Gone", 5)
    assert restore(client, gone).status_code == 200
    assert restore(client, gone).status_code == 404


# -- a name used since --

def test_a_name_in_use_is_flagged_and_refused_without_a_new_one(client):
    gone = make(client, "Savings pot", 5)
    other = make(client, "savings POT")          # ASCII case is folded
    assert listed(client)["accounts"][0]["name_taken"] is True
    before = row(client, gone)
    response = restore(client, gone)
    assert response.status_code == 422 and "already exists" in response.json()["detail"]
    assert row(client, gone) == before and not live(client, gone) and live(client, other)


def test_a_new_name_restores_it_and_the_other_account_is_left_alone(client):
    gone = make(client, "Savings pot", 5)
    other = make(client, "Savings POT")
    other_before = row(client, other)
    response = restore(client, gone, name="Savings pot (old)")
    assert response.status_code == 200 and response.json()["name"] == "Savings pot (old)"
    assert row(client, other) == other_before
    with with_db(client) as conn:
        assert conn.execute("SELECT name FROM live_accounts WHERE id = ?", (gone,)).fetchone()[0] == "Savings pot (old)"


def test_the_new_name_is_checked_too_and_a_blank_one_is_refused(client):
    gone = make(client, "Pot", 5)
    make(client, "Taken")
    assert restore(client, gone, name="Taken").status_code == 422
    assert restore(client, gone, name="  ").status_code == 422
    assert not live(client, gone)


def test_a_name_taken_after_the_list_was_drawn_is_caught_at_save_time(client):
    gone = make(client, "Pot", 5)
    assert listed(client)["accounts"][0]["name_taken"] is False
    make(client, "Pot")                          # in between
    assert restore(client, gone).status_code == 422 and not live(client, gone)


# -- nothing writes to a deleted account --

def test_nothing_that_reads_or_fails_writes_to_a_deleted_accounts_row(client):
    gone = make(client, "Pot", 5)
    make(client, "Pot")
    before = row(client, gone)
    listed(client)
    restore(client, gone)                        # refused
    restore(client, gone, name="")
    assert row(client, gone) == before


# -- who may --

def test_only_an_admin_can_list_or_restore_including_direct_requests(member_client, anon_client):
    assert member_client.get(URL).status_code == 403
    assert member_client.post(f"{URL}/1/restore", json={}).status_code == 403
    assert anon_client.get(URL).status_code == 401
    assert anon_client.post(f"{URL}/1/restore", json={}).status_code == 401
