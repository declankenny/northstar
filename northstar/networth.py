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
from datetime import date, timedelta

from northstar import accounts
from northstar.errors import ValidationError

ASSET = "Asset"
LIABILITY = "Liability"


def net_worth_on(conn: sqlite3.Connection, as_of: date, account_id: int | None = None) -> dict:
    """Assets, liabilities and net worth on one date, all in cents.

    With an account_id the same calculation covers only that account: its balance lands in
    assets or liabilities by its class, so a single account is just a small household.
    """
    rows = conn.execute(
        "SELECT c.name AS class_name, SUM(b.amount_cents) AS total "
        "FROM accounts a "
        "JOIN account_classes c ON c.id = a.class_id "
        "JOIN balances b ON b.account_id = a.id AND b.as_of_date = ("
        "    SELECT MAX(b2.as_of_date) FROM balances b2 "
        "    WHERE b2.account_id = a.id AND b2.as_of_date <= ?) "
        "WHERE (? IS NULL OR a.id = ?) "
        "GROUP BY c.name",
        (as_of.isoformat(), account_id, account_id),
    ).fetchall()
    by_class = {row["class_name"]: row["total"] for row in rows}
    assets, liabilities = by_class.get(ASSET, 0), by_class.get(LIABILITY, 0)
    return {"date": as_of.isoformat(), "assets": assets, "liabilities": liabilities,
            "net_worth": assets - liabilities}


PERIODS = ("day", "week", "month")
MAX_POINTS = 1000      # one request cannot ask for more points than this


def sample_dates(start: date, end: date, period: str) -> list[date]:
    """The dates to ask about, oldest first: start, then steps of the period, ending on end.

    Day is every day. Week counts back from end in sevens, so the newest point is always end.
    Month is each calendar month end after start, the last one cut off at end. Start is always
    included, so a chart's first point is exactly where the chart begins.
    """
    if period not in PERIODS:
        raise ValidationError(f"The period must be one of: {', '.join(PERIODS)}.")
    days = (end - start).days
    estimate = {"day": days + 1, "week": days // 7 + 2, "month": days // 28 + 2}[period]
    if estimate > MAX_POINTS:
        raise ValidationError(f"That range needs about {estimate} points. The most allowed is "
                              f"{MAX_POINTS}. Use a longer period or a shorter range.")
    if period == "day":
        dates = [start + timedelta(days=i) for i in range(days + 1)]
    elif period == "week":
        dates = [end - timedelta(days=7 * k) for k in range(days // 7 + 1)] + [start]
    else:
        dates = [start] + month_end_dates(start, end)
    return sorted(set(dates))


def net_worth_series(conn: sqlite3.Connection, today: date, start: date | None = None,
                     end: date | None = None, period: str = "month",
                     account_id: int | None = None) -> dict:
    """Net worth at regular dates between start and end, oldest first. Each point is net_worth_on.

    End defaults to today and cannot be after it. Start defaults to the date of the first balance
    and is never earlier than that: before any balance net worth is zero only because nothing has
    been entered, and drawing it would look like a climb from zero. The dates actually used are
    returned. Empty when there are no balances up to end.

    With an account_id the series covers that account alone, and "the first balance" is that
    account's own first balance. An unknown account raises NotFoundError.
    """
    if account_id is not None:
        accounts.get_account(conn, account_id)
    end = end or today
    if end > today:
        raise ValidationError("The end date cannot be after today.")
    if period not in PERIODS:
        raise ValidationError(f"The period must be one of: {', '.join(PERIODS)}.")
    first = conn.execute(
        "SELECT MIN(as_of_date) FROM balances WHERE (? IS NULL OR account_id = ?)",
        (account_id, account_id)).fetchone()[0]
    if first is None or date.fromisoformat(first) > end:
        return {"start": end.isoformat(), "end": end.isoformat(), "period": period, "series": []}
    start = max(start, date.fromisoformat(first)) if start else date.fromisoformat(first)
    if start > end:
        raise ValidationError("The start date cannot be after the end date.")
    return {"start": start.isoformat(), "end": end.isoformat(), "period": period,
            "series": [net_worth_on(conn, day, account_id) for day in sample_dates(start, end, period)]}


def month_end_dates(first: date, end: date) -> list[date]:
    """The last day of every month from first's month through end's month, oldest first.

    The last one is cut off at end when end is not itself a month end.
    """
    dates = []
    year, month = first.year, first.month
    while (year, month) <= (end.year, end.month):
        dates.append(min(date(year, month, calendar.monthrange(year, month)[1]), end))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return dates
