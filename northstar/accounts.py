"""Account rules. Plain functions, no web code."""

import ipaddress
import sqlite3
import unicodedata
from datetime import date
from urllib.parse import urlsplit

from northstar import currencies, db, rates, staleness, writer
from northstar.errors import NotFoundError, ValidationError
from northstar.writer import Operation

_SELECT = (
    "SELECT a.id, a.name, t.class_id, c.name AS class_name, a.type_id, t.name AS type_name, "
    "       a.is_open, a.notes, a.website, "
    "       (SELECT COUNT(*) FROM live_balances b WHERE b.account_id = a.id) AS balance_count "
    "FROM live_accounts a "
    "JOIN account_types t ON t.id = a.type_id "
    "JOIN account_classes c ON c.id = t.class_id "
)


def with_currency(item: dict) -> dict:
    """The row's currency columns as one `currency` entry, the way the API shows an account's currency."""
    item["currency"] = {"code": item.pop("currency_code"), "name": item.pop("currency_name"),
                        "minor_units": item.pop("currency_minor_units")}
    return item


def get_account(conn: sqlite3.Connection, account_id: int) -> sqlite3.Row:
    row = conn.execute(_SELECT + "WHERE a.id = ?", (account_id,)).fetchone()
    if row is None:
        raise NotFoundError("That account no longer exists.")
    return row


def account_summary(conn: sqlite3.Connection, account_id: int, today: date) -> dict:
    """The account plus what its page shows: balance count, earliest date, latest balance,
    its age in days and whether that is stale for the account's type."""
    summary = dict(get_account(conn, account_id))
    summary["currency"] = currencies.as_dict(currencies.account_currency(conn, account_id))
    summary["stale_after_days"] = conn.execute(
        "SELECT stale_after_days FROM account_types WHERE id = ?", (summary["type_id"],)
    ).fetchone()[0]
    summary["earliest_date"] = conn.execute(
        "SELECT MIN(as_of_date) FROM live_balances WHERE account_id = ?", (account_id,)
    ).fetchone()[0]
    latest = conn.execute(
        "SELECT as_of_date, amount_cents FROM last_balances WHERE account_id = ?",
        (account_id,),
    ).fetchone()
    summary["last_date"] = latest["as_of_date"] if latest else None
    summary["last_cents"] = latest["amount_cents"] if latest else None
    summary["days_since"] = staleness.days_since(summary["last_date"], today)
    # Closed accounts are never flagged: their last balance is meant to be old.
    summary["stale"] = bool(summary["is_open"]) and staleness.is_stale(
        summary["last_date"], today, summary["stale_after_days"])
    return summary


def classes_with_types(conn: sqlite3.Connection) -> list[dict]:
    """Both classes with the types each offers, for the Add account dialog."""
    classes = conn.execute("SELECT id, name FROM account_classes ORDER BY id").fetchall()
    return [{"id": c["id"], "name": c["name"], "types": [dict(t) for t in types_for_class(conn, c["id"])]}
            for c in classes]


def account_page(conn: sqlite3.Connection, account_id: int, today: date) -> dict:
    """Everything the account page shows: the summary, and the types to offer in its Edit and Change class dialogs (its own
    class's, and the other class's). Its balances are a list of their own."""
    page = account_summary(conn, account_id, today)
    page["types"] = [dict(row) for row in types_for_class(conn, page["class_id"])]
    other = other_class(conn, page["class_id"])
    page["other_class"] = {"id": other["id"], "name": other["name"],
                           "types": [dict(row) for row in types_for_class(conn, other["id"])]}
    return page


def get_class_by_slug(conn: sqlite3.Connection, slug: str | None) -> sqlite3.Row:
    """Look a class up by its lowercase name, such as 'asset' or 'liability'."""
    row = conn.execute(
        "SELECT id, name FROM account_classes WHERE lower(name) = ?", ((slug or "").lower(),)
    ).fetchone()
    if row is None:
        raise ValidationError("Choose Asset or Liability.")
    return row


def other_class(conn: sqlite3.Connection, class_id: int) -> sqlite3.Row:
    return conn.execute(
        "SELECT id, name FROM account_classes WHERE id != ?", (class_id,)
    ).fetchone()


def types_for_class(conn: sqlite3.Connection, class_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, name FROM account_types WHERE class_id = ? ORDER BY id", (class_id,)
    ).fetchall()


def _clean_name(name: str | None) -> str:
    name = (name or "").strip()
    if not name:
        raise ValidationError("Name is required.")
    return name


def _clean_notes(notes: str | None) -> str | None:
    return (notes or "").strip() or None


WEBSITE_MAX = 2048
WEBSITE_REFUSED = "Enter a full web address starting with http:// or https://, such as https://www.bank.example/."
# What cleaning can remove from an address, as the names the page turns into words.
LOGIN, QUERY, FRAGMENT = "login", "query", "fragment"


# The characters a browser's URL parser refuses in a host (the WHATWG "forbidden domain code points", less the controls and
# whitespace already refused), "%" included, so an encoded "/" or "?" cannot hide in one.
_HOST_FORBIDDEN = set('#/:<>?@[\\]^|%')


def _host_is_valid(hostport: str, host: str) -> bool:
    """urlsplit does not validate the host. A bracketed host must be an IPv6 address; any other must have none of the characters a
    browser refuses, so a saved address is one the link can open."""
    if hostport.startswith("["):
        if "%" in host:
            return False
        try:
            ipaddress.IPv6Address(host)
        except ValueError:
            return False
        return True
    return not any(ch in _HOST_FORBIDDEN for ch in host) and _numeric_host_is_valid(host)


def _ipv4_number(part: str) -> int | None:
    """One part of a numeric host as a browser reads it: decimal, 0x hex or leading-0 octal. None when it is not a number."""
    if not part:
        return None
    radix = 10
    if part[:2].lower() == "0x":
        part, radix = part[2:], 16
    elif len(part) > 1 and part[0] == "0":
        part, radix = part[1:], 8
    if not part:
        return 0
    try:
        return int(part, radix) if part.isascii() and part.isalnum() else None
    except ValueError:
        return None


def _numeric_host_is_valid(host: str) -> bool:
    """A browser reads a host whose last label is a number as an IPv4 address (so 999.999.999.999 and 1.2.3.4.5 are refused, and 1.2.3
    means 1.2.0.3), and refuses it when it is not one. Any other host is not checked further (WHATWG URL, "ends in a number")."""
    labels = host.split(".")
    if labels[-1] == "" and len(labels) > 1:
        labels.pop()
    last = labels[-1]
    if not (last.isascii() and last.isdigit()) and not (last[:2].lower() == "0x" and _ipv4_number(last) is not None):
        return True
    if len(labels) > 4:
        return False
    numbers = [_ipv4_number(label) for label in labels]
    if any(n is None for n in numbers):
        return False
    return all(n <= 255 for n in numbers[:-1]) and numbers[-1] < 256 ** (5 - len(numbers))


def clean_website(text: str | None) -> tuple[str | None, list[str]]:
    """An account's website as it is stored, and what was removed to get it (a list of LOGIN, QUERY and FRAGMENT, empty when the address
    was kept whole). The one rule for the form and the API (#266), in this order:

    1. surrounding whitespace is trimmed, and nothing left clears the website (None);
    2. more than WEBSITE_MAX characters is refused, before anything is parsed, so the work is bounded;
    3. it must be a well-formed http or https address with a host, with no whitespace, control character or backslash in it;
    4. any user name and password, the query string and the fragment are removed (a sign-in or session address often carries a token
       there), and the scheme and host are written in lower case. Cleaning only shortens an address, so it still fits.

    Only the cleaned address ever reaches the writer, so the change log never holds what was removed. A token in the path cannot be told
    from a path, so this reduces the risk and does not remove it."""
    text = (text or "").strip()
    if not text:
        return None, []
    if len(text) > WEBSITE_MAX:
        raise ValidationError(f"The website can be at most {WEBSITE_MAX} characters.")
    if any(ch.isspace() or unicodedata.category(ch) == "Cc" or ch == "\\" for ch in text):   # controls include DEL and the C1 range
        raise ValidationError(WEBSITE_REFUSED)
    try:
        parts = urlsplit(text)
        host = parts.hostname
        parts.port                    # a port that is not a number is a ValueError
    except ValueError:
        raise ValidationError(WEBSITE_REFUSED) from None
    if parts.scheme.lower() not in ("http", "https") or not host or not text[len(parts.scheme):].startswith("://"):
        raise ValidationError(WEBSITE_REFUSED)
    if not _host_is_valid(parts.netloc.rsplit("@", 1)[-1], host):
        raise ValidationError(WEBSITE_REFUSED)
    removed = []
    if "@" in parts.netloc:
        removed.append(LOGIN)
    if parts.query:
        removed.append(QUERY)
    if parts.fragment:
        removed.append(FRAGMENT)
    netloc = parts.netloc.rsplit("@", 1)[-1].lower()
    return f"{parts.scheme.lower()}://{netloc}{parts.path}", removed


def _check_type(conn: sqlite3.Connection, type_id: int | None, class_id: int) -> int:
    """The type must exist and belong to the class."""
    if type_id is None or not conn.execute(
        "SELECT 1 FROM account_types WHERE id = ? AND class_id = ?", (type_id, class_id)
    ).fetchone():
        raise ValidationError("Choose a type from the list.")
    return type_id


def _check_name_free(conn: sqlite3.Connection, name: str, own_id: int | None = None) -> None:
    """Names are unique among all accounts, open or closed, ignoring ASCII case (SQLite NOCASE, the same comparison as
    the unique index, which enforces it even if this is bypassed). `name` is already trimmed. A closed account keeps its
    name, so the message says when that is who holds it."""
    holder = conn.execute(
        "SELECT name, is_open FROM live_accounts WHERE name = ? COLLATE NOCASE AND id IS NOT ?", (name, own_id)).fetchone()
    if holder is None:
        return
    if holder["is_open"]:
        raise ValidationError(f'An account named "{holder["name"]}" already exists. Choose a different name.')
    raise ValidationError(
        f'A closed account named "{holder["name"]}" already exists. Choose a different name, '
        "or rename the closed account first.")


def add_account(op: Operation, name: str | None, class_id: int,
                type_id: int | None, notes: str | None = None, currency_id: int | None = None) -> int:
    """Add an account. Its currency is chosen here and never changes: the one given, which must be enabled and have at least one
    stored rate unless it is the system currency, or the system currency. While the system currency is unset no account can be
    added."""
    conn = op.conn
    with db.write_transaction(conn):
        currency = currencies.require_system_currency(conn)
        if currency_id is not None and currency_id != currency.id:
            if not currencies.is_usable(conn, currency_id):
                raise ValidationError("Choose a currency that is enabled.")
            currency = currencies.get(conn, currency_id)
            if not rates.has_rate(conn, currency.id):
                raise ValidationError(f"{currency.code} has no exchange rate yet. An administrator adds one on its currency "
                                      "page before an account can use it.")
        name = _clean_name(name)
        type_id = _check_type(conn, type_id, class_id)
        _check_name_free(conn, name)
        return writer.insert(op, "accounts", {
            "name": name, "type_id": type_id, "currency_id": currency.id, "notes": _clean_notes(notes)})


UNCHANGED = object()       # "the website was not sent": a partial update leaves it as it is, where None (or blank) clears it


def update_account(op: Operation, account_id: int, name: str | None,
                   type_id: int | None, notes: str | None = None, website: str | None | object = UNCHANGED) -> list[str]:
    """Rename, re-type within the account's own class, and edit notes and the website. Returns what cleaning removed from the website
    (see clean_website), so the page can say so."""
    conn = op.conn
    with db.write_transaction(conn):
        account = get_account(conn, account_id)
        name = _clean_name(name)
        type_id = _check_type(conn, type_id, account["class_id"])
        _check_name_free(conn, name, account_id)
        values = {"name": name, "type_id": type_id, "notes": _clean_notes(notes)}
        removed: list[str] = []
        if website is not UNCHANGED:
            values["website"], removed = clean_website(website)
        writer.update(op, "accounts", account_id, values)
        return removed


def change_class(op: Operation, account_id: int, new_type_id: int | None) -> None:
    """Move the account to the class of the chosen type. Class and type change together."""
    conn = op.conn
    with db.write_transaction(conn):
        account = get_account(conn, account_id)
        row = conn.execute(
            "SELECT class_id FROM account_types WHERE id = ?", (new_type_id,)
        ).fetchone() if new_type_id is not None else None
        if row is None:
            raise ValidationError("Choose a type from the list.")
        if row["class_id"] == account["class_id"]:
            raise ValidationError("Choose a type in the other class.")
        writer.update(op, "accounts", account_id, {"type_id": new_type_id})   # the type decides the class


def close_account(op: Operation, account_id: int) -> None:
    """Close an account whose latest balance is zero, or that has no balances.

    The check and the close are one transaction, so a balance entered at the same moment cannot slip in
    between and leave a closed account with a nonzero balance.
    """
    conn = op.conn
    with db.write_transaction(conn):
        account = get_account(conn, account_id)
        if not account["is_open"]:
            raise ValidationError("That account is already closed.")
        latest = conn.execute(
            "SELECT amount_cents FROM last_balances WHERE account_id = ?", (account_id,),
        ).fetchone()
        if latest is not None and latest["amount_cents"] != 0:
            raise ValidationError(
                f"The latest balance for {account['name']} is not zero. "
                "Enter a final zero balance first, then close the account."
            )
        writer.update(op, "accounts", account_id, {"is_open": 0})


def reopen_account(op: Operation, account_id: int) -> None:
    conn = op.conn
    with db.write_transaction(conn):
        account = get_account(conn, account_id)
        if account["is_open"]:
            raise ValidationError("That account is already open.")
        writer.update(op, "accounts", account_id, {"is_open": 1})


def delete_account(op: Operation, account_id: int) -> int:
    """Delete the account. Its balances stay in the database and leave every view with it, so net worth history changes
    to match. Returns how many balances went with it. The name is free for another account straight away."""
    conn = op.conn
    with db.write_transaction(conn):
        count = get_account(conn, account_id)["balance_count"]
        writer.update(op, "accounts", account_id, {"deleted": 1})
    return count
