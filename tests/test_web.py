from fastapi.testclient import TestClient

from northstar.web.app import create_app


def test_index_page_lists_the_starting_types(tmp_path):
    client = TestClient(create_app(tmp_path / "web.db"))
    response = client.get("/")
    assert response.status_code == 200
    assert "Northstar" in response.text
    assert "Real estate" in response.text
    assert "365" in response.text
