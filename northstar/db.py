"""SQLite connection, the migration runner, and the safe way to bring a database up to date."""

import re
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import dataclass
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
# The record of applied migrations. Releases before 0.2 called it schema_migrations. The runner moves it (see
# _prepare_ledger) because every table the app owns apart from the data itself carries the sys_ prefix.
LEDGER = "sys_schema_migrations"
OLD_LEDGER = "schema_migrations"
LEDGER_COLUMNS = [("version", 1), ("applied_at", 0)]    # name and primary key position, in order
# A migration whose first line is this is run with foreign keys off, so it can drop and recreate a table.
REBUILD_MARK = "-- northstar: rebuild"
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


@dataclass(frozen=True)
class Ledger:
    """What the database's record of applied migrations looks like, read without changing anything."""
    recorded: set[str]
    rename: bool = False      # the history is in the old ledger, which must be renamed
    drop_old: bool = False    # an empty old ledger is left over (see _inspect_ledgers) and must be dropped


def _refuse_ledger(reason: str) -> ValidationError:
    return ValidationError(
        f"The database has a migration ledger that this version cannot use: {reason}. Nothing was changed or deleted. "
        "Restore a backup made before the problem, or ask for help before editing the database by hand.")


def _inspect_ledgers(conn: sqlite3.Connection) -> Ledger:
    """Classify the migration record, read-only. Two ledgers exist when an older app was started on a database the
    newer one had already migrated: it creates an empty schema_migrations, fails to migrate, and leaves that behind.
    That empty old ledger beside a valid populated new one is the only combination that is cleaned up. Everything else
    that is not one valid ledger is refused, because guessing which history is true could lose data."""
    present = [name for name in (LEDGER, OLD_LEDGER) if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone()]
    versions = {}
    for name in present:
        columns = [(row[1], row[5]) for row in conn.execute(f"PRAGMA table_info({name})")]
        if columns != LEDGER_COLUMNS:
            raise _refuse_ledger(f"{name} does not have the columns {', '.join(c for c, _ in LEDGER_COLUMNS)}")
        versions[name] = {row[0] for row in conn.execute(f"SELECT version FROM {name}")}
    if len(present) == 2:
        if versions[OLD_LEDGER]:
            raise _refuse_ledger(f"both {OLD_LEDGER} and {LEDGER} hold history")
        if not versions[LEDGER]:
            raise _refuse_ledger(f"both {OLD_LEDGER} and {LEDGER} are empty")
        return Ledger(versions[LEDGER], drop_old=True)
    if present == [LEDGER]:
        return Ledger(versions[LEDGER])
    if present == [OLD_LEDGER]:
        return Ledger(versions[OLD_LEDGER], rename=bool(versions[OLD_LEDGER]), drop_old=not versions[OLD_LEDGER])
    return Ledger(set())


def _prepare_ledger(conn: sqlite3.Connection, ledger: Ledger) -> None:
    """Make the ledger exist under its current name, in one transaction. The renamed table keeps its rows and their
    times. Callers that migrate a real database have already made the backup."""
    with write_transaction(conn):
        if ledger.rename:
            conn.execute(f"ALTER TABLE {OLD_LEDGER} RENAME TO {LEDGER}")
        elif ledger.drop_old:
            conn.execute(f"DROP TABLE {OLD_LEDGER}")
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {LEDGER} ("
            "version TEXT PRIMARY KEY, "
            "applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')))"
        )


def _kept_objects(conn: sqlite3.Connection) -> set[tuple[str, str]]:
    """The indexes, views and triggers. Dropping a table silently takes its indexes and triggers with it."""
    return {(row[0], row[1]) for row in conn.execute(
        "SELECT type, name FROM sqlite_master WHERE type IN ('index', 'view', 'trigger') AND name NOT LIKE 'sqlite_%'")}


def _check_rebuild(conn: sqlite3.Connection, name: str, kept: set[tuple[str, str]]) -> None:
    """Run before a rebuild commits. Any failure here rolls the migration back."""
    if conn.execute("PRAGMA foreign_key_check").fetchall():
        raise ValidationError(f"Migration {name} left rows that break the foreign key rules, so it was rolled back.")
    if [tuple(row) for row in conn.execute("PRAGMA integrity_check")] != [("ok",)]:
        raise ValidationError(f"Migration {name} failed SQLite's integrity check, so it was rolled back.")
    lost = sorted(object_name for _, object_name in kept - _kept_objects(conn))
    if lost:
        raise ValidationError(
            f"Migration {name} lost {', '.join(lost)}: recreate every index, view and trigger it dropped. It was rolled back.")


def _apply(conn: sqlite3.Connection, file: Path) -> None:
    """Run one migration file and record it, in one transaction. A file marked as a rebuild runs with foreign keys
    off, because dropping a table with them on would delete rows in the tables that point at it. The pragma does
    nothing inside a transaction, so it is set first, and put back and verified whatever happens."""
    sql = file.read_text(encoding="utf-8")
    script = f"BEGIN;\n{sql}\nINSERT INTO {LEDGER} (version) VALUES ('{file.stem}');"
    rebuild = sql.startswith(REBUILD_MARK)
    keys = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    kept = _kept_objects(conn) if rebuild else set()
    if rebuild:
        conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.executescript(script)
        if rebuild:
            _check_rebuild(conn, file.stem, kept)
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        if rebuild:
            conn.execute(f"PRAGMA foreign_keys = {'ON' if keys else 'OFF'}")
            if conn.execute("PRAGMA foreign_keys").fetchone()[0] != keys:
                raise RuntimeError("Foreign key enforcement could not be restored after a rebuild migration.")


def migrate(conn: sqlite3.Connection, migrations_dir: Path = MIGRATIONS_DIR, only: set[str] | None = None) -> list[str]:
    """Apply any migration files not yet recorded. Returns the versions applied.

    This is the one executor: real upgrades and the scratch replay in backup._tables_for both use it. Each file runs
    in its own transaction, together with the row that records it. The ledger is brought to its current name first.
    `only` limits it to the named migrations, which is how a backup's recorded history is replayed.
    """
    if conn.in_transaction:
        raise ValidationError("Migrations cannot run inside a transaction: the caller must finish it first.")
    ledger = _inspect_ledgers(conn)
    _prepare_ledger(conn, ledger)
    applied = []
    for file in sorted(migrations_dir.glob("*.sql")):
        if file.stem in ledger.recorded or (only is not None and file.stem not in only):
            continue
        _apply(conn, file)
        applied.append(file.stem)
    return applied


def _known(migrations_dir: Path) -> set[str]:
    return {file.stem for file in migrations_dir.glob("*.sql")}


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
    known, ledger = _known(migrations_dir), _inspect_ledgers(conn)
    if not ledger.recorded:
        return "empty"
    if _newer_than_known(ledger.recorded, known):
        return "ahead"
    return "behind" if known - ledger.recorded or ledger.rename else "current"


def _backup_folder(path: Path) -> Path:
    return path.parent / "backups"


def _too_new(path: Path, conn: sqlite3.Connection, migrations_dir: Path) -> ValidationError:
    newer = ", ".join(_newer_than_known(_inspect_ledgers(conn).recorded, _known(migrations_dir)))
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

    A new database is just migrated. A database from a newer version is refused. When a migration is pending, or the
    ledger still has its old name, a checked backup of the database as it is goes to backups/ beside it first, and if
    that fails nothing is changed.
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
