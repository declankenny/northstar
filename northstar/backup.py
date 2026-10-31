"""Backup and restore of the SQLite database. Plain functions plus a small command line.

    python -m northstar.backup create BACKUP_FILE
    python -m northstar.backup restore BACKUP_FILE [--replace]

A backup uses SQLite's online backup, so it is safe while the app is running. Never copy the
database file by hand while the app runs. A restore needs the app stopped.

A backup file is a complete copy of the real financial data. Keep it somewhere private, never in
the repository, and never print what is inside it. This tool reports only counts.
"""

import argparse
import os
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from northstar import config
from northstar.errors import ValidationError

# Every table of the initial schema. A file without the sign-in tables cannot run the app, and the
# migrations would apply nothing to it, because the initial migration is already recorded.
REQUIRED_TABLES = {"account_classes", "account_types", "accounts", "balances", "schema_migrations", "users", "sessions"}
SIDECAR_SUFFIXES = ("-journal", "-wal", "-shm")   # files SQLite keeps beside the database


def _uri(path: Path, mode: str) -> str:
    return f"{path.resolve().as_uri()}?mode={mode}"


def check_database(path: str | Path) -> dict:
    """Open a file read-only and make sure it is a healthy Northstar database.

    Returns counts only: accounts, balances and applied migrations.
    """
    path = Path(path)
    if not path.is_file():
        raise ValidationError(f"There is no file at {path}.")
    not_valid = ValidationError(f"{path} is not a valid Northstar database.")
    try:
        conn = sqlite3.connect(_uri(path, "ro"), uri=True)
    except sqlite3.Error:
        raise not_valid from None
    try:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if not REQUIRED_TABLES <= tables:
            raise not_valid
        if conn.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValidationError(f"{path} failed SQLite's integrity check.")
        if conn.execute("PRAGMA foreign_key_check").fetchall():
            raise ValidationError(f"{path} has rows that break the foreign-key rules.")
        return {
            "accounts": conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0],
            "balances": conn.execute("SELECT COUNT(*) FROM balances").fetchone()[0],
            "migrations": conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0],
        }
    except sqlite3.Error:
        raise not_valid from None
    finally:
        conn.close()


def _copy_to_temp(source: Path, folder: Path, name: str) -> Path:
    """Copy a database with SQLite's online backup into a new temporary file in folder.

    The temporary file is checked before it is returned. If anything goes wrong it is removed.
    """
    descriptor, temp_name = tempfile.mkstemp(prefix=f"{name}.", suffix=".partial", dir=folder)
    os.close(descriptor)
    temp = Path(temp_name)
    try:
        source_conn = sqlite3.connect(source)
        target_conn = sqlite3.connect(temp)
        try:
            source_conn.backup(target_conn)
        finally:
            target_conn.close()
            source_conn.close()
        check_database(temp)
        return temp
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


def create_backup(db_path: str | Path, backup_path: str | Path) -> dict:
    """Write a checked copy of the database to backup_path, which must not exist yet."""
    db_path, backup_path = Path(db_path), Path(backup_path)
    if not db_path.is_file():
        raise ValidationError(f"There is no database at {db_path}.")   # connect() would create one
    if backup_path.exists():
        raise ValidationError(f"{backup_path} already exists. Choose a new file name.")
    if not backup_path.parent.is_dir():
        raise ValidationError(f"The folder {backup_path.parent} does not exist.")
    temp = _copy_to_temp(db_path, backup_path.parent, backup_path.name)
    try:
        os.replace(temp, backup_path)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    return check_database(backup_path)


def _sidecars(db_path: Path) -> list[Path]:
    return [p for p in (db_path.with_name(db_path.name + s) for s in SIDECAR_SUFFIXES) if p.exists()]


def restore_backup(backup_path: str | Path, db_path: str | Path, replace: bool = False) -> dict:
    """Put a backup in place as the database. The app must be stopped.

    The backup is checked first. An existing database is refused unless replace is set, and then
    it is moved aside, never deleted. Leftover journal files beside it are moved aside too, so
    SQLite can't apply an old journal to the restored file.
    """
    backup_path, db_path = Path(backup_path), Path(db_path)
    check_database(backup_path)
    if backup_path.resolve() == db_path.resolve():
        raise ValidationError("The backup and the database are the same file.")
    if db_path.exists() and not replace:
        raise ValidationError(
            f"{db_path} already exists. Stop the app and use --replace to move it aside and restore.")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    temp = _copy_to_temp(backup_path, db_path.parent, db_path.name)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    moved: list[tuple[Path, Path]] = []
    try:
        for old in ([db_path] if db_path.exists() else []) + _sidecars(db_path):
            aside = old.with_name(f"{old.name}.before-restore-{stamp}")
            os.replace(old, aside)
            moved.append((old, aside))
        os.replace(temp, db_path)
    except PermissionError:
        for old, aside in reversed(moved):          # put everything back as it was
            os.replace(aside, old)
        temp.unlink(missing_ok=True)
        raise ValidationError("The database is in use. Stop the app, then try again.") from None
    except BaseException:
        for old, aside in reversed(moved):
            os.replace(aside, old)
        temp.unlink(missing_ok=True)
        raise
    result = check_database(db_path)
    result["moved_aside"] = [str(aside) for _, aside in moved]
    return result


def _describe(counts: dict) -> str:
    return f"{counts['accounts']} accounts, {counts['balances']} balances, integrity ok"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m northstar.backup",
        description="Back up or restore the Northstar database (NORTHSTAR_DB, default data/northstar.db).")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="write a backup of the database to a new file")
    create.add_argument("backup_file")
    restore = commands.add_parser("restore", help="restore the database from a backup file (app stopped)")
    restore.add_argument("backup_file")
    restore.add_argument("--replace", action="store_true",
                         help="move an existing database aside and restore over it")
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            counts = create_backup(config.database_path(), args.backup_file)
            print(f"Backup written to {args.backup_file} ({_describe(counts)}).")
        else:
            result = restore_backup(args.backup_file, config.database_path(), replace=args.replace)
            print(f"Restored {config.database_path()} from {args.backup_file} ({_describe(result)}).")
            for aside in result["moved_aside"]:
                print(f"The previous file was moved to {aside}.")
    except ValidationError as err:
        print(f"Error: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
