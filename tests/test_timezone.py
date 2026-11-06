"""The installation's time zone: the system.timezone property, what "today" is, and the startup copy of TZ.
Synthetic data only."""

import logging
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from northstar import clock, system_properties as sp, throttle
from northstar.errors import ValidationError
from northstar.web.app import create_app
from tests.conftest import op, sign_in

NAME = "system.timezone"


def stored(conn):
    return conn.execute("SELECT value FROM system_properties WHERE name = ?", (NAME,)).fetchone()[0]


def at(moment_utc, monkeypatch):
    monkeypatch.setattr(clock, "now", lambda: moment_utc)


# -- the property --

def test_the_property_exists_empty_and_optional(conn):
    row = conn.execute("SELECT value, allow_null, read_only FROM system_properties WHERE name = ?", (NAME,)).fetchone()
    assert tuple(row) == (None, 1, 0)
    assert conn.execute("SELECT validator FROM ref_property_validators v JOIN system_properties p ON p.id = v.property_id "
                        "WHERE p.name = ?", (NAME,)).fetchall()[0][0] == "iana_timezone"


def test_a_zone_name_is_saved_and_clears_back_to_empty(conn):
    assert sp.set_property(op(conn), NAME, " America/Chicago ") == "America/Chicago"
    assert stored(conn) == "America/Chicago"
    assert sp.set_property(op(conn), NAME, "") is None
    assert stored(conn) is None


@pytest.mark.parametrize("bad", ["Mars/Olympus", "chicago", "America", "../etc/passwd", "UTC+5x", "zone.tab", "a" * 300])
def test_a_name_that_is_not_a_zone_is_refused_and_nothing_is_saved(conn, bad):
    with pytest.raises(ValidationError):
        sp.set_property(op(conn), NAME, bad)
    assert stored(conn) is None


def test_saving_the_zone_sets_the_clock_but_a_refused_save_does_not(conn, monkeypatch):
    at(datetime(2026, 11, 7, 3, 30, tzinfo=timezone.utc), monkeypatch)
    assert str(clock.today()) == "2026-11-07"
    sp.set_property(op(conn), NAME, "America/Chicago")
    assert str(clock.today()) == "2026-11-06"
    with pytest.raises(ValidationError):
        sp.set_property(op(conn), NAME, "Mars/Olympus")
    assert str(clock.today()) == "2026-11-06"


# -- the clock --

def test_with_no_zone_today_is_the_utc_date(monkeypatch):
    at(datetime(2026, 11, 7, 3, 30, tzinfo=timezone.utc), monkeypatch)
    assert str(clock.today()) == "2026-11-07"


def test_today_changes_at_midnight_in_the_zone_not_in_utc(monkeypatch):
    clock.set_zone("America/Chicago")           # UTC-5 until November 1, 2026, UTC-6 after
    at(datetime(2026, 7, 4, 4, 59, tzinfo=timezone.utc), monkeypatch)
    assert str(clock.today()) == "2026-07-03"
    at(datetime(2026, 7, 4, 5, 0, tzinfo=timezone.utc), monkeypatch)
    assert str(clock.today()) == "2026-07-04"
    at(datetime(2026, 12, 5, 5, 59, tzinfo=timezone.utc), monkeypatch)
    assert str(clock.today()) == "2026-12-04"
    at(datetime(2026, 12, 5, 6, 0, tzinfo=timezone.utc), monkeypatch)
    assert str(clock.today()) == "2026-12-05"


def test_a_zone_ahead_of_utc_is_a_day_ahead_late_in_the_utc_day(monkeypatch):
    clock.set_zone("Pacific/Auckland")
    at(datetime(2026, 7, 4, 13, 0, tzinfo=timezone.utc), monkeypatch)       # 01:00 on the 5th in Auckland
    assert str(clock.today()) == "2026-07-05"


def test_today_follows_a_daylight_saving_change_without_a_gap_or_a_repeat(monkeypatch):
    clock.set_zone("America/Chicago")           # clocks go back on November 1, 2026 at 07:00 UTC
    days = []
    moment = datetime(2026, 10, 31, 4, 0, tzinfo=timezone.utc)
    for _ in range(60):
        at(moment, monkeypatch)
        if not days or days[-1] != str(clock.today()):
            days.append(str(clock.today()))
        moment += timedelta(hours=1)
    assert days == ["2026-10-30", "2026-10-31", "2026-11-01", "2026-11-02"]


def test_now_stays_a_utc_instant_whatever_the_zone_is():
    clock.set_zone("Asia/Kolkata")
    assert clock.now().utcoffset() == timedelta(0)
    assert clock.now().tzinfo is timezone.utc


def test_the_sign_in_throttle_gives_the_same_result_in_any_zone(conn):
    moment = datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc)
    results = []
    for zone in (None, "America/Chicago", "Pacific/Auckland"):
        clock.set_zone(zone)
        conn.execute("DELETE FROM sys_login_attempts")
        throttle.begin(conn, "a@example.com", "10.0.0.1", moment)
        throttle.begin(conn, "a@example.com", "10.0.0.1", moment + timedelta(seconds=5))
        results.append(conn.execute("SELECT * FROM sys_login_attempts ORDER BY rowid").fetchall())
    assert [[tuple(r) for r in rows] for rows in results[1:]] == [[tuple(r) for r in results[0]]] * 2


def test_a_name_the_machine_cannot_read_is_not_a_zone():
    with pytest.raises(ValueError):
        clock.set_zone("Mars/Olympus")
    assert clock.now().tzinfo is timezone.utc


# -- startup: the stored zone and TZ --

def test_a_first_start_with_tz_saves_it_once_as_the_system_user_and_uses_it(conn):
    sp.apply_timezone(conn, "America/Chicago")
    assert stored(conn) == "America/Chicago"
    kind, user = conn.execute("SELECT kind, user_id FROM sys_operations ORDER BY id DESC").fetchone()
    assert kind == "cli" and user == conn.execute("SELECT id FROM users WHERE is_system = 1").fetchone()[0]
    clock.set_zone(None)
    sp.apply_timezone(conn, "Europe/London")      # the setting has a value now, so TZ no longer counts
    assert stored(conn) == "America/Chicago"


def test_the_stored_zone_is_used_and_a_different_tz_is_warned_about_and_ignored(conn, caplog):
    sp.set_property(op(conn), NAME, "Europe/London")
    with caplog.at_level(logging.WARNING):
        sp.apply_timezone(conn, "America/Chicago")
    assert stored(conn) == "Europe/London"
    assert "TZ" in caplog.text and "Europe/London" in caplog.text
    assert clock.zone_for("Europe/London").key == "Europe/London"


def test_the_same_tz_as_the_stored_zone_is_not_warned_about(conn, caplog):
    sp.set_property(op(conn), NAME, "Europe/London")
    with caplog.at_level(logging.WARNING):
        sp.apply_timezone(conn, "Europe/London")
    assert caplog.text == ""


def test_with_neither_the_property_stays_empty_and_today_is_utc(conn, monkeypatch):
    sp.apply_timezone(conn, None)
    sp.apply_timezone(conn, "")
    assert stored(conn) is None
    at(datetime(2026, 11, 7, 3, 30, tzinfo=timezone.utc), monkeypatch)
    assert str(clock.today()) == "2026-11-07"


def test_a_tz_that_is_not_a_zone_is_warned_about_and_nothing_is_saved(conn, caplog):
    with caplog.at_level(logging.WARNING):
        sp.apply_timezone(conn, "Mars/Olympus")
    assert stored(conn) is None
    assert "Mars/Olympus" in caplog.text


def test_a_stored_name_the_machine_has_no_data_for_falls_back_to_utc_and_says_so(conn, caplog):
    conn.execute("UPDATE system_properties SET value = 'Mars/Olympus' WHERE name = ?", (NAME,))
    with caplog.at_level(logging.ERROR):
        sp.apply_timezone(conn, None)
    assert "Mars/Olympus" in caplog.text
    assert clock.now().tzinfo is timezone.utc


def test_the_environment_is_read_when_no_value_is_passed(monkeypatch):
    monkeypatch.setenv("TZ", "Asia/Tokyo")
    assert clock.start_zone(None) == ("Asia/Tokyo", "Asia/Tokyo")
    monkeypatch.setenv("TZ", "  ")
    assert clock.start_zone(None) == (None, None)


# -- through the app --

def test_creating_the_app_copies_tz_once_and_uses_it(tmp_path, monkeypatch):
    monkeypatch.setenv("TZ", "America/Chicago")
    client = sign_in(TestClient(create_app(tmp_path / "web.db")))
    rows = {p["name"]: p["value"] for p in client.get("/api/system-properties").json()["properties"]}
    assert rows[NAME] == "America/Chicago"
    at_utc = datetime(2026, 11, 7, 3, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(clock, "now", lambda: at_utc)
    assert str(clock.today()) == "2026-11-06"
    monkeypatch.setenv("TZ", "Europe/London")
    again = create_app(tmp_path / "web.db")          # a second start: the property already has a value
    assert again is not None
    assert str(clock.today()) == "2026-11-06"


def test_an_admin_changes_the_zone_on_the_settings_page_and_today_follows(client, monkeypatch):
    at_utc = datetime(2026, 11, 7, 3, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(clock, "now", lambda: at_utc)
    assert str(clock.today()) == "2026-11-07"
    saved = client.put(f"/api/system-properties/{NAME}", json={"value": "America/Chicago"})
    assert saved.status_code == 200, saved.text
    assert str(clock.today()) == "2026-11-06"
    refused = client.put(f"/api/system-properties/{NAME}", json={"value": "Mars/Olympus"})
    assert refused.status_code == 422 and "time zone" in refused.json()["detail"]
    assert str(clock.today()) == "2026-11-06"
