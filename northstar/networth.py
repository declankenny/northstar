"""Net worth. Plain functions, no web code.

Net worth on a date = assets minus liabilities, where each account counts at its latest balance on or before that date. An
account with no balance yet counts for nothing. Closed accounts need no special case: their final balance is zero and it
carries forward like any other.

Every household figure is in the system currency. An account in another currency is converted with the latest rate of its
currency on or before the date (the view `account_days` looks both up), each account on its own, rounded half away from zero to
a whole minor unit of the system currency, and the converted amounts are summed. A zero is converted like any other amount. A
date on which an account has no rate to convert with has no net worth: it is refused, never totalled without that account.
A single account's figures are in its own currency and need no rate.

An account is counted in the class it has now, for every date, so changing an account's class changes past net worth too.
That is the rule agreed in the spec.

There is one calculation, net_worth_on. Everything else only chooses which dates to ask about.
"""

import calendar
import json
import sqlite3
from datetime import date, timedelta

from northstar import accounts, currencies, locales
from northstar.conversion import convert      # the one place the arithmetic is written; net worth calls it by this name
from northstar.errors import ValidationError

ASSET = "Asset"
LIABILITY = "Liability"


class NoRate(ValidationError):
    """A date on which an account is in a currency that has no rate yet, so its balance cannot be converted."""

    def __init__(self, day: str, codes: list[str]):
        super().__init__(
            f"There is no {', '.join(codes)} rate on or before {locales.speaking().date(day)}, so net worth cannot be worked out "
            "for that date. An administrator can add rates on the currency's page.")
        self.codes = codes

    @property
    def details(self) -> dict:
        return {"missing_rates": self.codes}


def _last_day(conn: sqlite3.Connection) -> str | None:
    """The last day the view covers: the newest balance or rate. Nothing changes after it, so a later date is its answer."""
    return conn.execute("SELECT MAX(day) FROM account_days").fetchone()[0]


def _totals(conn: sqlite3.Connection, days: list[date], account_id: int | None) -> dict[date, dict]:
    """Assets, liabilities and net worth for each date, in one query. With an account the figures are in its own currency."""
    last = _last_day(conn)
    effective = {day: (min(day.isoformat(), last) if last is not None else None) for day in days}
    wanted = sorted({day for day in effective.values() if day is not None})
    by_day: dict[str, list[sqlite3.Row]] = {day: [] for day in wanted}
    if wanted:
        for row in conn.execute(
                "SELECT day, class_name, currency_code, minor_units, converts, amount, rate FROM account_days "
                "WHERE day IN (SELECT value FROM json_each(?)) AND (? IS NULL OR account_id = ?)",
                (json.dumps(wanted), account_id, account_id)):
            by_day[row["day"]].append(row)
    system = currencies.system_currency(conn)
    result = {}
    for day in days:
        totals = {ASSET: 0, LIABILITY: 0}
        missing = []
        for row in (by_day[effective[day]] if effective[day] is not None else []):
            amount = row["amount"]
            if account_id is None and row["converts"]:
                if row["rate"] is None:
                    missing.append(row["currency_code"])
                    continue
                amount = convert(amount, row["minor_units"], row["rate"], system.minor_units)
            totals[row["class_name"]] += amount
        if missing:
            raise NoRate(day.isoformat(), sorted(set(missing)))
        result[day] = {"date": day.isoformat(), "assets": totals[ASSET], "liabilities": totals[LIABILITY],
                       "net_worth": totals[ASSET] - totals[LIABILITY]}
    return result


def net_worth_on(conn: sqlite3.Connection, as_of: date, account_id: int | None = None) -> dict:
    """Assets, liabilities and net worth on one date, in the system currency, as integer minor units.

    With an account_id the same calculation covers only that account, in its own currency and with no conversion: its balance
    lands in assets or liabilities by its class, so a single account is just a small household. A date on which an account has
    no rate to convert with raises NoRate.
    """
    return _totals(conn, [as_of], account_id)[as_of]


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


def _uncovered(conn: sqlite3.Connection, start: date, end: date) -> tuple[str | None, list[str]]:
    """The last date up to `end` on which a balance in another currency has no rate, and the currencies that lack one from
    `start` on."""
    row = conn.execute("SELECT MAX(day) FROM account_days WHERE converts AND rate IS NULL AND day <= ?", (end.isoformat(),)).fetchone()
    codes = [r[0] for r in conn.execute(
        "SELECT DISTINCT currency_code FROM account_days WHERE converts AND rate IS NULL AND day BETWEEN ? AND ? ORDER BY 1",
        (start.isoformat(), end.isoformat()))]
    return row[0], codes


def net_worth_series(conn: sqlite3.Connection, today: date, start: date | None = None,
                     end: date | None = None, period: str = "month",
                     account_id: int | None = None) -> dict:
    """Net worth at regular dates between start and end, oldest first. Each point is net_worth_on.

    End defaults to today and cannot be after it. Start defaults to the date of the first balance and is never earlier than
    that: before any balance net worth is zero only because nothing has been entered, and drawing it would look like a climb
    from zero. The dates actually used are returned. Empty when there are no balances up to end.

    A household series also never starts before the first date from which every later date can be converted. A balance in
    another currency has no rate before that currency's first rate, so the dates up to there are left out and `limited` says
    where the series starts and which currencies are missing rates; it is None when nothing was left out. If no date up to end
    can be converted the series is empty and `limited` says so.

    With an account_id the series covers that account alone, in its own currency, and "the first balance" is that account's own
    first balance. An unknown account raises NotFoundError. It also says how many of that account's balances fall inside the dates
    shown (`balance_count`, which a household series leaves empty).
    """
    if account_id is not None:
        accounts.get_account(conn, account_id)
    end = end or today
    if end > today:
        raise ValidationError("The end date cannot be after today.")
    if period not in PERIODS:
        raise ValidationError(f"The period must be one of: {', '.join(PERIODS)}.")
    first = conn.execute(
        "SELECT MIN(as_of_date) FROM live_balances WHERE (? IS NULL OR account_id = ?)",
        (account_id, account_id)).fetchone()[0]
    if first is None or date.fromisoformat(first) > end:
        return {"start": end.isoformat(), "end": end.isoformat(), "period": period, "series": [], "limited": None,
                "balance_count": 0 if account_id is not None else None}
    start = max(start, date.fromisoformat(first)) if start else date.fromisoformat(first)
    if start > end:
        raise ValidationError("The start date cannot be after the end date.")
    limited = None
    if account_id is None:
        through, codes = _uncovered(conn, start, end)
        if through is not None and date.fromisoformat(through) >= start:
            begins = date.fromisoformat(through) + timedelta(days=1)
            if begins > end or through >= _last_day(conn):
                return {"start": start.isoformat(), "end": end.isoformat(), "period": period, "series": [],
                        "limited": {"starts_on": None, "currencies": codes}, "balance_count": None}
            start, limited = begins, {"starts_on": begins.isoformat(), "currencies": codes}
    days = sample_dates(start, end, period)
    totals = _totals(conn, days, account_id)
    count = None
    if account_id is not None:          # the account's own balances inside the dates shown, for its page
        count = conn.execute("SELECT COUNT(*) FROM live_balances WHERE account_id = ? AND as_of_date BETWEEN ? AND ?",
                             (account_id, start.isoformat(), end.isoformat())).fetchone()[0]
    return {"start": start.isoformat(), "end": end.isoformat(), "period": period,
            "series": [totals[day] for day in days], "limited": limited, "balance_count": count}


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
