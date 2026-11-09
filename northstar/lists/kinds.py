"""Field kinds: what a column of a list can be, and so how it is sorted, filtered and grouped.

A kind knows its operators, how to read a value a person (or a saved filter) supplied, and the SQL that tests a column
against it. It never builds SQL from the value: the value is always a parameter. Display (locale, currency) is the page's
job, so a kind deals only in stored values: integers, text, ISO dates and UTC timestamps.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from northstar.errors import ValidationError

OPERATOR_NAMES = {
    "contains": "contains", "equals": "equals", "is_empty": "is empty", "is_not_empty": "is not empty",
    "at_least": "is at least", "at_most": "is at most", "between": "is between",
    "before": "is before", "after": "is after", "is_yes": "is Yes", "is_no": "is No", "is_any_of": "is any of",
}


def escape_like(text: str) -> str:
    """The text with LIKE's wildcards made literal (used with ESCAPE '\\')."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class Kind:
    """Base of every kind. A subclass sets `operators` and implements `read` and `where`."""

    name = ""
    operators: tuple[str, ...] = ()
    sorts_without_case = False          # text sorts and compares ignoring ASCII case, as everywhere in Northstar
    uses_date_part = False              # compares the first ten characters (a UTC timestamp's date)

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

    operators = ("equals", "at_least", "at_most", "between", "is_empty")

    def number(self, text):
        raise NotImplementedError

    def read(self, operator, value):
        self.check_operator(operator)
        if operator == "is_empty":
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
        if operator == "between":
            return f"{expression} BETWEEN ? AND ?", [value[0], value[1]]
        sign = {"equals": "=", "at_least": ">=", "at_most": "<="}[operator]
        return f"{expression} {sign} ?", [value]


class Integer(_Number):
    name = "whole number"

    def number(self, text):
        if isinstance(text, bool) or not isinstance(text, (int, str)):
            raise ValidationError("Type a whole number.")
        try:
            return int(str(text).strip())
        except ValueError:
            raise ValidationError("Type a whole number.") from None


class Number(_Number):
    """A number stored as a float (a measurement). Compared as the float it is."""

    name = "number"

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
        return int(stored)


class Date(Kind):
    name = "date"
    operators = ("before", "after", "between", "is_empty")

    def day(self, text) -> str:
        if isinstance(text, str) and len(text) == 10:
            try:
                return date.fromisoformat(text).isoformat()
            except ValueError:
                pass
        raise ValidationError("Choose a real date.")

    def read(self, operator, value):
        self.check_operator(operator)
        if operator == "is_empty":
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
        if operator == "between":                                    # both ends included
            return f"{part} BETWEEN ? AND ?", [value[0], value[1]]
        return f"{part} {'<' if operator == 'before' else '>'} ?", [value]      # before and after exclude the day


class Timestamp(Date):
    """A UTC instant (`2026-01-31T09:30:00Z`), shown and filtered as its UTC date."""

    name = "timestamp"
    uses_date_part = True


@dataclass(frozen=True)
class YesNo(Kind):
    """A flag stored as 1 or 0. When the column can be empty (not yet known) it also offers “is empty”."""

    nullable: bool = False
    name = "Yes or No"

    @property
    def operators(self):                                            # type: ignore[override]
        return ("is_yes", "is_no", "is_empty") if self.nullable else ("is_yes", "is_no")

    def read(self, operator, value):
        self.check_operator(operator)
        return None

    def where(self, expression, operator, value):
        return {"is_yes": (f"{expression} = 1", []), "is_no": (f"{expression} = 0", []),
                "is_empty": (f"{expression} IS NULL", [])}[operator]


@dataclass(frozen=True)
class Category(Kind):
    """One of a declared set of values (a status). Filtered with “is any of”."""

    values: tuple[str, ...]
    name = "choice"
    operators = ("is_any_of",)

    def read(self, operator, value):
        self.check_operator(operator)
        if not (isinstance(value, (list, tuple)) and value):
            raise ValidationError("Choose at least one value.")
        for item in value:
            if item not in self.values:
                raise ValidationError(f"“{item}” is not one of the choices.")
        return tuple(value)

    def where(self, expression, operator, value):
        return f"{expression} IN ({', '.join('?' * len(value))})", list(value)


class Reference(Kind):
    """The id of the record a relation points at. Filtered with “is any of”, by id, though shown by display value."""

    name = "choice"
    operators = ("is_any_of",)

    def read(self, operator, value):
        self.check_operator(operator)
        if not (isinstance(value, (list, tuple)) and value):
            raise ValidationError("Choose at least one value.")
        ids = []
        for item in value:
            if isinstance(item, bool) or not isinstance(item, int):
                raise ValidationError("Choose from the list.")
            ids.append(item)
        return tuple(ids)

    def where(self, expression, operator, value):
        return f"{expression} IN ({', '.join('?' * len(value))})", list(value)
