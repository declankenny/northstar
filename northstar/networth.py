"""Net worth. Plain functions, no web code.

Net worth on a date = assets minus liabilities, where each account counts at its latest balance
on or before that date. An account with no balance yet counts for nothing. Closed accounts need
no special case: their final balance is zero and it carries forward like any other.

An account is counted in the class it has now, for every date, so changing an account's class
changes past net worth too. That is the rule agreed in the spec.

There is one calculation, net_worth_on. Everything else only chooses which dates to ask about.
"""

import calendar
import sqlite3
from datetime import date

ASSET = "Asset"
LIABILITY = "Liability"


def net_worth_on(conn: sqlite3.Connection, as_of: date) -> dict:
    """Assets, liabilities and net worth on one date, all in cents."""
    rows = conn.execute(
        "SELECT c.name AS class_name, SUM(b.amount_cents) AS total "
        "FROM accounts a "
        "JOIN account_classes c ON c.id = a.class_id "
        "JOIN balances b ON b.account_id = a.id AND b.as_of_date = ("
        "    SELECT MAX(b2.as_of_date) FROM balances b2 "
        "    WHERE b2.account_id = a.id AND b2.as_of_date <= ?) "
        "GROUP BY c.name",
        (as_of.isoformat(),),
    ).fetchall()
    by_class = {row["class_name"]: row["total"] for row in rows}
    assets, liabilities = by_class.get(ASSET, 0), by_class.get(LIABILITY, 0)
    return {"date": as_of.isoformat(), "assets": assets, "liabilities": liabilities,
            "net_worth": assets - liabilities}


def month_end_dates(first: date, today: date) -> list[tuple[date, bool]]:
    """The last day of every month from first's month through today's month, oldest first.

    The current month is not over yet, so it ends today and is marked partial.
    """
    dates = []
    year, month = first.year, first.month
    while (year, month) <= (today.year, today.month):
        month_end = date(year, month, calendar.monthrange(year, month)[1])
        dates.append((min(month_end, today), month_end > today))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return dates


def net_worth_by_month(conn: sqlite3.Connection, today: date) -> list[dict]:
    """Net worth at the end of every month from the first balance through today, oldest first.

    Months with no entries carry the previous values forward. The last row is the current month,
    as of today, with partial set to True unless today is itself the last day of the month.
    Empty when there are no balances.
    """
    first = conn.execute(
        "SELECT MIN(as_of_date) FROM balances WHERE as_of_date <= ?", (today.isoformat(),)
    ).fetchone()[0]
    if first is None:
        return []
    rows = []
    for day, partial in month_end_dates(date.fromisoformat(first), today):
        row = net_worth_on(conn, day)
        row["partial"] = partial
        rows.append(row)
    return rows
