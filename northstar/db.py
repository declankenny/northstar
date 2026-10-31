"""SQLite connection, the migration runner, and the safe way to bring a database up to date."""

import re
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from northstar import backup, clock
from northstar.errors import ValidationError
from northstar.version import VERSION

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# How many backups made before a migration are kept. Older ones are removed after a successful upgrade.
KEEP_BACKUPS = 5
# Recorded by databases made before the migrations were squashed into one. Their numbers are higher than this
# version's own second migration, so without this list such a database would look like it came from a newer version.
LEGACY_MIGRATIONS = frozenset({"0002_users", "0003_user_theme"})
BACKUP_NAME = re.compile(r"^pre-migration-.+-(\d{8}-\d{6})\.db$")


def prepare(path: str | Path) -> None:
    """Create the database's folder if it is missing. SQLite creates the file but not the folder, and the
    default data/ folder is not in a fresh checkout. Starting the app and the command line tools both
    call this before opening the database."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def write_transaction(conn: sqlite3.Connection):
    """Run a check and the write that depends on it as one transaction.

    This is the policy for every operation that reads in order to decide and then writes (closing an
    account, changing a balance, the admin rules): without it another request can change what was
    just checked, and both requests pass. BEGIN IMMEDIATE takes SQLite's write lock at once, so a
    second writer waits here until the first has committed, and then checks against what it left.

    Inside an open transaction this joins it: the outer block commits or rolls back. Any exception
    rolls everything back.
    """
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def connect(path: str | Path) -> sqlite3.Connection:
    """Open the database with foreign keys on. SQLite has them off by default."""
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def migrate(conn: sqlite3.Connection, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply any migration files not yet recorded. Returns the versions applied.

    Each file runs in its own transaction, together with the row that records it.
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version TEXT PRIMARY KEY, "
        "applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')))"
    )
    done = {row["version"] for row in conn.execute("SELECT version FROM schema_migrations")}
    applied = []
    for file in sorted(migrations_dir.glob("*.sql")):
        if file.stem in done:
            continue
        script = (
            "BEGIN;\n"
            + file.read_text(encoding="utf-8")
            + f"\nINSERT INTO schema_migrations (version) VALUES ('{file.stem}');\nCOMMIT;"
        )
        try:
            conn.executescript(script)
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        applied.append(file.stem)
    return applied


def _known(migrations_dir: Path) -> set[str]:
    return {file.stem for file in migrations_dir.glob("*.sql")}


def _recorded(conn: sqlite3.Connection) -> set[str]:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'").fetchone():
        return set()
    return {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}


def _number(version: str) -> int:
    match = re.match(r"\d+", version)
    return int(match.group()) if match else 0


def _newer_than_known(recorded: set[str], known: set[str]) -> list[str]:
    """Recorded migrations this version does not have and that come after its last one. The highest number is
    compared, not the set of names, so a database that recorded other names for older migrations still opens."""
    highest = max((_number(version) for version in known), default=0)
    return sorted(version for version in recorded - known - LEGACY_MIGRATIONS if _number(version) > highest)


def schema_state(conn: sqlite3.Connection, migrations_dir: Path = MIGRATIONS_DIR) -> str:
    """"empty" (a new database), "behind" (a migration is pending), "current", or "ahead" (migrated by a newer version)."""
    known, recorded = _known(migrations_dir), _recorded(conn)
    if not recorded:
        return "empty"
    if _newer_than_known(recorded, known):
        return "ahead"
    return "behind" if known - recorded else "current"


def _backup_folder(path: Path) -> Path:
    return path.parent / "backups"


def _too_new(path: Path, conn: sqlite3.Connection, migrations_dir: Path) -> ValidationError:
    newer = ", ".join(_newer_than_known(_recorded(conn), _known(migrations_dir)))
    return ValidationError(
        f"This database was last used by a newer version of Northstar: it has {newer}, which this version "
        f"({VERSION}) does not know. Run the newer version again, or restore a backup made before the upgrade. "
        f"Backups made before an upgrade are in {_backup_folder(path)}. To restore one, stop the app and run "
        "python -m northstar.backup restore FILE --replace.")


def require_current(conn: sqlite3.Connection, path: str | Path, migrations_dir: Path = MIGRATIONS_DIR) -> None:
    """For the command line tools, which never change the schema: refuse unless the app has already brought
    the database to this version's schema."""
    state = schema_state(conn, migrations_dir)
    if state == "ahead":
        raise _too_new(Path(path), conn, migrations_dir)
    if state != "current":
        raise ValidationError(
            "The database has not been set up or updated by the app yet. Start Northstar once, then run this again.")


def _backups(folder: Path) -> list[Path]:
    """Backups made before a migration, oldest first, ordered by the time in their name (a version such as 0.10.0
    would sort before 0.9.0 as text). Anything else in the folder is not ours and is left out."""
    if not folder.is_dir():
        return []
    found = [(match.group(1), file.name, file) for file in folder.iterdir() if (match := BACKUP_NAME.match(file.name))]
    return [file for _, _, file in sorted(found)]


def prune_backups(folder: Path, keep: int = KEEP_BACKUPS) -> None:
    """Remove all but the newest `keep` backups made before a migration. Failing to remove one is not worth stopping for."""
    found = _backups(folder)
    for file in found[:max(len(found) - keep, 0)]:
        try:
            file.unlink()
        except OSError:
            pass


def upgrade(path: str | Path, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    """Bring the database up to date, safely. Returns the migrations applied.

    A new database is just migrated. A database from a newer version is refused. When a migration is pending, a
    checked backup of the database as it is goes to backups/ beside it first, and if that fails nothing is migrated.
    Old backups are removed only once the migration has worked.
    """
    path = Path(path)
    prepare(path)
    with closing(connect(path)) as conn:
        state = schema_state(conn, migrations_dir)
        if state == "ahead":
            raise _too_new(path, conn, migrations_dir)
        if state == "behind":
            folder = _backup_folder(path)
            folder.mkdir(exist_ok=True)
            stamp = clock.now().strftime("%Y%m%d-%H%M%S")
            backup.create_backup(path, folder / f"pre-migration-{VERSION}-{stamp}.db")
        applied = migrate(conn, migrations_dir)
        if state == "behind":
            prune_backups(folder)
    return applied
