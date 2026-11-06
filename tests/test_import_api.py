"""The balance import routes: read the file, review what it would do, commit it. Synthetic data only."""

import base64
import json
import logging

import pytest

from northstar import accounts, db
from northstar.web import import_api
from conftest import add_account, add_balance, op, with_db

ASSET = 1
CSV = "Date,Balance,Note\n2026-01-31,1000.00,Opening\n2026-02-28,1100.50,\n2026-03-31,1200.00,Bonus\n"
MAPPING = {"date": 0, "balance": 1, "note": 2}
SENT = {"date": 0, "balance": 1}      # a mapping with only the required columns


def encode(text, name="statement.csv"):
    raw = text if isinstance(text, bytes) else text.encode("utf-8")
    return {"content": base64.b64encode(raw).decode("ascii"), "file_name": name}


def settings(text=CSV, mapping=MAPPING, policy="skip", date_format=None, name="statement.csv"):
    return {**encode(text, name), "mapping": mapping, "policy": policy, "date_format": date_format}


@pytest.fixture
def account(client):
    with with_db(client) as conn:
        account_id = add_account(conn, "Demo Savings", ASSET, "Savings")
        conn.commit()
    return account_id


def url(account_id, step):
    return f"/api/accounts/{account_id}/import/{step}"


def review(client, account_id, **kwargs):
    return client.post(url(account_id, "review"), json=settings(**kwargs))


def commit(client, account_id, reviewed, **kwargs):
    return client.post(url(account_id, "commit"), json={**settings(**kwargs), "reviewed": reviewed})


def balances_of(client, account_id):
    with with_db(client) as conn:
        return [tuple(row) for row in conn.execute(
            "SELECT as_of_date, amount_cents, note, source FROM live_balances WHERE account_id = ? ORDER BY as_of_date", (account_id,))]


def everything(client):
    """All the data an import could touch, to show a refused one touched nothing."""
    with with_db(client) as conn:
        return ([tuple(row) for row in conn.execute("SELECT * FROM balances ORDER BY id")],
                conn.execute("SELECT COUNT(*) FROM sys_operations").fetchone()[0],
                conn.execute("SELECT COUNT(*) FROM sys_record_changes").fetchone()[0])


# -- who may use it, and on what --

@pytest.mark.parametrize("step", ["read", "review", "commit"])
def test_signed_out_is_refused(anon_client, step):
    assert anon_client.post(url(1, step), json=settings()).status_code == 401


@pytest.mark.parametrize("step", ["read", "review", "commit"])
def test_a_missing_account_is_not_found(client, step):
    body = {**settings(), "reviewed": {"fingerprint": "x", "expectations": []}}
    assert client.post(url(999, step), json=body).status_code == 404


@pytest.mark.parametrize("step", ["read", "review", "commit"])
def test_a_closed_account_is_refused_with_nothing_changed(client, account, step):
    with with_db(client) as conn:
        accounts.close_account(op(conn), account)
    before = everything(client)
    body = {**settings(), "reviewed": {"fingerprint": "x", "expectations": []}}
    response = client.post(url(account, step), json=body)
    assert response.status_code == 422
    assert "closed" in response.json()["detail"].lower()
    assert everything(client) == before


def test_an_ordinary_user_may_import_like_any_other_balance_change(member_client):
    with with_db(member_client) as conn:
        account_id = add_account(conn, "Demo Savings", ASSET, "Savings")
        conn.commit()
    reviewed = review(member_client, account_id).json()["reviewed"]
    assert commit(member_client, account_id, reviewed).status_code == 200


# -- read --

def test_read_describes_the_columns(client, account):
    body = client.post(url(account, "read"), json=encode(CSV)).json()
    assert body["delimiter"] == ","
    assert body["row_count"] == 3
    assert [c["header"] for c in body["columns"]] == ["Date", "Balance", "Note"]
    assert body["columns"][0]["samples"] == ["2026-01-31", "2026-02-28", "2026-03-31"]
    assert body["columns"][2]["samples"] == ["Opening", "Bonus"]       # blank cells are not samples
    assert body["suggested"] == {"date": 0, "balance": 1, "note": 2}
    assert body["today"]


def test_read_says_which_date_formats_a_column_can_be_read_in(client, account):
    ambiguous = "Day,Amount\n01/02/2026,10.00\n03/04/2026,11.00\n"
    columns = client.post(url(account, "read"), json=encode(ambiguous)).json()["columns"]
    assert columns[0]["date_formats"] == ["MM/DD/YYYY", "DD/MM/YYYY"]     # the person must choose
    assert columns[1]["date_formats"] == []                              # amounts are not dates
    settled = client.post(url(account, "read"), json=encode("Day,Amount\n31/01/2026,10.00\n")).json()["columns"]
    assert settled[0]["date_formats"] == ["DD/MM/YYYY"]                  # the column decides


def test_read_checks_the_whole_column_and_not_only_its_first_values(client, account):
    odd_one_last = "Day,Amount\n" + "".join(f"2026-01-{n:02d},1.00\n" for n in range(1, 8)) + "oops,1.00\n"
    assert client.post(url(account, "read"), json=encode(odd_one_last)).json()["columns"][0]["date_formats"] == []
    blank_first = "Day,Amount\n,1.00\n,1.00\n2026-01-05,1.00\n"
    assert client.post(url(account, "read"), json=encode(blank_first)).json()["columns"][0]["date_formats"] == ["YYYY-MM-DD"]


def test_read_sniffs_a_semicolon_file_and_a_byte_order_mark(client, account):
    text = "Datum;Saldo\n31.10.2026;1.234,56\n"
    body = client.post(url(account, "read"), json=encode(b"\xef\xbb\xbf" + text.encode("utf-8"))).json()
    assert body["delimiter"] == ";"
    assert [c["header"] for c in body["columns"]] == ["Datum", "Saldo"]      # no marker in the first header


@pytest.mark.parametrize("data, message", [
    (b"\xff\xfeD\x00a\x00t\x00e\x00", "UTF-8"),
    (b"", "empty"),
    (b"Date,Balance\n", "no data rows"),
    (b"JustOne\n1\n2\n", "one column"),
])
def test_read_refuses_a_file_that_cannot_be_used(client, account, data, message):
    response = client.post(url(account, "read"), json=encode(data))
    assert response.status_code == 422
    assert message in response.json()["detail"]


def test_read_refuses_a_file_over_the_row_limit(client, account):
    text = "Date,Balance\n" + "2026-01-01,1.00\n" * 20_001
    response = client.post(url(account, "read"), json=encode(text))
    assert response.status_code == 422
    assert "20,000" in response.json()["detail"]


# -- what a request may be --

def test_a_file_over_2_mb_is_refused_by_the_parser_with_a_message(client, account):
    response = client.post(url(account, "read"), json=encode("a,b\n" + "x" * (2 * 1024 * 1024)))
    assert response.status_code == 422
    assert "2 MB" in response.json()["detail"]


def test_a_body_over_the_limit_is_refused_before_it_is_read(client, account):
    response = client.post(url(account, "read"), content=b"x" * (import_api.MAX_BODY_BYTES + 1),
                           headers={"content-type": "application/json"})
    assert response.status_code == 413


def test_a_body_that_does_not_say_how_long_it_is_cannot_get_round_the_limit(client, account):
    def chunks():
        for _ in range(import_api.MAX_BODY_BYTES // 65_536 + 2):
            yield b"x" * 65_536
    response = client.post(url(account, "read"), content=chunks(), headers={"content-type": "application/json"})
    assert response.status_code == 413


@pytest.mark.parametrize("sent", [
    {"content": "not base64 !!!"},
    {"content": 12},
    {},
    {"file_name": "x.csv"},
])
def test_a_request_that_is_not_in_the_expected_form_is_a_422(client, account, sent):
    response = client.post(url(account, "read"), json=sent)
    assert response.status_code == 422


@pytest.mark.parametrize("raw", [b"not json", b"[1, 2]", b'"text"'])
def test_a_body_that_is_not_a_json_object_is_a_422(client, account, raw):
    response = client.post(url(account, "read"), content=raw, headers={"content-type": "application/json"})
    assert response.status_code == 422


def test_a_policy_other_than_skip_or_replace_is_a_422(client, account):
    assert review(client, account, policy="delete-everything").status_code == 422


# -- review --

def test_review_says_what_would_happen_and_writes_nothing(client, account):
    with with_db(client) as conn:
        add_balance(conn, account, "2026-02-28", 99999)
        conn.commit()
    before = everything(client)
    body = review(client, account).json()
    assert body["can_commit"] is True
    assert body["errors"] == []
    assert body["counts"] == {"add": 2, "replace": 0, "unchanged": 0, "skip": 1}
    assert [(r["date"], r["outcome"]) for r in body["rows"]] == [
        ("2026-03-31", "add"), ("2026-02-28", "skip"), ("2026-01-31", "add")]       # newest first
    skipped = body["rows"][1]
    assert (skipped["old_cents"], skipped["amount_cents"]) == (99999, 110050)
    assert body["reviewed"]["fingerprint"]
    assert [e["date"] for e in body["reviewed"]["expectations"]] == ["2026-01-31", "2026-02-28", "2026-03-31"]
    assert everything(client) == before


def test_review_with_the_replace_policy_shows_old_and_new(client, account):
    with with_db(client) as conn:
        add_balance(conn, account, "2026-02-28", 99999)
        conn.commit()
    body = review(client, account, policy="replace").json()
    assert body["counts"]["replace"] == 1
    replaced = next(r for r in body["rows"] if r["outcome"] == "replace")
    assert (replaced["old_cents"], replaced["amount_cents"]) == (99999, 110050)


def test_review_lists_unchanged_rows_in_the_counts_only(client, account):
    with with_db(client) as conn:
        add_balance(conn, account, "2026-01-31", 100000)
        conn.commit()
    body = review(client, account, mapping=SENT).json()       # no Note column, so the same amount is the same balance
    assert body["counts"]["unchanged"] == 1
    assert "2026-01-31" not in [r["date"] for r in body["rows"]]


def test_review_lists_at_most_200_of_each_outcome_and_counts_all(client, account):
    days = [f"{2000 + n // 365}-{(n % 365) // 31 + 1:02d}-{(n % 365) % 28 + 1:02d}" for n in range(0, 700)]
    unique = sorted(set(days))[:450]
    text = "Date,Balance\n" + "".join(f"{day},{n + 1}.00\n" for n, day in enumerate(unique))
    body = review(client, account, text=text, mapping=SENT).json()
    assert body["counts"]["add"] == 450
    assert len(body["rows"]) == import_api.ROWS_SHOWN == 200
    assert body["hidden"] == {"add": 250}
    assert body["rows"][0]["date"] == unique[-1]          # the newest are the ones listed
    assert len(body["reviewed"]["expectations"]) == 450  # the commit is still checked against every date


def test_review_lists_every_problem_and_offers_no_rows_or_commit(client, account):
    text = "Date,Balance\n2026-01-31,10.00\n2026-01-31,11.00\n2026-02-30,12.00\n2026-03-31,12x\n2099-01-01,1.00\n"
    body = review(client, account, text=text, mapping=SENT).json()
    assert body["can_commit"] is False
    assert body["counts"] is None and body["rows"] == [] and body["reviewed"] is None
    records = sorted(e["record"] for e in body["errors"])
    assert records == [4, 5, 6]            # the date, the amount and the future date; the duplicates are found after these are fixed
    assert all(e["message"] for e in body["errors"])


def test_review_names_every_record_of_a_duplicate_date(client, account):
    text = "Date,Balance\n2026-01-31,10.00\n2026-01-31,11.00\n2026-02-28,12.00\n"
    body = review(client, account, text=text, mapping=SENT).json()
    assert body["can_commit"] is False
    assert sorted(e["record"] for e in body["errors"]) == [2, 3]
    assert "Jan 31, 2026" in body["errors"][0]["message"]


def test_review_ignores_a_currency_column(client, account):
    text = "Date,Balance,Currency\n2026-01-31,10.00,USD\n2026-02-28,11.00,EUR\n"
    body = review(client, account, text=text, mapping={"date": 0, "balance": 1, "note": None, "currency": 2}).json()
    assert body["can_commit"] is True


def test_review_needs_a_date_format_when_the_data_cannot_decide(client, account):
    text = "Day,Amount\n01/02/2026,10.00\n03/04/2026,11.00\n"
    stuck = review(client, account, text=text, mapping=SENT).json()
    assert stuck["can_commit"] is False
    assert "date format" in stuck["errors"][0]["message"].lower()
    chosen = review(client, account, text=text, mapping=SENT, date_format="DD/MM/YYYY").json()
    assert chosen["can_commit"] is True
    assert chosen["date_format"] == "DD/MM/YYYY"
    assert sorted(r["date"] for r in chosen["rows"]) == ["2026-02-01", "2026-04-03"]


def test_review_refuses_a_mapping_that_cannot_work(client, account):
    for mapping in ({"date": 0, "balance": 0}, {"date": 0}, {"date": 7, "balance": 1}):
        assert review(client, account, mapping=mapping).status_code == 422


def test_review_reads_the_account_from_the_address_and_never_from_the_file(client, account):
    with with_db(client) as conn:
        other = add_account(conn, "Demo Checking", ASSET, "Checking")
        conn.commit()
    text = f"Date,Balance,Account\n2026-01-31,10.00,{other}\n"
    mapped = {"date": 0, "balance": 1, "note": None}      # the Account column is simply not mapped
    reviewed = review(client, account, text=text, mapping=mapped).json()["reviewed"]
    assert commit(client, account, reviewed, text=text, mapping=mapped).status_code == 200
    assert len(balances_of(client, account)) == 1
    assert balances_of(client, other) == []


# -- commit --

def test_commit_writes_what_was_reviewed(client, account):
    with with_db(client) as conn:
        add_balance(conn, account, "2026-02-28", 99999)
        conn.commit()
    reviewed = review(client, account, policy="replace").json()["reviewed"]
    response = commit(client, account, reviewed, policy="replace", name=r"C:\Users\someone\Documents\statement.csv")
    assert response.status_code == 200
    assert response.json() == {"added": 2, "updated": 1, "unchanged": 0, "skipped": 0}
    assert balances_of(client, account) == [
        ("2026-01-31", 100000, "Opening", "csv"), ("2026-02-28", 110050, None, "csv"), ("2026-03-31", 120000, "Bonus", "csv")]


def test_commit_records_who_and_which_file_and_never_what_was_in_it(client, account):
    reviewed = review(client, account).json()["reviewed"]
    commit(client, account, reviewed, name="/home/someone/private/statement.csv")
    with with_db(client) as conn:
        header = conn.execute("SELECT o.detail, o.kind, u.email FROM sys_operations o JOIN users u ON u.id = o.user_id WHERE o.kind = 'import'").fetchone()
        owners = {r[0] for r in conn.execute("SELECT created_by FROM balances")}
        actor = conn.execute("SELECT id FROM users WHERE email = 'test@example.com'").fetchone()[0]
    assert header["kind"] == "import" and header["email"] == "test@example.com"
    detail = json.loads(header["detail"])
    assert detail["file"] == "statement.csv"                                       # the base name, never the folders
    assert detail["mapping"] == {"date": 0, "balance": 1, "note": 2}
    assert detail["counts"] == {"added": 3, "updated": 0, "unchanged": 0, "skipped": 0}
    assert "Opening" not in header["detail"] and "1100.50" not in header["detail"]
    assert owners == {actor}


def test_commit_is_refused_when_a_reviewed_balance_changed_and_names_the_dates(client, account):
    with with_db(client) as conn:
        add_balance(conn, account, "2026-02-28", 99999)
        conn.commit()
    reviewed = review(client, account).json()["reviewed"]
    with with_db(client) as conn:
        conn.execute("DELETE FROM balances WHERE account_id = ?", (account,))       # a second tab removed it
        add_balance(conn, account, "2026-03-31", 5)                                  # and filled another reviewed date
        conn.commit()
    before = everything(client)
    response = commit(client, account, reviewed)
    assert response.status_code == 409
    assert response.json()["dates"] == ["2026-02-28", "2026-03-31"]
    assert "changed" in response.json()["detail"].lower()
    assert everything(client) == before


def test_commit_cannot_be_submitted_twice(client, account):
    reviewed = review(client, account).json()["reviewed"]
    assert commit(client, account, reviewed).status_code == 200
    again = commit(client, account, reviewed)
    assert again.status_code == 409
    assert len(balances_of(client, account)) == 3


@pytest.mark.parametrize("change", [
    {"policy": "replace"},
    {"text": CSV.replace("1200.00", "1200.01")},
    {"text": CSV + "2026-04-30,1300.00,\n"},
])
def test_commit_of_other_rows_or_settings_than_were_reviewed_is_refused(client, account, change):
    reviewed = review(client, account).json()["reviewed"]
    before = everything(client)
    response = commit(client, account, reviewed, **change)
    assert response.status_code == 409
    assert response.json()["dates"] == [] or response.json()["dates"]      # named dates are optional; nothing was written
    assert everything(client) == before


def test_commit_with_a_forged_review_can_only_make_it_refuse(client, account):
    before = everything(client)
    for forged in ({"fingerprint": "0" * 64, "expectations": []},
                   {"fingerprint": review(client, account).json()["reviewed"]["fingerprint"], "expectations": []}):
        assert commit(client, account, forged).status_code == 409
    assert everything(client) == before


def test_commit_of_a_file_with_problems_is_refused(client, account):
    reviewed = review(client, account).json()["reviewed"]
    response = commit(client, account, reviewed, text=CSV + "2026-04-30,oops,\n")
    assert response.status_code == 422
    assert balances_of(client, account) == []


def test_an_import_with_nothing_to_write_writes_nothing(client, account):
    with with_db(client) as conn:
        for day, cents in (("2026-01-31", 100000), ("2026-02-28", 110050), ("2026-03-31", 120000)):
            add_balance(conn, account, day, cents)
        conn.commit()
    before = everything(client)
    reviewed = review(client, account, mapping=SENT).json()["reviewed"]      # no Note column, so the same amounts are the same balances
    response = commit(client, account, reviewed, mapping=SENT)
    assert response.json() == {"added": 0, "updated": 0, "unchanged": 3, "skipped": 0}
    assert everything(client) == before


def test_a_review_and_a_commit_for_a_large_file_fit_in_one_request(client, account):
    """The `reviewed` value has an entry for every date, so a big file's commit is the largest request there is."""
    text = "Date,Balance\n" + "".join(f"{2025 - n // 336}-{(n % 336) // 28 + 1:02d}-{(n % 28) + 1:02d},{n}.00\n" for n in range(1, 19_000))
    reviewed = review(client, account, text=text, mapping=SENT).json()
    assert reviewed["can_commit"] is True and reviewed["counts"]["add"] == 18_999
    response = commit(client, account, reviewed["reviewed"], text=text, mapping=SENT)
    assert response.status_code == 200
    assert response.json()["added"] == 18_999


def test_nothing_from_the_file_reaches_the_log(client, account, caplog):
    secret = "Confidential-note-Z9"
    text = f"Date,Balance,Note\n2026-01-31,31337.31,{secret}\n"
    with caplog.at_level(logging.DEBUG):
        reviewed = review(client, account, text=text).json()["reviewed"]
        commit(client, account, reviewed, text=text)
        review(client, account, text=text + "bad row\n")
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert secret not in logged and "31337" not in logged


def test_the_routes_are_read_from_the_account_in_the_address():
    """No route takes an account from the body: the request models have no account field."""
    for model in (import_api.FileBody, import_api.ReviewBody, import_api.CommitBody):
        assert not any("account" in name for name in model.model_fields)


def test_database_is_left_consistent_after_an_import(client, account):
    reviewed = review(client, account).json()["reviewed"]
    commit(client, account, reviewed)
    with with_db(client) as conn:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
