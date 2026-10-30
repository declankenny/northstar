"""Account type queries. Plain functions, no web code."""

import sqlite3


def list_types(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """All account types with their class name and the number of accounts using each."""
    return conn.execute(
        "SELECT t.id, t.name, c.name AS class_name, t.stale_after_days, "
        "       (SELECT COUNT(*) FROM accounts a WHERE a.type_id = t.id) AS account_count "
        "FROM account_types t JOIN account_classes c ON c.id = t.class_id "
        "ORDER BY t.class_id, t.id"
    ).fetchall()
