"""Host-only command to get back in when password sign-in has been switched off (see docs/design/oidc). Plain functions.

`python -m northstar.signin enable-local` turns the system property `system.auth.local.enabled` back on. It works with no
web session and no connection to the identity provider, because it only needs the database file, so it is the way back
in when the provider is down or misconfigured. After it, `python -m northstar.users set-password EMAIL` can give an
admin a password to sign in with.
"""

import argparse
import sys
from contextlib import closing

from northstar import config, db, system_properties
from northstar.errors import ValidationError
from northstar.writer import Operation


def enable_local(op: Operation) -> bool:
    """Turn password sign-in on, as the system user. Returns False when it was already on, in which case nothing is written."""
    conn = op.conn
    already = system_properties.get_value(conn, system_properties.LOCAL_SIGNIN) is True
    system_properties.set_property(op, system_properties.LOCAL_SIGNIN, "true")
    return not already


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m northstar.signin",
        description="Sign-in settings that can be fixed from the host (NORTHSTAR_DB, default data/northstar.db).")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("enable-local", help="turn password sign-in back on")
    parser.parse_args(argv)
    try:
        path = config.database_path()
        if not path.is_file():      # connecting would create an empty one, and only the app sets a database up
            raise ValidationError(f"There is no database at {path}. Start Northstar once to set one up, then run this again.")
        with closing(db.connect(path)) as conn:
            db.require_current(conn, path)
            changed = enable_local(Operation(conn, None, "cli"))      # the command line has no signed-in user
        print("Password sign-in is now on." if changed else "Password sign-in was already on. Nothing changed.")
    except ValidationError as err:
        print(f"Error: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
