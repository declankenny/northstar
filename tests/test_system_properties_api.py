import pytest

from conftest import with_db

URL = "/api/system-properties"


def by_name(body):
    return {p["name"]: p for p in body["properties"]}


def test_the_list_has_each_property_with_its_type_hint_and_options(client):
    body = client.get(URL).json()
    props = by_name(body)
    assert [p["name"] for p in body["properties"]] == sorted(props)
    stale = props["balance.stale"]
    assert (stale["type"], stale["value"], stale["allow_null"], stale["read_only"], stale["options"]) == ("Integer", "35", False, False, [])
    assert stale["hint"]
    assert [o["value"] for o in props["ui.theme.default"]["options"]] == ["light", "dark"]
    assert props["ui.theme.default"]["options"][0] == {"value": "light", "label": "Light"}


def test_a_save_answers_with_the_whole_list_as_it_now_is(client):
    response = client.put(f"{URL}/balance.stale", json={"value": "45"})
    assert response.status_code == 200
    assert by_name(response.json())["balance.stale"]["value"] == "45"
    assert by_name(client.get(URL).json())["balance.stale"]["value"] == "45"


def test_a_lookup_can_be_saved_and_the_change_is_logged_to_the_signed_in_admin(client):
    assert client.put(f"{URL}/ui.theme.default", json={"value": "light"}).status_code == 200
    with with_db(client) as conn:
        row = conn.execute(
            "SELECT o.kind, u.email, c.old_json, c.new_json FROM sys_record_changes c "
            "JOIN sys_operations o ON o.id = c.operation_id JOIN users u ON u.id = o.user_id "
            "WHERE c.tablename = 'system_properties'").fetchone()
    assert (row["kind"], row["email"]) == ("ui_edit", "test@example.com")
    assert row["old_json"] == '{"value": "dark"}' and row["new_json"] == '{"value": "light"}'


@pytest.mark.parametrize("name, value, message", [
    ("balance.stale", "abc", "Enter a whole number."),
    ("balance.stale", "0", "of 1 or more"),
    ("balance.stale", "", "This setting is required."),
    ("balance.stale", None, "This setting is required."),
    ("ui.theme.default", "purple", "Choose one of the listed options."),
])
def test_a_refused_value_is_a_422_with_its_message_and_nothing_changes(client, name, value, message):
    before = by_name(client.get(URL).json())[name]["value"]
    response = client.put(f"{URL}/{name}", json={"value": value})
    assert response.status_code == 422 and message in response.json()["detail"]
    assert by_name(client.get(URL).json())[name]["value"] == before


def test_an_unknown_property_is_a_404(client):
    response = client.put(f"{URL}/no.such.setting", json={"value": "1"})
    assert response.status_code == 404 and "doesn't exist" in response.json()["detail"]


def test_a_locked_property_is_a_422(client):
    with with_db(client) as conn:
        conn.execute("UPDATE system_properties SET read_only = 1 WHERE name = 'balance.stale'")
    response = client.put(f"{URL}/balance.stale", json={"value": "31"})
    assert response.status_code == 422 and "locked" in response.json()["detail"]
    assert by_name(client.get(URL).json())["balance.stale"]["read_only"] is True


def test_a_save_of_the_same_value_changes_nothing(client):
    assert client.put(f"{URL}/balance.stale", json={"value": " 35 "}).status_code == 200
    with with_db(client) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sys_record_changes WHERE tablename = 'system_properties'").fetchone()[0] == 0


def test_a_missing_value_is_treated_as_blank(client):
    assert client.put(f"{URL}/balance.stale", json={}).status_code == 422


def test_ordinary_users_cannot_read_or_change_properties(member_client):
    assert member_client.get(URL).status_code == 403
    assert member_client.put(f"{URL}/balance.stale", json={"value": "45"}).status_code == 403


def test_signed_out_visitors_get_401(anon_client):
    assert anon_client.get(URL).status_code == 401
    assert anon_client.put(f"{URL}/balance.stale", json={"value": "45"}).status_code == 401
