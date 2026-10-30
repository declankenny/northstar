import pytest
from fastapi.testclient import TestClient

from northstar import db
from northstar.web.app import create_app

from conftest import add_account, type_id


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path / "web.db"))


def with_db(client):
    return db.connect(client.app.state.db_path)


def type_row(client, name):
    with with_db(client) as conn:
        return conn.execute("SELECT * FROM account_types WHERE name = ?", (name,)).fetchone()


def test_home_redirects_to_types_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.url.path == "/types"
    assert "Real estate" in response.text and "365" in response.text


def test_add_type(client):
    response = client.post("/types", data={"name": "529 plan", "class_id": "1", "stale_after_days": "90"})
    assert response.status_code == 200  # followed the redirect back to the page
    row = type_row(client, "529 plan")
    assert (row["class_id"], row["stale_after_days"]) == (1, 90)


def test_add_type_error_shows_message_and_keeps_input(client):
    response = client.post("/types", data={"name": "checking", "class_id": "2", "stale_after_days": "20"})
    assert response.status_code == 400
    assert "already exists" in response.text
    assert 'value="checking"' in response.text
    assert 'value="20"' in response.text


def test_edit_type(client):
    tid = type_row(client, "Savings")["id"]
    client.post(f"/types/{tid}", data={"name": "High-yield savings", "stale_after_days": "60", "class_id": "1"})
    row = type_row(client, "High-yield savings")
    assert row["id"] == tid and row["stale_after_days"] == 60


def test_edit_type_bad_days_is_refused(client):
    tid = type_row(client, "Savings")["id"]
    response = client.post(f"/types/{tid}", data={"name": "Savings", "stale_after_days": "0"})
    assert response.status_code == 400
    assert "whole number" in response.text
    assert type_row(client, "Savings")["stale_after_days"] == 35


def test_delete_button_only_appears_for_unused_types(client):
    with with_db(client) as conn:
        add_account(conn, "Test account", 1, "Checking")
        checking, savings = type_id(conn, "Checking"), type_id(conn, "Savings")
    page = client.get("/types").text
    assert f"/types/{savings}/delete" in page
    assert f"/types/{checking}/delete" not in page


def test_delete_unused_type(client):
    tid = type_row(client, "Savings")["id"]
    client.post(f"/types/{tid}/delete")
    assert type_row(client, "Savings") is None


def test_delete_type_in_use_is_refused_even_if_the_button_is_bypassed(client):
    with with_db(client) as conn:
        add_account(conn, "Test account", 1, "Checking")
    tid = type_row(client, "Checking")["id"]
    response = client.post(f"/types/{tid}/delete")
    assert response.status_code == 400
    assert "1 account uses this type" in response.text
    assert type_row(client, "Checking") is not None


def test_class_of_type_in_use_cannot_be_changed(client):
    with with_db(client) as conn:
        add_account(conn, "Test account", 1, "Checking")
    tid = type_row(client, "Checking")["id"]
    response = client.post(f"/types/{tid}", data={"name": "Checking", "stale_after_days": "35", "class_id": "2"})
    assert response.status_code == 400
    assert type_row(client, "Checking")["class_id"] == 1


def test_names_are_escaped_in_the_page(client):
    client.post("/types", data={"name": "<script>alert(1)</script>", "class_id": "1", "stale_after_days": "35"})
    page = client.get("/types").text
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


def test_cross_site_post_is_refused(client):
    response = client.post(
        "/types", data={"name": "Evil", "class_id": "1", "stale_after_days": "35"},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403
    assert type_row(client, "Evil") is None


def test_same_site_post_is_allowed(client):
    response = client.post(
        "/types", data={"name": "Fine", "class_id": "1", "stale_after_days": "35"},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    assert type_row(client, "Fine") is not None
