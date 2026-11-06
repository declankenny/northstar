"""Account precision and explicit file conventions, independent of the user's locale. Synthetic data only."""

from datetime import date

import pytest

from northstar import accounts, csvparse, db, import_register
from conftest import op, type_id, with_db
from test_currencies import use_currency, v02_database, v02_migrations
from test_import_api import balances_of, encode, settings, url


def currency_account(client, code):
    with with_db(client) as conn:
        use_currency(conn, code)
        account = accounts.add_account(op(conn), "Synthetic savings", 1, type_id(conn, "Savings"))
        conn.commit()
    return account


@pytest.mark.parametrize("code,text,expected", [("JPY", "1.234", 1234), ("USD", "1234.56", 123456),
                                               ("KWD", "1234.567", 1234567), ("KWD", "(1.234)", -1234)])
def test_review_and_commit_use_account_minor_units(client, code, text, expected):
    account = currency_account(client, code)
    body = settings(f"Date;Balance\n2026-01-31;{text}\n", mapping={"date": 0, "balance": 1})
    if code == "KWD":
        body["number_format"] = "1,234.56"
    reviewed = client.post(url(account, "review"), json=body).json()
    assert reviewed["can_commit"] is True
    assert reviewed["rows"][0]["amount_cents"] == expected
    saved = client.post(url(account, "commit"), json={**body, "reviewed": reviewed["reviewed"]})
    assert saved.status_code == 200
    assert balances_of(client, account)[0][1] == expected


def test_ambiguity_uses_all_rows_and_changing_the_style_requires_another_review(client):
    account = currency_account(client, "KWD")
    text = "Date;Balance\n2026-01-31;1.234\n2026-02-28;2.345\n"
    read = client.post(url(account, "read"), json=encode(text)).json()
    assert read["currency"]["minor_units"] == 3
    column = read["columns"][1]
    assert column["number_formats"] == ["1,234.56", "1.234,56"]
    assert column["number_previews"]["1,234.56"] == 1234
    assert column["number_previews"]["1.234,56"] == 1234000
    body = settings(text, mapping={"date": 0, "balance": 1})
    refused = client.post(url(account, "review"), json=body).json()
    assert not refused["can_commit"] and "number style" in refused["errors"][0]["message"]
    body["number_format"] = "1,234.56"
    reviewed = client.post(url(account, "review"), json=body).json()["reviewed"]
    body["number_format"] = "1.234,56"
    assert client.post(url(account, "commit"), json={**body, "reviewed": reviewed}).status_code == 409
    assert balances_of(client, account) == []
    # The last row disambiguates values which the first five sample rows cannot.
    text = "Date;Balance\n" + "2026-01-31;1.234\n" * 5 + "2026-02-28;2.34\n"
    read = client.post(url(account, "read"), json=encode(text)).json()
    assert read["columns"][1]["number_formats"] == ["1,234.56"]


@pytest.mark.parametrize("code,text", [("JPY", "12.5"), ("KWD", "1.2345"), ("USD", "1.234")])
def test_excess_precision_is_refused_without_rounding(client, code, text):
    account = currency_account(client, code)
    body = {**settings(f"Date;Balance\n2026-01-31;{text}\n", mapping={"date": 0, "balance": 1}),
            "number_format": "1,234.56"}
    result = client.post(url(account, "review"), json=body).json()
    assert not result["can_commit"] and result["errors"][0]["record"] == 2
    assert balances_of(client, account) == []


@pytest.mark.parametrize("locale", ["en-US", "de-DE", "fr-FR", "ja-JP"])
def test_existing_northstar_csv_is_read_as_plain_decimal_in_any_locale(client, locale):
    account = currency_account(client, "KWD")
    with with_db(client) as conn:
        conn.execute("UPDATE users SET locale = ? WHERE is_system = 0", (locale,))
        conn.commit()
    text = "Account ID,Account Name,Balance Date,Balance Amount\n999,Other name,2026-01-31,1.234\n"
    read = client.post(url(account, "read"), json=encode(text)).json()
    assert read["canonical"] and read["columns"][3]["number_formats"] == ["1234.56"]
    body = settings(text, mapping={"date": 2, "balance": 3})
    result = client.post(url(account, "review"), json=body).json()
    assert result["can_commit"] and result["rows"][0]["amount_cents"] == 1234
    assert client.post(url(account, "review"), json={**body, "number_format": "1.234,56"}).status_code == 422


def test_an_import_before_currency_migration_can_still_be_undone(tmp_path, v02_migrations):
    from northstar import balance_import
    path = v02_database(tmp_path, v02_migrations)
    conn = db.connect(path)
    rows = [csvparse.ParsedRow(2, date(2026, 2, 28), 12345, None)]
    plan = balance_import.plan_import(conn, 1, rows)
    balance_import.commit_import(conn, None, 1, rows, "skip", plan.reviewed)
    operation = conn.execute("SELECT id FROM sys_operations WHERE kind = 'import'").fetchone()[0]
    # Old operations have no number-format metadata and may contain a Currency mapping.
    conn.execute("UPDATE sys_operations SET detail = ? WHERE id = ?",
                 ('{"account_id":1,"mapping":{"date":0,"balance":1,"currency":2},"counts":{"added":1,"updated":0,"unchanged":0,"skipped":0}}', operation))
    conn.commit()
    conn.close()
    db.upgrade(path)
    conn = db.connect(path)
    import_register.undo_import(conn, None, operation)
    assert conn.execute("SELECT amount_cents FROM live_balances").fetchall()[0][0] == 123456
    assert conn.execute("SELECT COUNT(*) FROM live_balances").fetchone()[0] == 1
    conn.close()


# -- the precision is the account's and is never assumed --

TODAY = date(2026, 11, 6)


def test_the_file_parser_has_no_default_precision():
    table = csvparse.read_table(b"Date,Balance\n2026-01-31,1234\n")
    mapping = csvparse.suggest_mapping(table.headers)
    with pytest.raises(TypeError):
        csvparse.parse_file(table, mapping, None, TODAY)
    for minor_units, expected in ((0, 1234), (2, 123400), (3, 1234000)):
        assert [row.cents for row in csvparse.parse_file(table, mapping, None, TODAY, minor_units).rows] == [expected]


def test_the_lower_level_readers_have_no_default_either():
    with pytest.raises(TypeError):
        csvparse.parse_amount("1", "1,234.56")
    with pytest.raises(TypeError):
        csvparse.detect_number_formats([(2, "1")])


# -- a column that is plainly not amounts is not read to the end --

def test_a_text_column_is_decided_from_its_first_values(monkeypatch):
    seen = []
    real = csvparse.detect_number_formats
    monkeypatch.setattr(csvparse, "detect_number_formats", lambda cells, units: seen.append(len(cells)) or real(cells, units))
    words = [(index + 2, f"memo {index}") for index in range(5000)]
    assert csvparse.number_choices(words, 2) == []
    assert seen == [csvparse.SAMPLED]                               # one look at the first few, and no more


def test_a_numeric_column_is_still_read_whole_and_decides_as_before(monkeypatch):
    seen = []
    real = csvparse.detect_number_formats
    monkeypatch.setattr(csvparse, "detect_number_formats", lambda cells, units: seen.append(len(cells)) or real(cells, units))
    amounts = [(index + 2, f"{index}.50") for index in range(5000)]
    assert csvparse.number_choices(amounts, 2) == ["1,234.56"]            # equivalent styles are one choice
    assert seen == [csvparse.SAMPLED, 5000]


def test_a_bad_value_after_the_first_few_still_stops_a_column_being_offered_a_style():
    cells = [(index + 2, "1.50") for index in range(200)] + [(300, "oops")]
    assert csvparse.number_choices(cells, 2) == []


def test_blank_cells_do_not_count_towards_the_first_values():
    cells = [(index + 2, "") for index in range(80)] + [(100, "5.00"), (101, "6.00")]
    assert csvparse.number_choices(cells, 2) == ["1,234.56"]            # equivalent styles are one choice
    assert csvparse.number_choices([(2, ""), (3, "  ")], 2) == []


# -- what the refusal says follows the account's currency --

@pytest.mark.parametrize("units, name", [(0, "1,234"), (2, "1,234.56"), (3, "1,234.567")])
def test_a_number_style_is_named_with_the_accounts_own_decimal_places(units, name):
    assert csvparse.style_label("1,234.56", units) == name
    assert csvparse.style_label("1234.56", units) == name.replace(",", "")
    assert csvparse.style_label("1.234,56", units) == name.replace(",", "\u0000").replace(".", ",").replace("\u0000", ".")


def test_excess_precision_says_what_the_currency_allows():
    with pytest.raises(csvparse.ValidationError) as yen:
        csvparse.parse_amount("12.5", "1,234.56", 0)
    assert "in the format 1,234. This currency has no decimal places." in str(yen.value)
    with pytest.raises(csvparse.ValidationError) as dinar:
        csvparse.parse_amount("1.2345", "1,234.56", 3)
    assert "in the format 1,234.567. Use at most 3 decimal places; amounts are never rounded." in str(dinar.value)


def test_a_column_of_non_amounts_for_yen_says_there_are_no_decimal_places():
    text = "Date,Balance\n2026-01-31,12.5\n2026-02-28,oops\n"
    table = csvparse.read_table(text.encode("utf-8"))
    parsed = csvparse.parse_file(table, csvparse.suggest_mapping(table.headers), None, TODAY, 0)
    assert any("This currency has no decimal places." in error.message for error in parsed.errors)


def test_the_review_no_longer_carries_a_field_that_was_always_empty(client):
    account = currency_account(client, "USD")
    body = client.post(url(account, "review"), json=settings("Date;Balance\n2026-01-31;10.00\n", mapping={"date": 0, "balance": 1})).json()
    assert "unsupported_currencies" not in body
    bad = client.post(url(account, "review"), json=settings("Date;Balance\n2026-01-31;oops\n", mapping={"date": 0, "balance": 1})).json()
    assert "unsupported_currencies" not in bad
