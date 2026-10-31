import pytest

from conftest import add_account, add_balance, type_id, with_db


def by_name(body):
    return {t["name"]: t for t in body["types"]}


@pytest.fixture
def in_use(client):
    """Two accounts use Savings, one uses Mortgage. Synthetic."""
    with with_db(client) as conn:
        add_account(conn, "A", 1, "Savings")
        add_account(conn, "B", 1, "Savings")
        add_account(conn, "C", 2, "Mortgage")


def test_the_list_has_each_types_class_stale_days_and_account_count(client, in_use):
    body = client.get("/api/types").json()
    types = by_name(body)
    assert (types["Savings"]["class_name"], types["Savings"]["account_count"], types["Savings"]["stale_after_days"]) == ("Asset", 2, 35)
    assert types["Mortgage"]["class_name"] == "Liability" and types["Mortgage"]["account_count"] == 1
    assert types["Checking"]["account_count"] == 0
    assert [c["name"] for c in body["classes"]] == ["Asset", "Liability"]


def test_the_list_is_ordered_by_class_then_creation(client):
    classes = [t["class_name"] for t in client.get("/api/types").json()["types"]]
    assert classes == sorted(classes, key=["Asset", "Liability"].index)


def test_add_a_type_answers_with_the_new_list(client):
    response = client.post("/api/types", json={"name": " Crypto ", "class_id": 1, "stale_after_days": 10})
    assert response.status_code == 201
    row = by_name(response.json())["Crypto"]
    assert (row["class_name"], row["stale_after_days"], row["account_count"]) == ("Asset", 10, 0)


@pytest.mark.parametrize("fields, message", [
    ({"name": " "}, "Name is required"),
    ({"name": "checking"}, "already exists"),              # names ignore case
    ({"class_id": 99}, "Choose Asset or Liability"),
    ({"stale_after_days": 0}, "at least 1"),
])
def test_a_bad_new_type_is_refused_with_422_and_adds_nothing(client, fields, message):
    before = len(client.get("/api/types").json()["types"])
    body = {"name": "Crypto", "class_id": 1, "stale_after_days": 10}
    body.update(fields)
    response = client.post("/api/types", json=body)
    assert response.status_code == 422 and message in response.text
    assert len(client.get("/api/types").json()["types"]) == before


def test_edit_renames_and_changes_stale_days(client, in_use):
    with with_db(client) as conn:
        savings = type_id(conn, "Savings")
    body = client.patch(f"/api/types/{savings}", json={"name": "Savings accounts", "stale_after_days": 60}).json()
    row = by_name(body)["Savings accounts"]
    assert (row["stale_after_days"], row["account_count"], row["class_name"]) == (60, 2, "Asset")


def test_the_class_changes_only_while_no_account_uses_the_type(client, in_use):
    with with_db(client) as conn:
        savings, checking = type_id(conn, "Savings"), type_id(conn, "Checking")
    refused = client.patch(f"/api/types/{savings}", json={"name": "Savings", "stale_after_days": 35, "class_id": 2})
    assert refused.status_code == 422 and "can't change while accounts use" in refused.text
    moved = client.patch(f"/api/types/{checking}", json={"name": "Checking", "stale_after_days": 35, "class_id": 2}).json()
    assert by_name(moved)["Checking"]["class_name"] == "Liability"


def test_sending_the_same_class_for_a_type_in_use_is_fine(client, in_use):
    with with_db(client) as conn:
        savings = type_id(conn, "Savings")
    assert client.patch(f"/api/types/{savings}", json={"name": "Savings", "stale_after_days": 40, "class_id": 1}).status_code == 200


def test_renaming_onto_another_types_name_is_refused(client):
    with with_db(client) as conn:
        savings = type_id(conn, "Savings")
    response = client.patch(f"/api/types/{savings}", json={"name": "CHECKING", "stale_after_days": 35})
    assert response.status_code == 422 and "already exists" in response.text


def test_delete_removes_an_unused_type(client):
    with with_db(client) as conn:
        loan = type_id(conn, "Loan")
    body = client.delete(f"/api/types/{loan}").json()
    assert "Loan" not in by_name(body)
    assert client.delete(f"/api/types/{loan}").status_code == 404


def test_delete_refuses_a_type_in_use_and_says_how_many(client, in_use):
    with with_db(client) as conn:
        savings = type_id(conn, "Savings")
    response = client.delete(f"/api/types/{savings}")
    assert response.status_code == 422 and "2 accounts use this type" in response.text
    assert "Savings" in by_name(client.get("/api/types").json())


def test_an_unknown_type_is_a_404(client):
    assert client.patch("/api/types/9999", json={"name": "x", "stale_after_days": 1}).status_code == 404
    assert client.delete("/api/types/9999").status_code == 404


# ---- admins only ----

def test_an_ordinary_user_is_refused_on_every_type_endpoint(member_client):
    assert member_client.get("/api/types").status_code == 403
    assert member_client.post("/api/types", json={"name": "x", "class_id": 1, "stale_after_days": 5}).status_code == 403
    assert member_client.patch("/api/types/1", json={"name": "x", "stale_after_days": 5}).status_code == 403
    assert member_client.delete("/api/types/1").status_code == 403


def test_an_ordinary_user_is_refused_on_the_classic_type_pages_too(member_client):
    assert member_client.get("/types").status_code == 403
    assert member_client.post("/types", data={"name": "x", "class_id": "1", "stale_after_days": "5"}).status_code == 403
    assert member_client.post("/types/1", data={"name": "x", "stale_after_days": "5"}).status_code == 403
    assert member_client.post("/types/1/delete").status_code == 403
    with with_db(member_client) as conn:
        assert conn.execute("SELECT COUNT(*) FROM account_types WHERE name = 'x'").fetchone()[0] == 0


def test_an_admin_still_sees_the_classic_page_and_its_nav_link(client):
    page = client.get("/types")
    assert page.status_code == 200
    assert 'href="/types"' in client.get("/").text


def test_the_classic_nav_hides_account_types_from_an_ordinary_user(member_client):
    assert 'href="/types"' not in member_client.get("/").text


def test_an_ordinary_user_is_told_to_ask_an_admin_when_a_class_has_no_types(member_client):
    with with_db(member_client) as conn:
        conn.execute("DELETE FROM account_types WHERE class_id = 2")
    page = member_client.get("/accounts/new?class=liability")
    assert "Ask an admin to add one" in page.text and 'href="/types"' not in page.text


def test_signed_out_requests_get_401(anon_client):
    assert anon_client.get("/api/types").status_code == 401
    assert anon_client.delete("/api/types/1").status_code == 401


def test_a_cross_site_change_is_refused(client):
    response = client.post("/api/types", json={"name": "x", "class_id": 1, "stale_after_days": 5},
                           headers={"origin": "https://evil.example"})
    assert response.status_code == 403
    assert "x" not in by_name(client.get("/api/types").json())
