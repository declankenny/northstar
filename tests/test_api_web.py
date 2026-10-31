from datetime import date

import pytest
from fastapi.testclient import TestClient

from northstar.web.app import create_app

from conftest import add_account, add_balance, sign_in, with_db

TODAY = date(2026, 10, 30)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr("northstar.clock.today", lambda: TODAY)


@pytest.fixture
def household(client):
    """Synthetic. Worked by hand, in cents:
      2026-01-01  house 400,000.00, mortgage 250,000.00     -> 40000000, 25000000, 15000000
      2026-03-15  checking 1,000.00 and savings 2,000.50    -> 40300050, 25000000, 15300050
      2026-06-01  mortgage 249,000.00                       -> 40300050, 24900000, 15400050
    """
    with with_db(client) as conn:
        house = add_account(conn, "House", 1, "Real estate")
        checking = add_account(conn, "Checking", 1, "Checking")
        savings = add_account(conn, "Savings", 1, "Savings")
        mortgage = add_account(conn, "Mortgage", 2, "Mortgage")
        add_balance(conn, house, "2026-01-01", 40000000)
        add_balance(conn, mortgage, "2026-01-01", 25000000)
        add_balance(conn, checking, "2026-03-15", 100000)
        add_balance(conn, savings, "2026-03-15", 200050)
        add_balance(conn, mortgage, "2026-06-01", 24900000)


def rows(body):
    return [(p["date"], p["assets"], p["liabilities"], p["net_worth"]) for p in body["series"]]


def test_no_balances_gives_an_empty_series_and_the_servers_today(client):
    response = client.get("/api/networth")
    assert response.status_code == 200
    assert response.json() == {"today": "2026-10-30", "start": "2026-10-30", "end": "2026-10-30",
                               "period": "month", "series": []}


def test_with_no_parameters_the_series_is_monthly_from_the_first_balance_to_today(client, household):
    body = client.get("/api/networth").json()
    assert (body["today"], body["start"], body["end"], body["period"]) == (
        "2026-10-30", "2026-01-01", "2026-10-30", "month")
    early, middle, late = (40000000, 25000000, 15000000), (40300050, 25000000, 15300050), (40300050, 24900000, 15400050)
    expected = ([("2026-01-01", *early), ("2026-01-31", *early), ("2026-02-28", *early)]
                + [(d, *middle) for d in ("2026-03-31", "2026-04-30", "2026-05-31")]
                + [(d, *late) for d in ("2026-06-30", "2026-07-31", "2026-08-31", "2026-09-30", "2026-10-30")])
    assert rows(body) == expected


def test_start_end_and_period_choose_the_dates(client, household):
    body = client.get("/api/networth", params={"start": "2026-03-01", "end": "2026-03-31", "period": "week"}).json()
    early, middle = (40000000, 25000000, 15000000), (40300050, 25000000, 15300050)
    assert rows(body) == [
        ("2026-03-01", *early), ("2026-03-03", *early), ("2026-03-10", *early),     # before the 03-15 entry
        ("2026-03-17", *middle), ("2026-03-24", *middle), ("2026-03-31", *middle),
    ]


def test_start_is_clamped_to_the_first_balance_and_reported(client, household):
    body = client.get("/api/networth", params={"start": "2020-01-01", "period": "month"}).json()
    assert body["start"] == "2026-01-01" and body["series"][0]["date"] == "2026-01-01"


def test_balances_dated_after_today_are_left_out(client):
    # The app refuses future dates, but the series must not depend on that.
    with with_db(client) as conn:
        acct = add_account(conn, "Checking", 1, "Checking")
        add_balance(conn, acct, "2026-10-30", 500)
        add_balance(conn, acct, "2026-11-02", 900)
    body = client.get("/api/networth").json()
    assert rows(body) == [("2026-10-30", 500, 0, 500)]


def test_amounts_are_integer_cents_and_dates_are_plain_strings(client):
    with with_db(client) as conn:
        acct = add_account(conn, "Loan", 2, "Loan")
        add_balance(conn, acct, "2026-05-01", 123456)
    point = client.get("/api/networth").json()["series"][0]
    assert point == {"date": "2026-05-01", "assets": 0, "liabilities": 123456, "net_worth": -123456}
    assert all(isinstance(point[k], int) for k in ("assets", "liabilities", "net_worth"))


@pytest.mark.parametrize("params, message", [
    ({"end": "2026-10-31"}, "after today"),
    ({"start": "2026-05-01", "end": "2026-04-01"}, "after the end"),
    ({"period": "year"}, "period"),
    ({"start": "nonsense"}, "date"),
])
def test_a_bad_request_is_refused_with_422(client, household, params, message):
    response = client.get("/api/networth", params=params)
    assert response.status_code == 422 and message in response.text


def test_asking_for_too_many_points_is_refused(client):
    with with_db(client) as conn:
        acct = add_account(conn, "Checking", 1, "Checking")
        add_balance(conn, acct, "2000-01-01", 100)
    response = client.get("/api/networth", params={"period": "day"})
    assert response.status_code == 422 and "most allowed" in response.text
    assert client.get("/api/networth", params={"period": "week"}).status_code == 422     # about 1,400 weeks
    assert client.get("/api/networth", params={"period": "month"}).status_code == 200    # about 320 months


def test_the_built_frontend_is_served_at_app_when_it_exists(tmp_path, monkeypatch):
    spa = tmp_path / "spa"
    spa.mkdir()
    (spa / "index.html").write_text("<!doctype html><title>Northstar</title>")
    monkeypatch.setattr("northstar.web.app.SPA_DIR", spa)
    client = sign_in(TestClient(create_app(tmp_path / "web.db")))
    page = client.get("/app/")
    assert page.status_code == 200 and "<title>Northstar</title>" in page.text


def test_without_a_build_there_is_no_app_page_and_nothing_else_changes(tmp_path, monkeypatch):
    monkeypatch.setattr("northstar.web.app.SPA_DIR", tmp_path / "missing")
    client = sign_in(TestClient(create_app(tmp_path / "web.db")))
    assert client.get("/app/").status_code == 404
    assert client.get("/api/networth").status_code == 200


def test_the_api_is_read_only(client):
    assert client.post("/api/networth").status_code == 405
    assert client.put("/api/networth").status_code == 405
    assert client.delete("/api/networth").status_code == 405
