"""Every message the server writes for a person says its dates and numbers in that person's number and date format. Synthetic data only."""

import json
from datetime import date

import pytest

from conftest import add_account, op, with_db
from northstar import account_types, balances, csvparse, import_register, locales
from test_import_api import CSV, SENT, commit, review, settings, url
from test_imports_register import run_import

ASSET = 1
VECTORS = json.loads((__import__("pathlib").Path(__file__).resolve().parent.parent / "frontend" / "src" / "testdata"
                      / "locale_vectors.json").read_text(encoding="utf-8"))


def use_locale(client, tag, email="test@example.com"):
    with with_db(client) as conn:
        conn.execute("UPDATE users SET locale = ? WHERE email = ?", (tag, email))


def speak(conn, tag):
    return locales.speak_as(locales.get(conn, tag))


# -- saying a date or a whole number --

@pytest.mark.parametrize("vector", VECTORS["format_date"], ids=lambda v: f"{v['locale']} {v['iso']}")
def test_a_date_is_written_by_the_locales_template(conn, vector):
    locale = locales.get(conn, vector["locale"])
    assert locale.date(vector["iso"]) == vector["text"]
    assert locale.date(date.fromisoformat(vector["iso"])) == vector["text"]


@pytest.mark.parametrize("vector", VECTORS["format_integer"], ids=lambda v: f"{v['locale']} {v['n']}")
def test_a_whole_number_is_grouped_by_the_locales_mark(conn, vector):
    assert locales.get(conn, vector["locale"]).integer(vector["n"]) == vector["text"]


def test_a_negative_number_keeps_its_minus(conn):
    assert locales.get(conn, "de-DE").integer(-1234567) == "-1.234.567"
    assert locales.get(conn, "en-US").integer(-5) == "-5"


def test_us_english_without_a_database_is_the_en_us_row(conn):
    row = conn.execute("SELECT * FROM ref_locales WHERE tag = 'en-US'").fetchone()
    assert locales.US_ENGLISH == locales.get(conn, "en-US")
    assert (locales.US_ENGLISH.decimal_mark, locales.US_ENGLISH.group_mark) == (row["decimal_mark"], row["group_mark"])


def test_messages_are_in_us_english_unless_a_person_is_speaking(conn):
    assert locales.speaking() is locales.US_ENGLISH
    with speak(conn, "de-DE"):
        assert locales.speaking().tag == "de-DE"
        with speak(conn, "fr-FR"):
            assert locales.speaking().tag == "fr-FR"
        assert locales.speaking().tag == "de-DE"
    assert locales.speaking() is locales.US_ENGLISH
    with locales.speak_as(None):
        assert locales.speaking() is locales.US_ENGLISH


# -- the rules' own messages --

def test_the_message_for_a_date_that_is_taken_follows_the_locale(conn):
    admin_account = add_account(conn, "Test savings", ASSET, "Savings")
    balances.record_balance(op(conn), admin_account, date(2026, 9, 1), 100)
    other = balances.record_balance(op(conn), admin_account, date(2026, 8, 31), 200)
    assert other == "added"
    entry = conn.execute("SELECT id FROM live_balances WHERE as_of_date = '2026-08-31'").fetchone()[0]
    for tag, text in (("en-US", "Sep 1, 2026"), ("de-DE", "01.09.2026"), ("ja-JP", "2026/09/01"), ("fr-FR", "1 Sep 2026")):
        with speak(conn, tag):
            with pytest.raises(balances.ValidationError) as caught:
                balances.update_balance(op(conn), entry, "2026-09-01", "5.00", None, date(2026, 10, 1))
        assert f"There is already a balance on {text}. Edit that one instead." == str(caught.value), tag


def test_counts_of_a_thousand_or_more_use_the_group_mark(conn):
    with speak(conn, "de-DE"):
        assert str(balances.ConflictingEdit([{}] * 1234)).startswith("1.234 balances changed")
        assert account_types._in_use_message(1234, 0).startswith("1.234 accounts use this type.")
        assert account_types._in_use_message(1500, 20).startswith("1.520 accounts use this type, 20 of them deleted.")
    with speak(conn, "fr-FR"):
        assert str(balances.ConflictingEdit([{}] * 1234)).startswith("1\u202f234 balances changed")
    assert str(balances.ConflictingEdit([{}] * 1234)).startswith("1,234 balances changed")


def test_the_file_row_limit_is_written_in_the_locale(conn):
    big = ("Date,Balance\n" + "2026-01-01,1\n" * (csvparse.MAX_ROWS + 1)).encode("utf-8")
    for tag, text in (("en-US", "20,000"), ("de-DE", "20.000"), ("de-CH", "20\u2019000")):
        with speak(conn, tag):
            with pytest.raises(csvparse.CsvError) as caught:
                csvparse.read_table(big)
        assert f"The file has more than {text} rows." in str(caught.value), tag


def test_the_reason_a_balance_changed_since_an_import_names_the_date_in_the_locale(conn):
    system = conn.execute("SELECT id FROM users WHERE is_system = 1").fetchone()[0]
    version = conn.execute("INSERT INTO sys_operations (kind, user_id, created_at) VALUES ('import', ?, '2026-11-05T10:00:00Z')",
                           (system,)).lastrowid
    with speak(conn, "en-US"):
        assert import_register._why_changed(conn, version) == "Replaced by a later import (Nov 5, 2026)"
    with speak(conn, "de-DE"):
        assert import_register._why_changed(conn, version) == "Replaced by a later import (05.11.2026)"


# -- through the web, for the signed-in person --

@pytest.fixture
def account(client):
    with with_db(client) as conn:
        account_id = add_account(conn, "Demo Savings", ASSET, "Savings")
        conn.commit()
    return account_id


def test_a_duplicate_date_in_a_file_is_named_in_the_signed_in_persons_format(client, account):
    text = "Date,Balance\n2026-01-31,10.00\n2026-01-31,11.00\n2026-02-28,12.00\n"
    for tag, expected in (("en-US", "Jan 31, 2026"), ("de-DE", "31.01.2026"), ("fr-FR", "31 Jan 2026"), ("ja-JP", "2026/01/31")):
        use_locale(client, tag)
        body = review(client, account, text=text, mapping=SENT).json()
        assert f"Records 2 and 3 all have the date {expected}." in body["errors"][0]["message"], tag
        assert "2026-01-31" not in body["errors"][0]["message"], tag


def test_a_changed_balance_since_a_review_is_named_in_the_signed_in_persons_format(client, account):
    use_locale(client, "de-DE")
    reviewed = review(client, account, mapping=SENT).json()["reviewed"]
    with with_db(client) as conn:
        balances.record_balance(op(conn), account, date(2026, 1, 31), 99)
        conn.commit()
    refused = commit(client, account, reviewed, mapping=SENT)
    assert refused.status_code == 409
    assert "(31.01.2026)" in refused.json()["detail"]
    assert refused.json()["dates"] == ["2026-01-31"]                    # the data stays ISO, for the page to format


def test_the_date_an_import_was_undone_is_written_in_the_signed_in_persons_format(client, account):
    run_import(client, account)
    with with_db(client) as conn:
        import_id = conn.execute("SELECT id FROM sys_operations WHERE kind = 'import'").fetchone()[0]
    assert client.post(f"/api/imports/{import_id}/undo").status_code == 200
    with with_db(client) as conn:
        undone = conn.execute("SELECT created_at FROM sys_operations WHERE undoes_operation_id = ?", (import_id,)).fetchone()[0][:10]
    for tag in ("en-US", "de-DE", "fr-FR"):
        use_locale(client, tag)
        with with_db(client) as conn:
            expected = locales.get(conn, tag).date(undone)
        refused = client.get(f"/api/imports/{import_id}/undo")
        assert refused.status_code == 409
        assert refused.json()["detail"] == f"This import was already undone on {expected}.", tag
