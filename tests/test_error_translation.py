"""A broken rule becomes the same response everywhere, decided by the error's type and never by its message."""

import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from northstar import users
from northstar.balance_import import StaleImport
from northstar.balances import EntryErrors
from northstar.errors import NotFoundError, ValidationError
from northstar.web import errors
from conftest import with_db

WEB = Path(__file__).resolve().parent.parent / "northstar" / "web"


class MissingThing(NotFoundError):
    pass


def raising(error):
    app = FastAPI()
    errors.install(app)

    @app.get("/boom")
    def boom():
        raise error

    return TestClient(app)


@pytest.mark.parametrize("error, status", [
    (ValidationError("Nope."), 422),
    (NotFoundError("Gone."), 404),
    (MissingThing("A subtype of not found."), 404),
    (StaleImport("Review again."), 409),
    (EntryErrors("Fix these.", {3: "bad"}), 422),
])
def test_status_comes_from_the_type(error, status):
    response = raising(error).get("/boom")
    assert response.status_code == status
    assert response.json()["detail"] == str(error)


@pytest.mark.parametrize("message", ["That user no longer exists.", "Something else entirely.", ""])
def test_rewording_a_message_changes_no_status(message):
    assert raising(NotFoundError(message)).get("/boom").status_code == 404
    assert raising(ValidationError(message)).get("/boom").status_code == 422


def test_errors_put_their_details_in_the_body():
    stale = raising(StaleImport("Review again.", ["2026-01-31", "2026-02-28"])).get("/boom").json()
    assert stale == {"detail": "Review again.", "dates": ["2026-01-31", "2026-02-28"]}
    assert raising(StaleImport("Different file.")).get("/boom").json() == {"detail": "Different file.", "dates": []}
    entries = raising(EntryErrors("Fix these.", {3: "bad"})).get("/boom").json()
    assert entries == {"detail": "Fix these.", "errors": {"3": "bad"}}


def test_a_missing_user_is_not_found_by_type(client):
    with with_db(client) as conn:
        with pytest.raises(NotFoundError):
            users.get_user(conn, 99999)
    assert client.patch("/api/users/99999", json={"is_admin": True}).status_code == 404
    assert client.delete("/api/users/99999").status_code == 404


def test_the_real_app_answers_through_the_same_handler(client):
    assert client.get("/api/accounts/99999").status_code == 404
    assert client.get("/api/networth?account_id=99999").status_code == 404
    assert client.get("/api/balances/update?date=not-a-date").status_code == 422


# Routes do not translate broken rules themselves; they let them reach the handler. The one exception is profile_api, whose
# password change catches the error only to count the attempt against the throttle, and re-raises it.
CATCHES = re.compile(r"except\s+[\w.,\s()]*\b(NotFoundError|ValidationError|EntryErrors|StaleImport)\b")
ALLOWED = {"profile_api.py"}


def test_no_route_module_catches_a_broken_rule_itself():
    found = [path.name for path in sorted(WEB.glob("*.py")) if path.name not in ALLOWED and path.name != "errors.py"
             and CATCHES.search(path.read_text(encoding="utf-8"))]
    assert not found, f"{found} catch domain errors; let northstar.web.errors translate them"


def test_no_route_module_has_its_own_run_wrapper():
    found = [path.name for path in sorted(WEB.glob("*.py")) if re.search(r"^def _run\(", path.read_text(encoding="utf-8"), re.M)]
    assert not found, f"{found} define _run; use auth_routes.run"
