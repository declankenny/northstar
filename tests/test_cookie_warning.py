"""The startup warning when the sign-in cookie is not marked Secure."""

import logging

import pytest

from northstar.web.app import create_app


def warnings_about_the_cookie(caplog):
    return [r for r in caplog.records if r.levelno >= logging.WARNING and "NORTHSTAR_COOKIE_SECURE" in r.getMessage()]


def start(tmp_path, caplog):
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        create_app(tmp_path / "web.db")


def test_starting_without_the_setting_warns_loudly_and_says_what_to_do(tmp_path, caplog, monkeypatch):
    monkeypatch.delenv("NORTHSTAR_COOKIE_SECURE", raising=False)
    start(tmp_path, caplog)
    found = warnings_about_the_cookie(caplog)
    assert len(found) == 1
    message = found[0].getMessage()
    assert "plain HTTP" in message and "NORTHSTAR_COOKIE_SECURE=1" in message and "HTTPS" in message


def test_starting_with_the_setting_does_not_warn(tmp_path, caplog, monkeypatch):
    monkeypatch.setenv("NORTHSTAR_COOKIE_SECURE", "1")
    start(tmp_path, caplog)
    assert warnings_about_the_cookie(caplog) == []


@pytest.mark.parametrize("value", ["true", "yes", "0", "on", ""])
def test_any_value_other_than_1_still_warns_because_it_does_not_turn_the_flag_on(tmp_path, caplog, monkeypatch, value):
    """The flag is only on for exactly 1, so a well-meant "true" must not silence the warning."""
    monkeypatch.setenv("NORTHSTAR_COOKIE_SECURE", value)
    start(tmp_path, caplog)
    found = warnings_about_the_cookie(caplog)
    assert len(found) == 1 and "exactly 1" in found[0].getMessage()
