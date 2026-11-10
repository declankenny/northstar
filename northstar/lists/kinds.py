"""Field kinds: what a column of a list can be, and so how it is sorted, filtered and grouped.

A kind knows its operators, how to read a value a person (or a saved filter) supplied, and the SQL that tests a column
against it. It never builds SQL from the value: the value is always a parameter. Display (locale, units) is the page's
job, so a kind deals only in stored values: integers, text, ISO dates and UTC timestamps.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from northstar.errors import ValidationError

OPERATOR_NAMES = {
    "contains": "contains", "equals": "equals", "is_empty": "is empty", "is_not_empty": "is not empty",
    "at_least": "is at least", "at_most": "is at most", "between": "is between",
    "before": "is before", "after": "is after", "is_yes": "is Yes", "is_no": "is No",
    "is": "is", "is_not": "is not", "is_any_of": "is one of", "is_not_any_of": "is not one of",     # a choice (the stored name of "is one of" stays)
}


LARGEST = 2 ** 62                   # a stored integer must fit SQLite's 64 bits, with room to normalise


def fits(number: int) -> int:
    """The number, or a ValidationError if it is too large to be a stored value."""
    if abs(number) > LARGEST:
        raise ValidationError("That number is too large.")
    return number


def escape_like(text: str) -> str:
    """The text with LIKE's wildcards made literal (used with ESCAPE '\\')."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class Kind:
    """Base of every kind. A subclass sets `operators` and implements `read` and `where`."""

    name = ""
    code = ""                           # what the page chooses how to draw and align a column by
    operators: tuple[str, ...] = ()
    sorts_without_case = False          # text sorts and compares ignoring ASCII case, as everywhere in Northstar
    uses_date_part = False              # compares the first ten characters (a UTC timestamp's date)

    # How the engine reads and shows a column of this kind. The defaults read the column itself.

    def select(self, view, resolved) -> list[str]:
        """The SQL expressions a row of this column is made from. The first is the value."""
        return [view.plain(resolved)]

    def shape(self, values: list):
        """The value a row shows, made from what `select` produced."""
        return values[0]

    def compare(self, view, resolved) -> str:
        """The SQL expression that is sorted, grouped and filtered."""
        return view.plain(resolved)

    def read(self, operator: str, value):
        """The value as the SQL needs it, or a ValidationError that says what is wrong."""
        raise NotImplementedError

    def where(self, expression: str, operator: str, value) -> tuple[str, list]:
        """The SQL that is true for rows whose `expression` matches, with its parameters. `value` was read by `read`."""
        raise NotImplementedError

    def check_operator(self, operator) -> None:
        if not isinstance(operator, str) or not operator:
            raise ValidationError("Choose how to filter.")
        if operator not in self.operators:
            allowed = ", ".join(OPERATOR_NAMES[o] for o in self.operators)
            raise ValidationError(f"A {self.name} cannot be filtered with “{operator}”. Choose one of: {allowed}.")


class Text(Kind):
    name = "text"
    code = "text"
    operators = ("contains", "equals", "is_empty", "is_not_empty")
    sorts_without_case = True

    def read(self, operator, value):
        self.check_operator(operator)
        if operator in ("is_empty", "is_not_empty"):
            return None
        if not isinstance(value, str) or value == "":
            raise ValidationError("Type the text to look for.")
        if len(value) > 256:
            raise ValidationError("That text is too long to filter by.")
        return value

    def where(self, expression, operator, value):
        if operator == "contains":
            return f"{expression} LIKE ? ESCAPE '\\'", [f"%{escape_like(value)}%"]
        if operator == "equals":
            return f"{expression} = ? COLLATE NOCASE", [value]
        if operator == "is_empty":                                   # no value, or an empty one
            return f"({expression} IS NULL OR {expression} = '')", []
        return f"({expression} IS NOT NULL AND {expression} <> '')", []


class _Number(Kind):
    """Integers, decimals and scaled integers. Subclasses say how a typed number becomes the stored one."""

    operators = ("equals", "at_least", "at_most", "between", "is_empty", "is_not_empty")

    def number(self, text):
        raise NotImplementedError

    def read(self, operator, value):
        self.check_operator(operator)
        if operator in ("is_empty", "is_not_empty"):
            return None
        if operator == "between":
            if not (isinstance(value, (list, tuple)) and len(value) == 2):
                raise ValidationError("Give the two ends of the range.")
            low, high = self.number(value[0]), self.number(value[1])
            if low > high:
                raise ValidationError("The range ends before it starts.")
            return (low, high)
        return self.number(value)

    def where(self, expression, operator, value):
        if operator == "is_empty":
            return f"{expression} IS NULL", []
        if operator == "is_not_empty":
            return f"{expression} IS NOT NULL", []
        if operator == "between":
            return f"{expression} BETWEEN ? AND ?", [value[0], value[1]]
        sign = {"equals": "=", "at_least": ">=", "at_most": "<="}[operator]
        return f"{expression} {sign} ?", [value]


class Integer(_Number):
    name = "whole number"
    code = "integer"

    def number(self, text):
        if isinstance(text, bool) or not isinstance(text, (int, str)):
            raise ValidationError("Type a whole number.")
        try:
            return fits(int(str(text).strip()))
        except ValueError:
            raise ValidationError("Type a whole number.") from None


class Number(_Number):
    """A number stored as a float (a measurement). Compared as the float it is."""

    name = "number"
    code = "number"

    def number(self, text):
        if isinstance(text, bool) or not isinstance(text, (int, float, str)):
            raise ValidationError("Type a number.")
        try:
            number = float(str(text).strip())
        except ValueError:
            raise ValidationError("Type a number.") from None
        if number != number or number in (float("inf"), float("-inf")):
            raise ValidationError("Type a number.")
        return number


@dataclass(frozen=True)
class Scaled(_Number):
    """An exact decimal stored as an integer count of 10^-scale units (hundredths of a degree for scale 2). A typed value
    with more places than the scale is refused, never rounded."""

    scale: int
    name = "decimal"
    code = "decimal"

    def number(self, text):
        if isinstance(text, bool) or not isinstance(text, (int, str)):
            raise ValidationError("Type a number.")
        try:
            exact = Decimal(str(text).strip())
        except InvalidOperation:
            raise ValidationError("Type a number.") from None
        if not exact.is_finite():
            raise ValidationError("Type a number.")
        stored = exact * (10 ** self.scale)
        if stored != stored.to_integral_value():
            raise ValidationError(f"Use at most {self.scale} decimal places.")
        return fits(int(stored))


class Date(Kind):
    name = "date"
    code = "date"
    operators = ("before", "after", "between", "is_empty", "is_not_empty")

    def day(self, text) -> str:
        if isinstance(text, str) and len(text) == 10:
            try:
                return date.fromisoformat(text).isoformat()
            except ValueError:
                pass
        raise ValidationError("Choose a real date.")

    def read(self, operator, value):
        self.check_operator(operator)
        if operator in ("is_empty", "is_not_empty"):
            return None
        if operator == "between":
            if not (isinstance(value, (list, tuple)) and len(value) == 2):
                raise ValidationError("Give the two ends of the range.")
            low, high = self.day(value[0]), self.day(value[1])
            if low > high:
                raise ValidationError("The range ends before it starts.")
            return (low, high)
        return self.day(value)

    def where(self, expression, operator, value):
        part = f"substr({expression}, 1, 10)" if self.uses_date_part else expression
        if operator == "is_empty":
            return f"{expression} IS NULL", []
        if operator == "is_not_empty":
            return f"{expression} IS NOT NULL", []
        if operator == "between":                                    # both ends included
            return f"{part} BETWEEN ? AND ?", [value[0], value[1]]
        return f"{part} {'<' if operator == 'before' else '>'} ?", [value]      # before and after exclude the day


class Timestamp(Date):
    """A UTC instant (`2026-01-31T09:30:00Z`), shown and filtered as its UTC date."""

    name = "timestamp"
    code = "timestamp"
    uses_date_part = True


@dataclass(frozen=True)
class YesNo(Kind):
    """A flag stored as 1 or 0. When the column can be empty (not yet known) it also offers “is empty” and “is not empty”."""

    nullable: bool = False
    name = "Yes or No"
    code = "yes_no"

    @property
    def operators(self):                                            # type: ignore[override]
        return ("is_yes", "is_no", "is_empty", "is_not_empty") if self.nullable else ("is_yes", "is_no")

    def read(self, operator, value):
        self.check_operator(operator)
        return None

    def where(self, expression, operator, value):
        return {"is_yes": (f"{expression} = 1", []), "is_no": (f"{expression} = 0", []),
                "is_empty": (f"{expression} IS NULL", []), "is_not_empty": (f"{expression} IS NOT NULL", [])}[operator]


class _Choice(Kind):
    """A column whose value is one of a set of choices. It is filtered by one value (“is”, “is not”), by several (“is one of”, “is not
    one of”) or by whether it has one (“is empty”, “is not empty”). The negatives include rows with no value: “is not Savings” lists
    a row with no type too, which SQL's own `<>` and `NOT IN` would leave out."""

    name = "choice"
    code = "choice"
    operators = ("is", "is_not", "is_any_of", "is_not_any_of", "is_empty", "is_not_empty")

    def one(self, item):
        """A single choice as the SQL needs it, or a ValidationError."""
        raise NotImplementedError

    def read(self, operator, value):
        self.check_operator(operator)
        if operator in ("is_empty", "is_not_empty"):
            return None
        if operator in ("is", "is_not"):
            if isinstance(value, (list, tuple, dict)) or value is None:
                raise ValidationError("Choose a value.")
            return self.one(value)
        if not (isinstance(value, (list, tuple)) and value):
            raise ValidationError("Choose at least one value.")
        return tuple(self.one(item) for item in value)

    def where(self, expression, operator, value):
        if operator == "is_empty":
            return f"{expression} IS NULL", []
        if operator == "is_not_empty":
            return f"{expression} IS NOT NULL", []
        if operator == "is":
            return f"{expression} = ?", [value]
        if operator == "is_not":
            return f"({expression} IS NULL OR {expression} <> ?)", [value]
        marks = ", ".join("?" * len(value))
        if operator == "is_any_of":
            return f"{expression} IN ({marks})", list(value)
        return f"({expression} IS NULL OR {expression} NOT IN ({marks}))", list(value)


@dataclass(frozen=True)
class Category(_Choice):
    """One of a declared set of values (a status)."""

    values: tuple[str, ...]

    def one(self, item):
        if not isinstance(item, str) or item not in self.values:
            raise ValidationError(f"“{item}” is not one of the choices.")
        return item


class Reference(_Choice):
    """The id of the record a relation points at. Filtered by id, though shown by display value."""

    def one(self, item):
        if isinstance(item, bool) or not isinstance(item, int):
            raise ValidationError("Choose from the list.")
        return item


# -- amounts whose scale is not the column's own --

COMMON_SCALE = 3                    # amounts are compared in thousandths of a unit: exact, and enough for any scale used


class Quantity(Kind):
    """An exact amount held as an integer with a scale that can differ from row to row (hundredths in one row, whole units in
    the next). It is sorted and compared by the number a person sees, normalised to thousandths, so a value of 10 with scale 2
    and a value of 10 with scale 0 are equal. A typed amount may have at most three decimal places, and no row can equal one
    with more places than its own scale."""

    name = "amount"
    code = "amount"
    operators = ("equals", "at_least", "at_most", "between", "is_empty", "is_not_empty")

    def number(self, text) -> int:
        if isinstance(text, bool) or not isinstance(text, (int, str)):
            raise ValidationError("Type an amount.")
        try:
            exact = Decimal(str(text).strip())
        except InvalidOperation:
            raise ValidationError("Type an amount.") from None
        if not exact.is_finite():
            raise ValidationError("Type an amount.")
        scaled = exact * (10 ** COMMON_SCALE)
        if scaled != scaled.to_integral_value():
            raise ValidationError(f"Use at most {COMMON_SCALE} decimal places.")
        return fits(int(scaled))

    read = _Number.read
    where = _Number.where


def normalise(value: int | None, scale: int) -> int | None:
    """An amount with `scale` decimal places, as thousandths."""
    if value is None:
        return None
    if not 0 <= scale <= COMMON_SCALE:
        raise ValueError(f"A scale of {scale} is not supported: amounts are compared to {COMMON_SCALE} places.")
    return value * 10 ** (COMMON_SCALE - scale)


@dataclass(frozen=True)
class ScaledBy(Quantity):
    """An amount whose scale is a column of a record it points at. `scale_from` and `unit_from` are paths of relation names from the
    column's own table, ending in a column (`("account", "currency", "minor_units")`). Nothing here says what the scale or the
    unit mean: a row shows its value, its scale and its unit, and the page decides how to write them."""

    scale_from: tuple[str, ...] = ()
    unit_from: tuple[str, ...] | None = None

    def _scale_sql(self, view, resolved) -> str:
        alias = view.alias_via(resolved, self.scale_from[:-1])
        return f'{alias}."{self.scale_from[-1]}"'

    def select(self, view, resolved):
        amount = view.plain(resolved)
        unit = "NULL"
        if self.unit_from:
            unit = f'{view.alias_via(resolved, self.unit_from[:-1])}."{self.unit_from[-1]}"'
        return [amount, self._scale_sql(view, resolved), unit]

    def shape(self, values):
        value, scale, unit = values
        return None if value is None else {"value": value, "scale": scale, "unit": unit}

    def compare(self, view, resolved):
        amount, scale = view.plain(resolved), self._scale_sql(view, resolved)
        steps = " ".join(f"WHEN {n} THEN {10 ** (COMMON_SCALE - n)}" for n in range(COMMON_SCALE + 1))
        return f"({amount} * CASE {scale} {steps} END)"
