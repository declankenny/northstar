"""Converting an amount from one currency's minor units into another's. The one place the arithmetic is written.

Net worth calls `convert` from Python, and the database calls it from a view as the SQL function `northstar_convert`, registered
on every connection the application opens (see `db.connect`), so a figure is the same wherever it is worked out. A view that
calls it can only be read through such a connection: it can still be created, backed up and checked without one.

Exact decimal arithmetic, never floating point: SQLite has no decimal type and its integers overflow into floats, which is why
this is not written in SQL.
"""

import sqlite3
from decimal import ROUND_HALF_UP, Decimal, localcontext


def convert(amount: int, minor_units: int, rate: str, system_minor_units: int) -> int:
    """An amount in the minor units of a currency with `minor_units` decimal places, converted at `rate` (the exact decimal text:
    1 unit of that currency = `rate` units of the system currency) into minor units of the system currency, rounded half away
    from zero. Exact decimal arithmetic, never floating point."""
    with localcontext() as context:
        context.prec = 80
        value = Decimal(amount) * Decimal(rate) * Decimal(10) ** (system_minor_units - minor_units)
        return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _sql_convert(amount, minor_units, rate, system_minor_units):
    """`convert` for SQL. A value that is missing (no amount, no rate yet, no system currency) gives a missing answer."""
    if amount is None or minor_units is None or rate is None or system_minor_units is None:
        return None
    return convert(amount, minor_units, rate, system_minor_units)


def register(conn: sqlite3.Connection) -> None:
    """Make `northstar_convert(amount, minor_units, rate, system_minor_units)` available to SQL on this connection."""
    conn.create_function("northstar_convert", 4, _sql_convert, deterministic=True)
