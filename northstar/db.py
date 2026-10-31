"""SQLite connection and the migration runner."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


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
