"""Account names are unique, ignoring ASCII case and surrounding spaces, across open and closed accounts. The
application says why; the database enforces it; the migration renames the duplicates a v0.1 database may hold.
Synthetic data only."""

import random
import shutil
import sqlite3

import pytest

from northstar import accounts, db
from northstar.errors import ValidationError

from conftest import type_id

ASSET, LIABILITY = 1, 2
MIGRATION = "0003_unique_account_names"


def add(conn, name, class_id=ASSET, type_name="Checking"):
    return accounts.add_account(conn, name, class_id, type_id(conn, type_name))


# -- the application --

def test_adding_an_account_with_a_taken_name_is_refused(conn):
    add(conn, "Test savings")
    with pytest.raises(ValidationError, match='account named "Test savings" already exists'):
        add(conn, "Test savings")


@pytest.mark.parametrize("variant", ["TEST SAVINGS", "test savings", "  Test savings  ", "tEsT sAvInGs"])
def test_case_and_surrounding_spaces_do_not_make_a_new_name(conn, variant):
    add(conn, "Test savings")
    with pytest.raises(ValidationError, match="already exists"):
        add(conn, variant)


def test_a_name_is_taken_across_classes(conn):
    add(conn, "Test account")
    with pytest.raises(ValidationError, match="already exists"):
        add(conn, "Test account", LIABILITY, "Loan")


def test_renaming_to_a_taken_name_is_refused_and_changes_nothing(conn):
    add(conn, "Test one")
    other = add(conn, "Test two")
    with pytest.raises(ValidationError, match='"Test one" already exists'):
        accounts.update_account(conn, other, "test ONE", type_id(conn, "Checking"))
    assert accounts.get_account(conn, other)["name"] == "Test two"


def test_an_account_can_be_renamed_to_a_different_case_of_its_own_name(conn):
    account = add(conn, "test savings")
    accounts.update_account(conn, account, "Test Savings", type_id(conn, "Checking"))
    assert accounts.get_account(conn, account)["name"] == "Test Savings"


def test_saving_an_account_without_changing_its_name_is_not_a_clash(conn):
    account = add(conn, "Test savings")
    accounts.update_account(conn, account, "Test savings", type_id(conn, "Savings"), "a note")


def test_a_closed_account_keeps_its_name_and_the_message_says_so(conn):
    old = add(conn, "Test old card", LIABILITY, "Credit card")
    accounts.close_account(conn, old)
    with pytest.raises(ValidationError, match="closed account named .Test old card. already exists") as refused:
        add(conn, "test old card", LIABILITY, "Credit card")
    assert "rename" in str(refused.value).lower()


def test_the_message_for_an_open_account_does_not_call_it_closed(conn):
    add(conn, "Test open")
    with pytest.raises(ValidationError) as refused:
        add(conn, "Test open")
    assert "closed" not in str(refused.value)


def test_a_closed_name_is_free_once_the_closed_account_is_renamed(conn):
    old = add(conn, "Test card", LIABILITY, "Credit card")
    accounts.close_account(conn, old)
    accounts.update_account(conn, old, "Test card (old)", type_id(conn, "Credit card"))
    add(conn, "Test card", LIABILITY, "Credit card")


def test_names_that_differ_only_in_non_ascii_case_are_different(conn):
    """NOCASE folds ASCII only, the same as account types and users, and the message does not pretend otherwise."""
    add(conn, "Épargne")
    add(conn, "épargne")
    with pytest.raises(ValidationError, match="already exists"):
        add(conn, "Épargne")


def test_the_database_refuses_a_duplicate_even_when_the_application_is_bypassed(conn):
    add(conn, "Test account")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO accounts (name, class_id, type_id) VALUES ('TEST ACCOUNT', 1, 1)")
    conn.execute("INSERT INTO accounts (name, class_id, type_id) VALUES ('Other', 1, 1)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE accounts SET name = 'test ACCOUNT' WHERE name = 'Other'")


def test_a_refused_new_account_leaves_no_row(conn):
    add(conn, "Test account")
    with pytest.raises(ValidationError):
        add(conn, "test account")
    assert conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 1


def test_the_api_refuses_a_taken_name_with_422_and_the_message(client):
    body = {"name": "Test api", "account_class": "asset", "type_id": 1}
    first = client.post("/api/accounts", json=body)
    assert first.status_code < 300, first.text
    second = client.post("/api/accounts", json={**body, "name": "TEST API"})
    assert second.status_code == 422 and "already exists" in second.text


# -- the migration --

@pytest.fixture
def before(tmp_path):
    """A v0.1 database (migrations up to 0002), and a helper to upgrade it with the real migrations."""
    older = tmp_path / "older"
    older.mkdir()
    for name in ("0001_initial", "0002_login_attempts"):
        shutil.copy(db.MIGRATIONS_DIR / f"{name}.sql", older)
    path = tmp_path / "data" / "northstar.db"
    db.upgrade(path, older)
    conn = db.connect(path)
    yield conn, path
    conn.close()


def names_in_order(conn):
    return [row[0] for row in conn.execute("SELECT name FROM accounts ORDER BY id")]


def put(conn, *names, closed=()):
    for name in names:
        conn.execute("INSERT INTO accounts (name, class_id, type_id, is_open) VALUES (?, 1, 1, ?)",
                     (name, 0 if name in closed else 1))


def upgrade(conn, path):
    conn.close()
    return db.upgrade(path)


def test_a_database_without_duplicates_keeps_every_name(before):
    conn, path = before
    put(conn, "Test one", "Test two", "Épargne", "épargne")
    assert upgrade(conn, path) == [MIGRATION]
    assert names_in_order(db.connect(path)) == ["Test one", "Test two", "Épargne", "épargne"]


def test_name_and_NAME_and_an_existing_Name_2_are_all_kept_apart(before):
    conn, path = before
    put(conn, "Name", "name", "Name (2)", "NAME")
    upgrade(conn, path)
    assert names_in_order(db.connect(path)) == ["Name", "Name (3)", "Name (2)", "Name (4)"]


def test_the_lowest_id_keeps_its_name_whatever_its_spelling_and_whether_open_or_closed(before):
    conn, path = before
    put(conn, "old card", "Old Card", "OLD CARD", closed=("old card",))
    upgrade(conn, path)
    assert names_in_order(db.connect(path)) == ["old card", "old card (2)", "old card (3)"]


def test_a_name_ending_in_a_number_is_a_group_of_its_own(before):
    conn, path = before
    put(conn, "Card (2)", "Card", "card", "CARD (2)")
    upgrade(conn, path)
    assert names_in_order(db.connect(path)) == ["Card (2)", "Card", "Card (3)", "Card (2) (2)"]


def test_the_balances_of_a_renamed_account_are_untouched(before):
    conn, path = before
    put(conn, "Dup", "dup")
    conn.execute("INSERT INTO balances (account_id, as_of_date, amount_cents) VALUES (2, '2026-01-31', 12345)")
    upgrade(conn, path)
    again = db.connect(path)
    assert again.execute("SELECT name FROM accounts WHERE id = 2").fetchone()[0] == "Dup (2)"
    assert again.execute("SELECT amount_cents FROM balances WHERE account_id = 2").fetchone()[0] == 12345


def test_the_migration_runs_once_and_a_second_start_changes_nothing(before):
    conn, path = before
    put(conn, "Dup", "dup")
    upgrade(conn, path)
    first = path.read_bytes()
    assert db.upgrade(path) == []
    assert path.read_bytes() == first


def test_a_backup_of_the_old_names_is_made_first(before):
    conn, path = before
    put(conn, "Dup", "dup")
    upgrade(conn, path)
    [saved] = (path.parent / "backups").glob("pre-migration-*.db")
    kept = sqlite3.connect(saved)
    assert [row[0] for row in kept.execute("SELECT name FROM accounts ORDER BY id")] == ["Dup", "dup"]


@pytest.mark.parametrize("bad", [" Padded", "Padded ", "\tTabbed", ""])
def test_an_untrimmed_name_stops_the_migration_which_rolls_back(before, bad):
    conn, path = before
    put(conn, "Dup", "dup", bad)
    with pytest.raises(sqlite3.IntegrityError, match="account_names_are_trimmed"):
        upgrade(conn, path)
    again = db.connect(path)
    assert names_in_order(again) == ["Dup", "dup", bad]                    # nothing was renamed
    assert MIGRATION not in {row[0] for row in again.execute("SELECT version FROM sys_schema_migrations")}


def test_the_index_is_on_the_name_ignoring_ascii_case(conn):
    [sql] = [row[0] for row in conn.execute("SELECT sql FROM sqlite_master WHERE name = 'accounts_name_unique'")]
    assert "UNIQUE" in sql.upper() and "NOCASE" in sql.upper()


def ascii_fold(name):
    return "".join(c.lower() if "A" <= c <= "Z" else c for c in name)


def reference_rename(names):
    """The rule as written in the design, done one step at a time: collect every normalized name, then go through
    the duplicates in id order, the first keeping its name, and give each later one the smallest unused Name (n)."""
    taken = {ascii_fold(name) for name in names}
    seen, result = set(), []
    for name in names:
        key = ascii_fold(name)
        if key not in seen:
            seen.add(key)
            result.append(name)
            first_spelling = name
            continue
        base = next(n for n in result if ascii_fold(n) == key)
        number = 2
        while ascii_fold(f"{base} ({number})") in taken:
            number += 1
        new = f"{base} ({number})"
        taken.add(ascii_fold(new))
        result.append(new)
    return result


@pytest.mark.parametrize("seed", range(25))
def test_the_migration_agrees_with_the_rule_and_with_the_index_on_random_names(before, seed):
    """The collision detection (in SQL) and the final index must give the same answer, and both must match the
    sequential rule. Small alphabets make many collisions, including names that already end in a number."""
    conn, path = before
    rng = random.Random(seed)
    pool = ["a", "A", "b", "B", "a (2)", "A (3)", "b (2)", "É", "é", "a (2) (2)"]
    names = [rng.choice(pool) for _ in range(rng.randint(1, 14))]
    put(conn, *names)
    upgrade(conn, path)
    after = names_in_order(db.connect(path))
    assert after == reference_rename(names)
    assert len({ascii_fold(name) for name in after}) == len(after)     # and the index accepted all of them
