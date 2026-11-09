"""Converting an amount into the system currency, for a list column that shows it.

This is Northstar's own rule (docs/spec.md, "Conversion"), written once in networth.convert: the latest rate of the amount's
currency on or before the day, never a later one, in exact decimal arithmetic, rounded half away from zero to a whole minor unit
of the system currency. The list engine only calls this function for the rows it needs and carries what it answers.
"""

from bisect import bisect_right
from datetime import date

from northstar import currencies, networth
from northstar.lists.kinds import Answer


def _rates(conn, codes: set[str]) -> dict[str, tuple[list[str], list[str]]]:
    """For each code, the dates of its rates in order and the rates themselves (as exact decimal text)."""
    found: dict[str, tuple[list[str], list[str]]] = {code: ([], []) for code in codes}
    if codes:
        marks = ", ".join("?" * len(codes))
        for row in conn.execute(
                f"SELECT c.code, r.rate_date, r.rate FROM exchange_rates r JOIN currencies c ON c.id = r.currency_id "
                f"WHERE c.code IN ({marks}) ORDER BY c.code, r.rate_date", sorted(codes)):
            found[row["code"]][0].append(row["rate_date"])
            found[row["code"]][1].append(row["rate"])
    return found


def reporting_value(day_key: str | None):
    """The function for a column showing an amount in the system currency. `day_key` names the input that holds the day to
    convert on (a balance's own date), or is None to convert on today's date. The inputs, in the order the column names them,
    are the amount in minor units, the minor units of its currency, the currency's code and the day."""

    def compute(conn, context, rows: list[dict]) -> list[Answer]:
        system = currencies.system_currency(conn)
        wanted = {row["account.currency"] for row in rows if row["amount_cents"] is not None and row["account.currency"]}
        table = _rates(conn, wanted - ({system.code} if system else set()))
        answers = []
        for row in rows:
            amount, code = row["amount_cents"], row["account.currency"]
            if amount is None:
                answers.append(Answer(None))
            elif system is None:
                answers.append(Answer(None, 0, None, "The system currency is not set"))
            elif code == system.code:                                  # already in the system currency: no rate needed
                answers.append(Answer(amount, system.minor_units, system.code))
            else:
                day = row[day_key] if day_key else context.today.isoformat()
                dates, texts = table.get(code, ([], []))
                at = bisect_right(dates, day)                          # the last rate on or before the day
                if at == 0:
                    answers.append(Answer(None, system.minor_units, system.code, f"No {code} rate"))
                else:
                    value = networth.convert(amount, row["account.currency.minor_units"], texts[at - 1], system.minor_units)
                    answers.append(Answer(value, system.minor_units, system.code))
        return answers

    return compute
