"""Entering balances. Plain functions, no web code."""

import re
import sqlite3
from datetime import date

from northstar import accounts, staleness
from northstar.errors import NotFoundError, ValidationError
from northstar.money import parse_cents

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)


class EntryErrors(ValidationError):
    """One or more amounts in a batch were bad. by_account maps account id to its message."""

    def __init__(self, message: str, by_account: dict[int, str]):
        super().__init__(message)
        self.by_account = by_account


def parse_date(text: str | None, today: date) -> date:
    """A YYYY-MM-DD calendar date that is not in the future."""
    text = (text or "").strip()
    try:
        if not _ISO_DATE.fullmatch(text):
            raise ValueError
        parsed = date.fromisoformat(text)
    except ValueError:
        raise ValidationError("Enter a valid date.") from None
    if parsed > today:
        raise ValidationError("The date can't be in the future.")
    return parsed


MAX_NOTE_LENGTH = 500

# record_balance leaves an existing note alone unless it is given one, so the Update balances
# screen, which has no note field, never wipes notes.
KEEP_NOTE = object()


def clean_note(note: str | None) -> str | None:
    note = (note or "").strip()
    if len(note) > MAX_NOTE_LENGTH:
        raise ValidationError(f"The note is too long. Use {MAX_NOTE_LENGTH} characters or fewer.")
    return note or None


def _require_open(account) -> None:
    if not account["is_open"]:
        raise ValidationError(f"{account['name']} is closed. Reopen it before changing its balances.")


def record_balance(conn: sqlite3.Connection, account_id: int, as_of: date, cents: int,
                   note: str | None | object = KEEP_NOTE) -> str:
    """Save one balance. Returns 'added', 'updated' or 'unchanged'. Closed accounts are refused.

    A date that already has a balance is edited. The note is replaced only if one is given
    (a blank note clears it); leave it out to keep what is there.
    """
    _require_open(accounts.get_account(conn, account_id))
    new_note = None if note is KEEP_NOTE else clean_note(note)
    existing = conn.execute(
        "SELECT id, amount_cents, note FROM balances WHERE account_id = ? AND as_of_date = ?",
        (account_id, as_of.isoformat()),
    ).fetchone()
    if existing is None:
        conn.execute(
            "INSERT INTO balances (account_id, as_of_date, amount_cents, note) VALUES (?, ?, ?, ?)",
            (account_id, as_of.isoformat(), cents, new_note),
        )
        return "added"
    target_note = existing["note"] if note is KEEP_NOTE else new_note
    if existing["amount_cents"] == cents and existing["note"] == target_note:
        return "unchanged"
    conn.execute(
        "UPDATE balances SET amount_cents = ?, note = ?, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
        (cents, target_note, existing["id"]),
    )
    return "updated"


def add_balance(conn: sqlite3.Connection, account_id: int, date_text: str | None,
                amount_text: str | None, note: str | None, today: date) -> str:
    """The detail page's Add a balance form: typed text in, 'added', 'updated' or 'unchanged' out."""
    as_of = parse_date(date_text, today)
    cents = parse_cents(amount_text)
    return record_balance(conn, account_id, as_of, cents, note)


def add_account_with_balance(conn: sqlite3.Connection, class_slug: str | None, name: str | None,
                             type_id: int | None, notes: str | None, amount_text: str | None,
                             date_text: str | None, today: date) -> int:
    """Add an account, and its first balance when an amount is typed, all or nothing. Returns the id.

    A blank amount adds the account with no balance and the date is ignored. A typed amount with a
    blank date is as of today. Anything wrong refuses the whole thing, so no half-made account is left.
    """
    cls = accounts.get_class_by_slug(conn, class_slug)
    entry = None
    if (amount_text or "").strip():
        entry = (parse_date((date_text or "").strip() or today.isoformat(), today), parse_cents(amount_text))
    conn.execute("BEGIN")
    try:
        account_id = accounts.add_account(conn, name, cls["id"], type_id, notes)
        if entry:
            record_balance(conn, account_id, entry[0], entry[1])
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
    return account_id


def get_balance(conn: sqlite3.Connection, balance_id: int) -> dict:
    """One balance with its account's name and open state."""
    row = conn.execute(
        "SELECT b.id, b.account_id, b.as_of_date, b.amount_cents, b.note, b.source, "
        "       a.name AS account_name, a.is_open "
        "FROM balances b JOIN accounts a ON a.id = b.account_id WHERE b.id = ?",
        (balance_id,),
    ).fetchone()
    if row is None:
        raise NotFoundError("That balance no longer exists.")
    return dict(row)


def update_balance(conn: sqlite3.Connection, balance_id: int, date_text: str | None,
                   amount_text: str | None, note: str | None, today: date) -> str:
    """Change a balance's date, amount and note. Returns 'updated' or 'unchanged'."""
    balance = get_balance(conn, balance_id)
    _require_open({"name": balance["account_name"], "is_open": balance["is_open"]})
    as_of = parse_date(date_text, today)
    cents = parse_cents(amount_text)
    new_note = clean_note(note)
    if conn.execute(
        "SELECT 1 FROM balances WHERE account_id = ? AND as_of_date = ? AND id != ?",
        (balance["account_id"], as_of.isoformat(), balance_id),
    ).fetchone():
        raise ValidationError(
            f"There is already a balance on {as_of.isoformat()}. Edit that one instead.")
    if (balance["as_of_date"], balance["amount_cents"], balance["note"]) == (
            as_of.isoformat(), cents, new_note):
        return "unchanged"
    conn.execute(
        "UPDATE balances SET as_of_date = ?, amount_cents = ?, note = ?, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
        (as_of.isoformat(), cents, new_note, balance_id),
    )
    return "updated"


def delete_balance(conn: sqlite3.Connection, balance_id: int) -> None:
    balance = get_balance(conn, balance_id)
    _require_open({"name": balance["account_name"], "is_open": balance["is_open"]})
    conn.execute("DELETE FROM balances WHERE id = ?", (balance_id,))


def update_rows(conn: sqlite3.Connection, as_of: date, today: date) -> list[dict]:
    """Every open account with what the Update screen shows: its latest balance, how old that
    is, whether that is stale for its type, and any balance already saved on the chosen date."""
    rows = conn.execute(
        "SELECT a.id, a.name, c.name AS class_name, t.name AS type_name, t.stale_after_days, "
        "  (SELECT b.as_of_date FROM balances b WHERE b.account_id = a.id "
        "     ORDER BY b.as_of_date DESC LIMIT 1) AS last_date, "
        "  (SELECT b.amount_cents FROM balances b WHERE b.account_id = a.id "
        "     ORDER BY b.as_of_date DESC LIMIT 1) AS last_cents, "
        "  (SELECT b.amount_cents FROM balances b WHERE b.account_id = a.id "
        "     AND b.as_of_date = ?) AS existing_cents "
        "FROM accounts a "
        "JOIN account_classes c ON c.id = a.class_id "
        "JOIN account_types t ON t.id = a.type_id "
        "WHERE a.is_open = 1 "
        "ORDER BY a.class_id, t.name COLLATE NOCASE, a.name COLLATE NOCASE",
        (as_of.isoformat(),),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["days_since"] = staleness.days_since(row["last_date"], today)
        item["stale"] = staleness.is_stale(row["last_date"], today, row["stale_after_days"])
        result.append(item)
    return result


def save_update(conn: sqlite3.Connection, date_text: str | None,
                amounts: dict[int, str | None], today: date) -> dict[str, int]:
    """Save one date's amounts for the open accounts, all or nothing.

    Blank amounts are skipped. If any amount is bad, nothing is saved and EntryErrors says which.
    Returns how many balances were added, updated and left unchanged.
    """
    as_of = parse_date(date_text, today)
    open_ids = [r["id"] for r in update_rows(conn, as_of, today)]
    entered: dict[int, int] = {}
    errors: dict[int, str] = {}
    for account_id in open_ids:
        text = (amounts.get(account_id) or "").strip()
        if not text:
            continue
        try:
            entered[account_id] = parse_cents(text)
        except ValidationError as err:
            errors[account_id] = str(err)
    if errors:
        raise EntryErrors("Some amounts need fixing. Nothing was saved.", errors)

    counts = {"added": 0, "updated": 0, "unchanged": 0}
    conn.execute("BEGIN")
    try:
        for account_id, cents in entered.items():
            counts[record_balance(conn, account_id, as_of, cents)] += 1
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
    return counts
