from conftest import with_db


def type_count(client, name):
    with with_db(client) as conn:
        return conn.execute("SELECT COUNT(*) FROM account_types WHERE name = ?", (name,)).fetchone()[0]


def test_cross_site_post_is_refused(client):
    response = client.post("/api/types", json={"name": "Evil", "class_id": 1, "stale_after_days": 35},
                           headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    assert type_count(client, "Evil") == 0


def test_same_site_post_is_allowed(client):
    response = client.post("/api/types", json={"name": "Fine", "class_id": 1, "stale_after_days": 35},
                           headers={"Origin": "http://testserver"})
    assert response.status_code == 201
    assert type_count(client, "Fine") == 1
