"""A liability's payment due day (#258): the rule that checks it, the next due date the database works out, the edit API, the class change
that clears it, the Accounts list column and the migration. Synthetic data only; the dates are worked out by a plain Python calculation."""

import calendar
import json
import shutil
from datetime import date, datetime, timedelta, timezone

import pytest

from northstar import accounts, clock, db
from northstar.errors import ValidationError

from conftest import add_account, add_balance, op, type_id, use_dollars, with_db

LIST = "/api/lists/accounts"
REAL_TODAY = clock.today


def reference(due_day: int, today: date) -> date:
    """The next due date by the rule's plain words: this month's (the day, or the month's last day if it is shorter) when that is today or
    later, otherwise next month's, clamped the same way."""
    year, month = today.year, today.month
    for _ in range(2):
        candidate = date(year, month, min(due_day, calendar.monthrange(year, month)[1]))
        if candidate >= today:
            return candidate
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    raise AssertionError("unreachable: next month's date is always after today")


@pytest.fixture
def clock_on(monkeypatch):
    """Fix the clock's today() and return the setter."""
    current = {"today": date(2026, 11, 15)}
    monkeypatch.setattr(clock, "today", lambda: current["today"])

    def set_today(day: date) -> None:
        current["today"] = day
    return set_today


def liability(conn, name="Visa Card", due_day=None, open_=True):
    account_id = add_account(conn, name, 2, "Credit card")
    conn.execute("UPDATE accounts SET due_day = ?, is_open = ? WHERE id = ?", (due_day, int(open_), account_id))
    return account_id


def next_due(conn, account_id):
    return conn.execute("SELECT next_due FROM account_summaries WHERE id = ?", (account_id,)).fetchone()[0]


# ---- the rule ----

@pytest.mark.parametrize("value", [1, 15, 28, 29, 30, 31])
def test_a_whole_number_from_1_to_31_is_kept(value):
    assert accounts.clean_due_day(value) == value


def test_none_clears_it():
    assert accounts.clean_due_day(None) is None


@pytest.mark.parametrize("value", [0, 32, -1, 100, 15.0, 15.5, "15", "", " ", "fifteenth", True, False, [15], {"day": 15}])
def test_anything_else_is_refused(value):
    with pytest.raises(ValidationError, match="whole number from 1 to 31"):
        accounts.clean_due_day(value)


# ---- the next due date: the examples in the design ----

@pytest.mark.parametrize("due_day, today, expected", [
    (31, date(2027, 1, 31), date(2027, 1, 31)),        # due today
    (31, date(2027, 2, 10), date(2027, 2, 28)),        # a shorter month
    (31, date(2027, 3, 1), date(2027, 3, 31)),
    (31, date(2027, 4, 30), date(2027, 4, 30)),        # the 30th is the last day of April, so due today
    (30, date(2028, 2, 10), date(2028, 2, 29)),        # a leap year
    (15, date(2027, 3, 16), date(2027, 4, 15)),        # passed, so next month's
    (31, date(2026, 12, 31), date(2026, 12, 31)),
    (31, date(2027, 1, 1), date(2027, 1, 31)),
    (15, date(2026, 12, 20), date(2027, 1, 15)),       # the year rolls over
    (31, date(2026, 11, 30), date(2026, 11, 30)),
    (31, date(2026, 10, 31), date(2026, 10, 31)),
    (29, date(2027, 2, 28), date(2027, 2, 28)),        # the 29th in a year with no 29th
    (30, date(2027, 1, 31), date(2027, 2, 28)),        # passed in January, so February's last day
])
def test_the_examples_in_the_design(conn, clock_on, due_day, today, expected):
    clock_on(today)
    assert next_due(conn, liability(conn, due_day=due_day)) == expected.isoformat()
    assert reference(due_day, today) == expected                  # the reference agrees with the design's own table


@pytest.mark.parametrize("year", [2027, 2028])              # a normal year and a leap year
def test_every_due_day_on_every_day_of_the_year_agrees_with_a_plain_calculation(conn, clock_on, year):
    ids = {day: liability(conn, f"Account {day}", due_day=day) for day in range(1, 32)}
    today = date(year, 1, 1)
    while today.year == year:
        clock_on(today)
        got = {row[0]: row[1] for row in conn.execute("SELECT due_day, next_due FROM account_summaries")}
        for day in ids:
            assert got[day] == reference(day, today).isoformat(), (day, today)
        today += timedelta(days=1)


def test_the_date_is_never_before_today_and_is_within_a_month(conn, clock_on):
    liability(conn, due_day=31)
    for today in (date(2026, 1, 31), date(2026, 2, 1), date(2026, 12, 31), date(2028, 2, 29)):
        clock_on(today)
        found = date.fromisoformat(conn.execute("SELECT next_due FROM account_summaries").fetchone()[0])
        assert today <= found <= today + timedelta(days=31)


# ---- the installation's zone ----

def test_the_date_follows_the_installations_zone_either_side_of_its_midnight(conn, monkeypatch):
    monkeypatch.setattr(clock, "today", REAL_TODAY)                           # the real today(), with a fixed now()
    account_id = liability(conn, due_day=4)
    monkeypatch.setattr(clock, "now", lambda: datetime(2026, 6, 3, 20, 0, tzinfo=timezone.utc))
    clock.set_zone(None)
    assert next_due(conn, account_id) == "2026-06-04"                         # still the 3rd in UTC: due tomorrow
    clock.set_zone("Pacific/Auckland")                                        # twelve hours ahead: already the 4th, so due today
    assert next_due(conn, account_id) == "2026-06-04"
    monkeypatch.setattr(clock, "now", lambda: datetime(2026, 6, 4, 11, 59, tzinfo=timezone.utc))
    assert next_due(conn, account_id) == "2026-06-04"                         # 23:59 on the 4th in Auckland
    monkeypatch.setattr(clock, "now", lambda: datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc))
    assert next_due(conn, account_id) == "2026-07-04"                         # midnight: the 5th, so July's
    clock.set_zone(None)


# ---- accounts without a date ----

def test_an_account_with_no_due_day_has_no_date(conn, clock_on):
    assert next_due(conn, liability(conn)) is None


def test_a_closed_account_keeps_its_day_and_shows_no_date_until_it_is_reopened(conn, clock_on):
    account_id = liability(conn, due_day=20)
    assert next_due(conn, account_id) == "2026-11-20"
    conn.execute("UPDATE accounts SET is_open = 0 WHERE id = ?", (account_id,))
    assert next_due(conn, account_id) is None
    assert conn.execute("SELECT due_day FROM accounts WHERE id = ?", (account_id,)).fetchone()[0] == 20
    conn.execute("UPDATE accounts SET is_open = 1 WHERE id = ?", (account_id,))
    assert next_due(conn, account_id) == "2026-11-20"


def test_an_open_account_that_is_paid_off_keeps_its_date(conn, clock_on):
    account_id = liability(conn, due_day=20)
    add_balance(conn, account_id, '2026-11-01', 0)
    assert next_due(conn, account_id) == "2026-11-20"


def test_a_deleted_account_is_not_in_the_view(conn, clock_on):
    account_id = liability(conn, due_day=20)
    conn.execute("UPDATE accounts SET deleted = 1 WHERE id = ?", (account_id,))
    assert conn.execute("SELECT COUNT(*) FROM account_summaries WHERE id = ?", (account_id,)).fetchone()[0] == 0


# ---- what is stored and logged ----

def account_and_op(conn):
    admin = conn.execute("SELECT id FROM users WHERE is_system = 1").fetchone()[0]
    return liability(conn), admin


def test_an_edit_stores_and_logs_the_day(conn):
    account_id, admin = account_and_op(conn)
    accounts.update_account(op(conn, admin), account_id, "Visa Card", type_id(conn, "Credit card"), None, due_day=15)
    assert accounts.get_account(conn, account_id)["due_day"] == 15
    change = conn.execute("SELECT new_json FROM sys_record_changes WHERE tablename = 'accounts' AND record_id = ? ORDER BY id DESC",
                          (account_id,)).fetchone()[0]
    assert json.loads(change)["due_day"] == 15


def test_leaving_it_out_keeps_it_and_none_clears_it(conn):
    account_id, admin = account_and_op(conn)
    kind = type_id(conn, "Credit card")
    accounts.update_account(op(conn, admin), account_id, "Visa Card", kind, None, due_day=15)
    accounts.update_account(op(conn, admin), account_id, "Visa Card", kind, "a note")                    # not sent
    assert accounts.get_account(conn, account_id)["due_day"] == 15
    accounts.update_account(op(conn, admin), account_id, "Visa Card", kind, "a note", due_day=None)
    assert accounts.get_account(conn, account_id)["due_day"] is None


def test_an_asset_cannot_have_a_due_day_and_nothing_is_written(conn):
    admin = conn.execute("SELECT id FROM users WHERE is_system = 1").fetchone()[0]
    account_id = add_account(conn, "Checking", 1, "Checking")
    before = conn.execute("SELECT COUNT(*) FROM sys_record_changes").fetchone()[0]
    with pytest.raises(ValidationError, match="Only a liability"):
        accounts.update_account(op(conn, admin), account_id, "Renamed", type_id(conn, "Checking"), None, due_day=15)
    assert conn.execute("SELECT name, due_day FROM accounts WHERE id = ?", (account_id,)).fetchone()[:] == ("Checking", None)
    assert conn.execute("SELECT COUNT(*) FROM sys_record_changes").fetchone()[0] == before
    accounts.update_account(op(conn, admin), account_id, "Checking", type_id(conn, "Checking"), None, due_day=None)     # clearing is fine


def test_the_database_refuses_a_stored_day_out_of_range(conn):
    account_id, _ = account_and_op(conn)
    for bad in (0, 32):
        with pytest.raises(Exception, match="CHECK"):
            conn.execute("UPDATE accounts SET due_day = ? WHERE id = ?", (bad, account_id))


# ---- changing class ----

def test_moving_to_an_asset_type_clears_the_day_and_logs_it(conn):
    account_id, admin = account_and_op(conn)
    accounts.update_account(op(conn, admin), account_id, "Visa Card", type_id(conn, "Credit card"), None, due_day=15)
    accounts.change_class(op(conn, admin), account_id, type_id(conn, "Checking"))
    assert conn.execute("SELECT due_day FROM accounts WHERE id = ?", (account_id,)).fetchone()[0] is None
    change = conn.execute("SELECT new_json FROM sys_record_changes WHERE tablename = 'accounts' AND record_id = ? ORDER BY id DESC",
                          (account_id,)).fetchone()[0]
    assert json.loads(change)["due_day"] is None


def test_moving_to_a_liability_type_leaves_it_empty_and_a_class_change_without_a_day_writes_no_day(conn):
    admin = conn.execute("SELECT id FROM users WHERE is_system = 1").fetchone()[0]
    account_id = add_account(conn, "Checking", 1, "Checking")
    accounts.change_class(op(conn, admin), account_id, type_id(conn, "Credit card"))
    assert accounts.get_account(conn, account_id)["due_day"] is None
    accounts.update_account(op(conn, admin), account_id, "Checking", type_id(conn, "Credit card"), None, due_day=9)
    assert accounts.get_account(conn, account_id)["due_day"] == 9


def test_a_type_cannot_change_class_while_an_account_uses_it(conn):
    """So no account can become an asset with a due day through a type's class (the only other path that changes a class)."""
    from northstar import account_types
    admin = conn.execute("SELECT id FROM users WHERE is_system = 1").fetchone()[0]
    liability(conn, due_day=10)
    kind = type_id(conn, "Credit card")
    with pytest.raises(ValidationError):
        account_types.update_type(op(conn, admin), kind, "Credit card", 1, 30)


# ---- the API ----

def account_for(client, name="Visa Card", class_id=2, type_name="Credit card"):
    with with_db(client) as conn:
        account_id = add_account(conn, name, class_id, type_name)
        conn.commit()
    return account_id


@pytest.fixture
def visa(client):
    account_id = account_for(client)
    with with_db(client) as conn:
        kind = type_id(conn, "Credit card")
    return account_id, kind


def patch(client, visa, **fields):
    account_id, kind = visa
    return client.patch(f"/api/accounts/{account_id}", json={"name": "Visa Card", "type_id": kind, **fields})


def test_an_edit_answers_with_the_day_and_the_next_due_date(client, visa, clock_on):
    clock_on(date(2026, 11, 15))
    body = patch(client, visa, due_day=20).json()
    assert (body["due_day"], body["next_due"]) == (20, "2026-11-20")
    page = client.get(f"/api/accounts/{visa[0]}").json()
    assert (page["due_day"], page["next_due"]) == (20, "2026-11-20")


def test_an_account_with_no_due_day_answers_none_for_both(client, visa):
    page = client.get(f"/api/accounts/{visa[0]}").json()
    assert (page["due_day"], page["next_due"]) == (None, None)


def test_leaving_it_out_keeps_it_and_null_clears_it(client, visa):
    patch(client, visa, due_day=12)
    assert patch(client, visa, notes="hello").json()["due_day"] == 12             # not sent: unchanged
    assert patch(client, visa, due_day=None).json()["due_day"] is None            # null clears it
    patch(client, visa, due_day=12)
    assert patch(client, visa, due_day=None, notes="x").json()["due_day"] is None


@pytest.mark.parametrize("due_day", [0, 32, -3, 15.5, 15.0, "15", "", "soon", True, [15]])
def test_a_refused_day_is_a_422_and_nothing_is_saved(client, visa, due_day):
    patch(client, visa, due_day=12)
    response = patch(client, visa, notes="should not be saved", due_day=due_day)
    assert response.status_code == 422
    page = client.get(f"/api/accounts/{visa[0]}").json()
    assert (page["due_day"], page["notes"]) == (12, None)


def test_an_asset_with_a_day_is_a_422(client):
    account_id = account_for(client, "Checking", 1, "Checking")
    with with_db(client) as conn:
        kind = type_id(conn, "Checking")
    response = client.patch(f"/api/accounts/{account_id}", json={"name": "Checking", "type_id": kind, "due_day": 5})
    assert response.status_code == 422 and "Only a liability" in response.json()["detail"]


def test_any_signed_in_user_who_can_edit_an_account_can_set_it(member_client):
    account_id = account_for(member_client)
    with with_db(member_client) as conn:
        kind = type_id(conn, "Credit card")
    response = member_client.patch(f"/api/accounts/{account_id}", json={"name": "Visa Card", "type_id": kind, "due_day": 7})
    assert response.status_code == 200 and response.json()["due_day"] == 7


def test_signed_out_it_is_refused(anon_client):
    assert anon_client.patch("/api/accounts/1", json={"name": "x", "type_id": 1, "due_day": 7}).status_code == 401


def test_closing_hides_the_date_and_reopening_brings_it_back(client, visa, clock_on):
    clock_on(date(2026, 11, 15))
    patch(client, visa, due_day=20)
    closed = client.post(f"/api/accounts/{visa[0]}/close").json()
    assert (closed["due_day"], closed["next_due"]) == (20, None)
    reopened = client.post(f"/api/accounts/{visa[0]}/reopen").json()
    assert (reopened["due_day"], reopened["next_due"]) == (20, "2026-11-20")


def test_changing_class_through_the_api_clears_the_day(client, visa):
    patch(client, visa, due_day=20)
    with with_db(client) as conn:
        asset = type_id(conn, "Checking")
    page = client.post(f"/api/accounts/{visa[0]}/change-class", json={"type_id": asset}).json()
    assert (page["class_name"], page["due_day"], page["next_due"]) == ("Asset", None, None)


# ---- the Accounts list ----

def listed(client, **request):
    return {row["name"]: row for row in client.post(LIST, json={"filters": [], **request}).json()["rows"]}


@pytest.fixture
def household(client, clock_on):
    clock_on(date(2026, 11, 15))
    with with_db(client) as conn:
        liability(conn, "Late", due_day=10)         # passed: December 10
        liability(conn, "Today", due_day=15)
        liability(conn, "Soon", due_day=31)         # November has 30 days: the 30th
        liability(conn, "Nothing", due_day=None)
        liability(conn, "Shut", due_day=12, open_=False)
        add_account(conn, "Savings", 1, "Savings")
        conn.commit()


def test_next_due_is_a_default_column_between_type_and_currency(client, household):
    page = client.post(LIST, json={}).json()
    assert page["default_columns"][:5] == ["name", "type.class", "type", "next_due", "currency"]
    assert {c["key"]: c["label"] for c in page["columns"]}["next_due"] == "Next due"


def test_the_column_shows_the_date_and_nothing_for_no_day_a_closed_account_or_an_asset(client, household):
    got = {name: row["next_due"] for name, row in listed(client).items()}
    assert got == {"Late": "2026-12-10", "Today": "2026-11-15", "Soon": "2026-11-30", "Nothing": None, "Shut": None, "Savings": None}


def test_it_sorts_ascending_with_the_empty_ones_last(client, household):
    names = [row["name"] for row in client.post(LIST, json={"filters": [], "sort": {"field": "next_due", "direction": "asc"}}).json()["rows"]]
    assert names[:3] == ["Today", "Soon", "Late"] and set(names[3:]) == {"Nothing", "Shut", "Savings"}


def test_it_sorts_descending_with_the_empty_ones_still_last(client, household):
    names = [row["name"] for row in client.post(LIST, json={"filters": [], "sort": {"field": "next_due", "direction": "desc"}}).json()["rows"]]
    assert names[:3] == ["Late", "Soon", "Today"] and set(names[3:]) == {"Nothing", "Shut", "Savings"}


def test_it_filters_by_date(client, household):
    rows = listed(client, filters=[{"field": "next_due", "operator": "before", "value": "2026-12-01"}])
    assert set(rows) == {"Today", "Soon"}


def test_the_due_day_is_a_column_a_person_can_add_and_is_not_shown_by_default(client, household):
    page = client.post(LIST, json={}).json()
    assert "due_day" not in page["default_columns"]
    assert "due_day" in [f["key"] for f in client.get(f"{LIST}/fields").json()["fields"]]


# ---- the migration ----

def test_upgrading_from_0033_adds_the_column_and_the_date_and_changes_no_data(tmp_path):
    folder = tmp_path / "before"
    folder.mkdir()
    for file in db.MIGRATIONS_DIR.glob("*.sql"):
        if not file.name.startswith("0034"):
            shutil.copy(file, folder)
    path = tmp_path / "data" / "northstar.db"
    db.upgrade(path, folder)
    conn = db.connect(path)
    use_dollars(conn)
    account_id = add_account(conn, "Test upgrade", 2, "Credit card")
    conn.commit()
    accounts_before = [tuple(r) for r in conn.execute("SELECT id, name, type_id, notes, is_open FROM accounts ORDER BY id")]
    log_before = conn.execute("SELECT COUNT(*) FROM sys_record_changes").fetchone()[0]
    assert "due_day" not in [r[1] for r in conn.execute("PRAGMA table_info(accounts)")]
    assert "next_due" not in [r[1] for r in conn.execute("PRAGMA table_info(account_summaries)")]
    conn.close()

    assert db.upgrade(path) == ["0034_payment_due_day"]
    conn = db.connect(path)
    assert [tuple(r) for r in conn.execute("SELECT id, name, type_id, notes, is_open FROM accounts ORDER BY id")] == accounts_before
    assert conn.execute("SELECT due_day FROM accounts WHERE id = ?", (account_id,)).fetchone()[0] is None
    assert conn.execute("SELECT due_day, next_due FROM account_summaries WHERE id = ?", (account_id,)).fetchone()[:] == (None, None)
    assert tuple(conn.execute("SELECT is_logged FROM sys_audited_fields WHERE tablename = 'accounts' AND fieldname = 'due_day'").fetchone()) == (1,)
    assert conn.execute("SELECT COUNT(*) FROM sys_record_changes").fetchone()[0] == log_before
    conn.close()


def test_the_summary_view_still_has_every_column_it_had_before(conn):
    columns = [r[1] for r in conn.execute("PRAGMA table_info(account_summaries)")]
    for name in ("balance_count", "last_date", "last_cents", "reporting_value", "reporting_scale", "reporting_unit", "days_since",
                 "is_stale", "website", "due_day", "next_due"):
        assert name in columns
