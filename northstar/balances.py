"""Entering balances. Plain functions, no web code."""

import json
import re
import sqlite3
from datetime import date

from northstar import accounts, currencies, db, locales, staleness, writer
from northstar.errors import NotFoundError, ValidationError
from northstar.money import parse_amount
from northstar.writer import Operation

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)


class EntryErrors(ValidationError):
    """One or more amounts in a batch were bad. by_account maps account id to its message."""

    def __init__(self, message: str, by_account: dict[int, str]):
        super().__init__(message)
        self.by_account = by_account

    @property
    def details(self) -> dict:
        return {"errors": self.by_account}


def parse_for(currency: currencies.Currency, text: str | None, locale: locales.Locale | None = None) -> int:
    """Typed text as a count of the currency's minor units, read in the person's locale (US English when none is given). A
    leading '$' is accepted only for US dollars."""
    return parse_amount(text, currency.minor_units, locale, dollar_sign=currency.code == "USD")


# What a caller loaded a balance as: the `version` it carried (the id of the operation that last wrote it), or None for a date
# that had no balance. A caller with nothing loaded (a script, a test) passes UNCHECKED; the web routes always say.
UNCHECKED = object()


class ConflictingEdit(ValidationError):
    """A balance is no longer what the person saw when they opened it, so nothing was saved. `conflicts` says, for each: its
    kind (`changed`, `deleted`, or `added` for a date that had no balance), the account and date, the balance as it is now
    (None for the amount when it is gone), and who changed it and on what UTC date."""

    def __init__(self, conflicts: list[dict]):
        many = len(conflicts) > 1
        super().__init__(f"{locales.speaking().integer(len(conflicts))} balances changed since you opened this date. Nothing was saved." if many
                         else "That balance changed since you opened it. Nothing was saved.")
        self.conflicts = conflicts

    @property
    def details(self) -> dict:
        return {"reason": "conflict", "conflicts": self.conflicts}


def _who(conn: sqlite3.Connection, operation_id: int | None) -> tuple[str | None, str | None]:
    """The name of the user who made an operation and its UTC date. A deleted user still has a name."""
    row = conn.execute("SELECT o.created_at, u.display_name FROM sys_operations o JOIN users u ON u.id = o.user_id "
                       "WHERE o.id = ?", (operation_id,)).fetchone()
    return (None, None) if row is None else (row["display_name"], row["created_at"][:10])


def _conflict(conn: sqlite3.Connection, kind: str, account_id: int, row) -> dict:
    """A conflict over a balance that exists (`row` is its live row) or, for `deleted`, one that is gone (`row` is its log entry)."""
    if kind == "deleted":
        old = json.loads(row["old_json"])
        by, on = _who(conn, row["operation_id"])
        found = {"balance_id": row["record_id"], "date": old.get("as_of_date"), "amount_cents": None, "note": None, "version": None}
    else:
        by, on = _who(conn, row["version"])
        found = {"balance_id": row["id"], "date": row["as_of_date"], "amount_cents": row["amount_cents"], "note": row["note"],
                 "version": row["version"]}
    return {"kind": kind, "account_id": account_id, "account_name": accounts.get_account(conn, account_id)["name"],
            "currency": currencies.as_dict(currencies.account_currency(conn, account_id)), "by": by, "on": on, **found}


def _deleted(conn: sqlite3.Connection, where: str, args: tuple):
    return conn.execute("SELECT operation_id, record_id, old_json FROM sys_record_changes WHERE tablename = 'balances' "
                        f"AND change = 'DELETE' AND {where} ORDER BY id DESC LIMIT 1", args).fetchone()


def require_version(conn: sqlite3.Connection, balance_id: int, expected: int | None) -> None:
    """Refuse, with ConflictingEdit, unless the balance is still at the version the caller loaded. A balance that never
    existed is left for the caller's own NotFoundError."""
    row = conn.execute("SELECT id, account_id, as_of_date, amount_cents, note, version FROM live_balances WHERE id = ?",
                       (balance_id,)).fetchone()
    if row is None:
        gone = _deleted(conn, "record_id = ?", (balance_id,))
        if gone is not None:
            raise ConflictingEdit([_conflict(conn, "deleted", json.loads(gone["old_json"])["account_id"], gone)])
        return
    if row["version"] != expected:
        raise ConflictingEdit([_conflict(conn, "changed", row["account_id"], row)])


def require_versions(conn: sqlite3.Connection, as_of: date, expected: dict[int, int | None]) -> None:
    """The same for one date across accounts, where an account whose date had no balance expects None. Names every conflict."""
    conflicts = []
    for account_id, want in expected.items():
        row = conn.execute("SELECT id, as_of_date, amount_cents, note, version FROM live_balances "
                           "WHERE account_id = ? AND as_of_date = ?", (account_id, as_of.isoformat())).fetchone()
        if row is None:
            if want is not None:
                gone = _deleted(conn, "json_extract(old_json, '$.account_id') = ? AND json_extract(old_json, '$.as_of_date') = ?",
                                (account_id, as_of.isoformat()))
                conflicts.append(_conflict(conn, "deleted", account_id, gone) if gone is not None else {
                    "kind": "deleted", "account_id": account_id, "account_name": accounts.get_account(conn, account_id)["name"],
                    "balance_id": None, "date": as_of.isoformat(), "amount_cents": None, "note": None, "version": None,
                    "by": None, "on": None})
        elif want is None:
            conflicts.append(_conflict(conn, "added", account_id, row))
        elif row["version"] != want:
            conflicts.append(_conflict(conn, "changed", account_id, row))
    if conflicts:
        raise ConflictingEdit(conflicts)


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


def require_open(account) -> None:
    if not account["is_open"]:
        raise ValidationError(f"{account['name']} is closed. Reopen it before changing its balances.")


def record_balance(op: Operation, account_id: int, as_of: date, cents: int,
                   note: str | None | object = KEEP_NOTE) -> str:
    """Save one balance. Returns 'added', 'updated' or 'unchanged'. Closed accounts are refused.

    A date that already has a balance is edited. The note is replaced only if one is given
    (a blank note clears it); leave it out to keep what is there.
    """
    conn = op.conn
    new_note = None if note is KEEP_NOTE else clean_note(note)
    with db.write_transaction(conn):       # the open check and the write are one step (see db.write_transaction)
        require_open(accounts.get_account(conn, account_id))
        existing = conn.execute(
            "SELECT id, amount_cents, note FROM live_balances WHERE account_id = ? AND as_of_date = ?",
            (account_id, as_of.isoformat()),
        ).fetchone()
        if existing is None:
            writer.insert(op, "balances", {
                "account_id": account_id, "as_of_date": as_of.isoformat(), "amount_cents": cents, "note": new_note})
            return "added"
        target_note = existing["note"] if note is KEEP_NOTE else new_note
        if existing["amount_cents"] == cents and existing["note"] == target_note:
            return "unchanged"
        writer.update(op, "balances", existing["id"], {"amount_cents": cents, "note": target_note})
        return "updated"


def add_balance(op: Operation, account_id: int, date_text: str | None,
                amount_text: str | None, note: str | None, today: date, locale_tag: str | None = None) -> str:
    """The detail page's Add a balance form: typed text in, 'added', 'updated' or 'unchanged' out. A form says which locale it
    was using in `locale_tag`, and is refused with LocaleChanged, writing nothing, if the person's saved one is now another."""
    as_of = parse_date(date_text, today)
    cents = parse_for(currencies.account_currency(op.conn, account_id), amount_text,
                      locales.reading_locale(op.conn, op.actor_id, locale_tag))
    with db.write_transaction(op.conn):
        locales.require_current(op.conn, op.actor_id, locale_tag)
        return record_balance(op, account_id, as_of, cents, note)


def add_account_with_balance(op: Operation, class_slug: str | None, name: str | None,
                             type_id: int | None, notes: str | None, amount_text: str | None,
                             date_text: str | None, today: date, locale_tag: str | None = None,
                             currency_code: str | None = None) -> int:
    """Add an account, and its first balance when an amount is typed, all or nothing. Returns the id. The account is in the
    currency with `currency_code`, which must be usable (see accounts.add_account), or in the system currency when none is given.

    A blank amount adds the account with no balance and the date is ignored. A typed amount with a
    blank date is as of today. Anything wrong refuses the whole thing, so no half-made account is left. A form says which
    locale it was using in `locale_tag`: with an amount typed, it is refused with LocaleChanged if the saved one is now another.
    """
    conn = op.conn
    cls = accounts.get_class_by_slug(conn, class_slug)
    currency = currencies.require_system_currency(conn)        # refused before anything is read from the form
    if currency_code is not None and currency_code != currency.code:
        currency = currencies.by_code(conn, currency_code)
        if currency is None:
            raise ValidationError("Choose a currency from the list.")
    entry = None
    typed = bool((amount_text or "").strip())
    if typed:
        entry = (parse_date((date_text or "").strip() or today.isoformat(), today),
                 parse_for(currency, amount_text, locales.reading_locale(conn, op.actor_id, locale_tag)))
    with db.write_transaction(conn):
        if typed:
            locales.require_current(conn, op.actor_id, locale_tag)
        account_id = accounts.add_account(op, name, cls["id"], type_id, notes, currency.id)
        if entry:
            record_balance(op, account_id, entry[0], entry[1])
    return account_id


def get_balance(conn: sqlite3.Connection, balance_id: int) -> dict:
    """One balance with its account's name and open state."""
    row = conn.execute(
        "SELECT b.id, b.account_id, b.as_of_date, b.amount_cents, b.note, b.source, "
        "       a.name AS account_name, a.is_open "
        "FROM live_balances b JOIN live_accounts a ON a.id = b.account_id WHERE b.id = ?",
        (balance_id,),
    ).fetchone()
    if row is None:
        raise NotFoundError("That balance no longer exists.")
    return dict(row)


def balance_details(conn: sqlite3.Connection, balance_id: int, currency_code: str) -> dict:
    """What a balance's own page shows beside the balance: its value in the system currency with the date of the rate it used, and
    who entered it and who last changed it, with the dates (the UTC date of the time written). `currency_code` is the account's.
    `reporting` is None when there is nothing to show: no system currency yet, or the account is in it. Its `value` is None, with no
    `rate_date`, when the currency has no rate on or before the balance's date. The value is the view's own (live_balance_values), so
    it is the same figure the list shows; only the date of the rate is looked up here, by the rule the view uses."""
    row = conn.execute(
        "SELECT v.reporting_value, v.reporting_scale, v.reporting_unit, v.created_at, v.updated_at, "
        "       cu.display_name AS entered_by, uu.display_name AS changed_by, "
        "       (SELECT r.rate_date FROM exchange_rates r WHERE r.currency_id = (SELECT currency_id FROM live_accounts WHERE id = v.account_id) "
        "          AND r.rate_date <= v.as_of_date ORDER BY r.rate_date DESC LIMIT 1) AS rate_date "
        "FROM live_balance_values v JOIN users cu ON cu.id = v.created_by JOIN users uu ON uu.id = v.updated_by WHERE v.id = ?",
        (balance_id,),
    ).fetchone()
    if row is None:
        raise NotFoundError("That balance no longer exists.")
    reporting = None
    if row["reporting_unit"] is not None and row["reporting_unit"] != currency_code:
        reporting = {"value": row["reporting_value"], "scale": row["reporting_scale"], "unit": row["reporting_unit"],
                     "rate_date": row["rate_date"] if row["reporting_value"] is not None else None}
    return {"reporting": reporting, "entered_by": row["entered_by"], "entered_on": row["created_at"][:10],
            "changed_by": row["changed_by"], "changed_on": row["updated_at"][:10]}


def _balance_currency(conn: sqlite3.Connection, balance_id: int) -> currencies.Currency:
    """The currency of the balance's account. A balance that is gone is read as dollars, so the amount is still checked
    and the caller's own check (a version, or the balance no longer existing) is what refuses it."""
    row = conn.execute(
        "SELECT c.id, c.code, c.name, c.minor_units FROM live_balances b JOIN live_accounts a ON a.id = b.account_id "
        "JOIN currencies c ON c.id = a.currency_id WHERE b.id = ?", (balance_id,)).fetchone()
    return currencies.Currency(row["id"], row["code"], row["name"], row["minor_units"]) if row         else currencies.Currency(0, "USD", "US Dollar", 2)


def update_balance(op: Operation, balance_id: int, date_text: str | None,
                   amount_text: str | None, note: str | None, today: date, expected_version=UNCHECKED,
                   locale_tag: str | None = None) -> str:
    """Change a balance's date, amount and note. Returns 'updated' or 'unchanged'. Given the version the caller loaded, it
    refuses with ConflictingEdit, before anything else, if the balance has been written since (or deleted). A form says which
    locale it was using in `locale_tag`, and is refused with LocaleChanged, writing nothing, if the saved one is now another."""
    conn = op.conn
    as_of = parse_date(date_text, today)
    cents = parse_for(_balance_currency(conn, balance_id), amount_text, locales.reading_locale(conn, op.actor_id, locale_tag))
    new_note = clean_note(note)
    with db.write_transaction(conn):
        locales.require_current(conn, op.actor_id, locale_tag)
        if expected_version is not UNCHECKED:
            require_version(conn, balance_id, expected_version)
        balance = get_balance(conn, balance_id)
        require_open({"name": balance["account_name"], "is_open": balance["is_open"]})
        if conn.execute(
            "SELECT 1 FROM live_balances WHERE account_id = ? AND as_of_date = ? AND id != ?",
            (balance["account_id"], as_of.isoformat(), balance_id),
        ).fetchone():
            raise ValidationError(
                f"There is already a balance on {locales.speaking().date(as_of)}. Edit that one instead.")
        if (balance["as_of_date"], balance["amount_cents"], balance["note"]) == (
                as_of.isoformat(), cents, new_note):
            return "unchanged"
        writer.update(op, "balances", balance_id, {
            "as_of_date": as_of.isoformat(), "amount_cents": cents, "note": new_note})
        return "updated"


def delete_balance(op: Operation, balance_id: int, expected_version=UNCHECKED) -> int:
    """Delete a balance and return its account's id. Given the version the caller loaded, it refuses with ConflictingEdit if
    the balance has changed since."""
    conn = op.conn
    with db.write_transaction(conn):
        if expected_version is not UNCHECKED:
            require_version(conn, balance_id, expected_version)
        balance = get_balance(conn, balance_id)
        require_open({"name": balance["account_name"], "is_open": balance["is_open"]})
        writer.delete(op, "balances", balance_id)
        return balance["account_id"]


def update_rows(conn: sqlite3.Connection, as_of: date, today: date) -> list[dict]:
    """Every open account with what the Update screen shows: its latest balance, how old that
    is, whether that is stale for its type, and any balance already saved on the chosen date."""
    rows = conn.execute(
        "SELECT a.id, a.name, c.name AS class_name, t.name AS type_name, t.stale_after_days, "
        "  cu.code AS currency_code, cu.name AS currency_name, cu.minor_units AS currency_minor_units, "
        "  (SELECT b.as_of_date FROM live_balances b WHERE b.account_id = a.id "
        "     ORDER BY b.as_of_date DESC LIMIT 1) AS last_date, "
        "  (SELECT b.amount_cents FROM live_balances b WHERE b.account_id = a.id "
        "     ORDER BY b.as_of_date DESC LIMIT 1) AS last_cents, "
        "  (SELECT b.amount_cents FROM live_balances b WHERE b.account_id = a.id "
        "     AND b.as_of_date = ?) AS existing_cents, "
        "  (SELECT b.version FROM live_balances b WHERE b.account_id = a.id "
        "     AND b.as_of_date = ?) AS existing_version "
        "FROM live_accounts a "
        "JOIN account_types t ON t.id = a.type_id "
        "JOIN account_classes c ON c.id = t.class_id "
        "JOIN currencies cu ON cu.id = a.currency_id "
        "WHERE a.is_open = 1 "
        "ORDER BY t.class_id, t.name COLLATE NOCASE, a.name COLLATE NOCASE",
        (as_of.isoformat(), as_of.isoformat()),
    ).fetchall()
    result = []
    for row in rows:
        item = accounts.with_currency(dict(row))
        item["days_since"] = staleness.days_since(row["last_date"], today)
        item["stale"] = staleness.is_stale(row["last_date"], today, row["stale_after_days"])
        result.append(item)
    return result


def save_update(op: Operation, date_text: str | None,
                amounts: dict[int, str | None], today: date, expected_versions=UNCHECKED,
                locale_tag: str | None = None) -> dict[str, int]:
    """Save one date's amounts for the open accounts, all or nothing.

    Blank amounts are skipped. If any amount is bad, nothing is saved and EntryErrors says which. Given the version of the
    balance each account had on the date when the caller loaded it (None for none), it refuses with ConflictingEdit, naming
    every account whose balance has since changed, been deleted or been added. Returns how many balances were added,
    updated and left unchanged. A form says which locale it was using in `locale_tag`: with an amount typed, it is refused
    with LocaleChanged, writing nothing, if the saved one is now another.
    """
    conn = op.conn
    as_of = parse_date(date_text, today)
    open_ids = [r["id"] for r in update_rows(conn, as_of, today)]
    typed = any((amounts.get(account_id) or "").strip() for account_id in open_ids)
    locale = locales.reading_locale(conn, op.actor_id, locale_tag) if typed else locales.for_user(conn, op.actor_id)
    entered: dict[int, int] = {}
    errors: dict[int, str] = {}
    for account_id in open_ids:
        text = (amounts.get(account_id) or "").strip()
        if not text:
            continue
        try:
            entered[account_id] = parse_for(currencies.account_currency(conn, account_id), text, locale)
        except ValidationError as err:
            errors[account_id] = str(err)
    if errors:
        raise EntryErrors("Some amounts need fixing. Nothing was saved.", errors)

    counts = {"added": 0, "updated": 0, "unchanged": 0}
    with db.write_transaction(conn):
        if typed:
            locales.require_current(conn, op.actor_id, locale_tag)
        if expected_versions is not UNCHECKED:
            require_versions(conn, as_of, {account_id: expected_versions.get(account_id) for account_id in entered})
        for account_id, cents in entered.items():
            counts[record_balance(op, account_id, as_of, cents)] += 1
    return counts
