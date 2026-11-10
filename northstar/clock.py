"""The only place the app asks what the date and time are, so tests can fix them.

`now()` is an absolute UTC instant and never changes with the installation's time zone: sign-in throttling subtracts
durations from it, and a local time would be wrong across a daylight-saving change. `today()` is the date of `now()` in
the installation's zone, the `system.timezone` system property. The zone is held here, set at startup and whenever that
property is saved (see system_properties.py), so `today()` needs no database. With no zone set it is UTC.
"""

import logging
import os
import sqlite3
from datetime import date, datetime, timezone, tzinfo
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

_zone: tzinfo = timezone.utc


def zone_for(name: str) -> ZoneInfo:
    """The zone with this IANA name. Raises ValueError for a name that is not one in the zone database."""
    try:
        return ZoneInfo(name)
    except (KeyError, ValueError, OSError):       # not found, malformed, or a folder or file that is not a zone
        raise ValueError(f"{name!r} is not a time zone name") from None


def set_zone(name: str | None) -> None:
    """Make `name` the installation's zone for `today()`. None means UTC."""
    global _zone
    _zone = timezone.utc if not name else zone_for(name)


def today() -> date:
    """Today's date in the installation's time zone."""
    return now().astimezone(_zone).date()


def register(conn: sqlite3.Connection) -> None:
    """Make `northstar_today()` available to SQL on this connection: today's date as `YYYY-MM-DD`, from `today()` at the moment
    it is called (so a test that fixes the clock fixes it here too). Not deterministic, so SQLite never caches it."""
    conn.create_function("northstar_today", 0, lambda: today().isoformat())


def now() -> datetime:
    """The current moment, in UTC. Used for sign-in throttling, which needs a time and not just a date."""
    return datetime.now(timezone.utc)


def start_zone(stored: str | None, environment: str | None = None) -> tuple[str | None, str | None]:
    """Work out the zone at startup. `stored` is the system.timezone property and `environment` the TZ variable (read from
    the process when not given). Returns the name to use, None for UTC, and the name to save into the property, which is
    set only when the property was empty and TZ names a real zone. Logs a warning for a TZ that is not a zone name, for
    a stored name this machine cannot read, and for a TZ that differs from the stored zone, which is the one used."""
    env = os.environ.get("TZ") if environment is None else environment
    env = env.strip() if env else None
    if stored:
        try:
            zone_for(stored)
        except ValueError:
            log.error("The system.timezone setting is %r, which this machine has no zone data for. Using UTC.", stored)
            return None, None
        if env and env != stored:
            log.warning("The TZ environment variable is %r but the system.timezone setting is %r. The setting is used, "
                        "and TZ is ignored once the setting has a value.", env, stored)
        return stored, None
    if env:
        try:
            zone_for(env)
        except ValueError:
            log.warning("The TZ environment variable is %r, which is not a time zone name this machine knows. Using UTC.", env)
            return None, None
        return env, env
    return None, None
