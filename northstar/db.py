"""SQLite connection and the migration runner."""

import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def prepare(path: str | Path) -> None:
    """Create the database's folder if it is missing. SQLite creates the file but not the folder, and the
    default data/ folder is not in a fresh checkout. Starting the app and the command line tools both
    call this before opening the database."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)


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
