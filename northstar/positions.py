"""Account positions: what each account is worth on a date. Plain functions, no web code.

A balance is a recorded fact: an amount in the account's own currency on a date, unaffected by exchange rates (it can be corrected, but
a rate never changes it). An account's **position** on a day is derived: its latest balance on or before the day, converted at the
latest rate of its currency on or before the day, whatever date the balance has. It moves when a rate moves even though no balance was
entered. Net worth is the sum of positions, and the Dashboard works this way: `networth.net_worth_on` and this module read the same
view, `account_days`, so they share the rule that picks the balance and the rate, and both convert with `conversion.convert`. The
aggregation by class is written in both places, and the parity tests keep them together.

Each position carries the fact (the balance's id, amount and date), the native currency, the rate used and its date, the value in
the system currency and the signed contribution to net worth, so a report can show where a figure came from and link to the balance.

* An account in the population with no balance by the day is listed with no balance, no rate and a value of zero, whatever its
  currency: nothing needs converting, and a report can tell "no balance" from a recorded zero, which is a balance and (in another
  currency) still needs a rate.
* A balance in another currency needs a rate on or before the day, a zero included. If any day asked about lacks one the whole call
  fails with `NoRate` for the earliest such day, naming every currency missing a rate on it, and nothing is returned. Only the accounts in
  the population count, so a report on dollar accounts is not refused for an unrelated account in euros.
* Days beyond the last balance or rate behave as that last day, as in `networth`, and a position names the day that was asked.
* Positions come back for each day in account-id order, and an empty list of days returns `{}` without reading anything.

Everything is read inside `db.read_transaction`, which joins the caller's transaction or opens its own, so the accounts, the balances
and rates and the system currency come from one snapshot.
"""

import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable

from northstar import currencies, db
from northstar.conversion import convert
from northstar.errors import ValidationError
from northstar.networth import ASSET, MAX_POINTS, NoRate, _last_day
from northstar.reports.population import Population

MAX_DAYS = MAX_POINTS         # one call cannot ask about more days than a series can


@dataclass(frozen=True)
class Balance:
    """The fact a position rests on."""
    id: int
    amount: int               # in the account's own currency, in its minor units, as entered (a mortgage is positive)
    as_of_date: str


@dataclass(frozen=True)
class Rate:
    """The rate a balance was converted at: 1 unit of the account's currency = `rate` units of the system currency."""
    rate: str                 # the exact decimal text
    rate_date: str


@dataclass(frozen=True)
class AccountPosition:
    account_id: int
    day: date                 # the day asked about
    class_name: str           # Asset or Liability, the account's class now
    currency_code: str        # the account's own currency, and its decimal places, so a native amount can be formatted
    minor_units: int
    balance: Balance | None   # None: no balance on or before the day
    rate: Rate | None         # None when nothing was converted: the system currency, or no balance
    value: int                # the balance in the system currency's minor units, as entered (a mortgage is positive); 0 with no balance

    @property
    def signed_value(self) -> int:
        """What this account adds to net worth: its value for an asset, minus its value for a liability."""
        return self.value if self.class_name == ASSET else -self.value


@dataclass(frozen=True)
class Totals:
    assets: int
    liabilities: int
    net_worth: int


def totals(positions: Iterable[AccountPosition]) -> Totals:
    """Assets, liabilities and net worth of some positions, which are the sums by class and their difference."""
    assets = liabilities = 0
    for position in positions:
        if position.class_name == ASSET:
            assets += position.value
        else:
            liabilities += position.value
    return Totals(assets, liabilities, assets - liabilities)


def _days(days: Iterable[date]) -> list[date]:
    wanted = sorted(set(days))
    if len(wanted) > MAX_DAYS:
        raise ValidationError(f"Ask about at most {MAX_DAYS} days at a time.")
    for day in wanted:
        if not isinstance(day, date) or isinstance(day, datetime):
            raise ValueError("A day is a date.")
    return wanted


def account_positions(conn, population: Population, days: Iterable[date]) -> dict[date, tuple[AccountPosition, ...]]:
    """The position of every live account in the population on each day, oldest day first and in account-id order within it. Raises
    NoRate when a balance cannot be converted on some day (see the module's notes)."""
    wanted = _days(days)
    if not wanted:
        return {}
    ids = population.account_ids()
    if not ids:
        return {day: () for day in wanted}
    ids_json = _json(ids)
    with db.read_transaction(conn):
        system = currencies.require_system_currency(conn)
        accounts = conn.execute(
            "SELECT a.id, cl.name AS class_name, cur.code, cur.minor_units "
            "FROM live_accounts a JOIN account_types t ON t.id = a.type_id JOIN account_classes cl ON cl.id = t.class_id "
            "JOIN currencies cur ON cur.id = a.currency_id WHERE a.id IN (SELECT value FROM json_each(?)) ORDER BY a.id",
            (ids_json,)).fetchall()
        last = _last_day(conn)
        effective = {day: (min(day.isoformat(), last) if last is not None else None) for day in wanted}
        rows = {}
        looked_up = sorted({day for day in effective.values() if day is not None})
        if looked_up:
            for row in conn.execute(
                    "SELECT day, account_id, amount, rate, balance_id, balance_date, rate_date FROM account_days "
                    "WHERE day IN (SELECT value FROM json_each(?)) AND account_id IN (SELECT value FROM json_each(?))",
                    (_json(looked_up), ids_json)):
                rows[(row["day"], row["account_id"])] = row
    result = {}
    for day in wanted:                                  # oldest first, so the earliest failing day is the one reported
        positions, missing = [], set()
        for account in accounts:
            row = rows.get((effective[day], account["id"])) if effective[day] is not None else None
            if row is None:
                positions.append(AccountPosition(account["id"], day, account["class_name"], account["code"], account["minor_units"],
                                                 None, None, 0))
                continue
            balance = Balance(row["balance_id"], row["amount"], row["balance_date"])
            if account["code"] == system.code:
                positions.append(AccountPosition(account["id"], day, account["class_name"], account["code"], account["minor_units"],
                                                 balance, None, row["amount"]))
            elif row["rate"] is None:
                missing.add(account["code"])
            else:
                value = convert(row["amount"], account["minor_units"], row["rate"], system.minor_units)
                positions.append(AccountPosition(account["id"], day, account["class_name"], account["code"], account["minor_units"],
                                                 balance, Rate(row["rate"], row["rate_date"]), value))
        if missing:
            raise NoRate(day.isoformat(), sorted(missing))
        result[day] = tuple(positions)
    return result


def _json(values) -> str:
    return json.dumps(list(values))
