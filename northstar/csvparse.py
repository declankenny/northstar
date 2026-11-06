"""Reading a balance CSV file: the file, the column mapping, dates, amounts and the whole-file check. See issue 99 and
issue 79 ("Formats").

Plain functions with no database and no web code, so the import screens, and later the locale work, can reuse them. Nothing
here keeps or logs what it reads: an error message may quote a value, and goes only to the person who uploaded it.

The order of use is read_table (the file), suggest_mapping and mapping_problems (which column is what), detect_date_format
(the date format, which the person chooses when the data cannot decide), and parse_file (every row, or every error).
"""

import codecs
import csv
import io
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import date

from northstar import locales, money
from northstar.balances import clean_note
from northstar.errors import ValidationError

MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 20_000
DELIMITERS = (",", ";", "\t")
SNIFFED_RECORDS = 50


class CsvError(ValidationError):
    """The file as a whole cannot be used."""


@dataclass(frozen=True)
class RowError:
    """One thing wrong in one place. `record` is the record number (the header is 1), or None when it is about the whole
    file. `column` is the zero-based column, or None."""
    record: int | None
    column: int | None
    message: str


# -- the file --

@dataclass(frozen=True)
class Record:
    number: int            # the header is record 1, and a quoted multiline record counts once
    cells: list[str]


@dataclass(frozen=True)
class Table:
    delimiter: str
    headers: list[str]
    rows: list[Record]     # data records only, blank ones left out

    def values(self, column: int) -> list[tuple[int, str]]:
        """(record number, cell) for a column, for the records that have it."""
        return [(row.number, row.cells[column]) for row in self.rows if column < len(row.cells)]


def decode(data: bytes) -> str:
    """UTF-8, with or without a byte order mark (an invisible marker some spreadsheet exports add, skipped silently)."""
    if len(data) > MAX_BYTES:
        raise CsvError("The file is larger than 2 MB.")
    if data.startswith(codecs.BOM_UTF8):
        data = data[len(codecs.BOM_UTF8):]
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise CsvError("The file is not UTF-8 text. In your spreadsheet, save or export it as CSV (UTF-8) and try again.") from None


def _records(text: str, delimiter: str, limit: int | None = None):
    """(number, cells) for each record, counting blank ones, stopping after `limit` records."""
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    for number, cells in enumerate(reader, start=1):
        yield number, cells
        if limit is not None and number >= limit:
            return


def _blank(cells: list[str]) -> bool:
    return all(not cell.strip() for cell in cells)


def sniff_delimiter(text: str) -> str:
    """Comma, semicolon or tab: whichever gives the same number of columns, at least two, on the most records."""
    best, best_score = ",", (0.0, 0)
    for delimiter in DELIMITERS:
        try:
            counts = [len(cells) for _, cells in _records(text, delimiter, SNIFFED_RECORDS) if not _blank(cells)]
        except csv.Error:
            continue
        if not counts:
            continue
        columns, how_many = Counter(counts).most_common(1)[0]
        score = (how_many / len(counts), columns)
        if columns >= 2 and score > best_score:
            best, best_score = delimiter, score
    return best


def read_table(data: bytes, delimiter: str | None = None) -> Table:
    """The file as a header and data records. Raises CsvError when it cannot be used at all; a record with the wrong number
    of fields is kept and reported by parse_file, never dropped."""
    text = decode(data)
    if delimiter is not None and delimiter not in DELIMITERS:
        raise CsvError("The delimiter must be a comma, a semicolon or a tab.")
    delimiter = delimiter or sniff_delimiter(text)
    header, rows = None, []
    try:
        for number, cells in _records(text, delimiter):
            if _blank(cells):
                continue
            if header is None:
                header = cells
            else:
                rows.append(Record(number, cells))
                if len(rows) > MAX_ROWS:
                    raise CsvError(f"The file has more than {locales.speaking().integer(MAX_ROWS)} rows. Split it and import the parts one at a time.")
    except csv.Error as error:
        raise CsvError(f"The file is not valid CSV: {error}.") from None
    if header is None:
        raise CsvError("The file is empty.")
    if len(header) < 2:
        raise CsvError("The file has only one column. A balance file needs at least a date and an amount. "
                       "If the columns are separated by something other than a comma, semicolon or tab, change that first.")
    if not rows:
        raise CsvError("The file has a header row but no data rows.")
    return Table(delimiter, header, rows)


# -- which column is which --

TARGETS = ("date", "balance", "note")


@dataclass(frozen=True)
class Mapping:
    """The zero-based column for each target, or None. Columns are identified by position, so duplicate and blank headers
    stay distinct. A column left out of the mapping is ignored."""
    date: int | None = None
    balance: int | None = None
    note: int | None = None

    def used(self) -> dict[str, int]:
        return {target: getattr(self, target) for target in TARGETS if getattr(self, target) is not None}


_ALIASES = {
    "date": {"date", "as of", "as of date", "asof", "balance date", "statement date", "day"},
    "balance": {"balance", "amount", "balance amount", "value", "closing balance", "ending balance", "end balance", "total"},
    "note": {"note", "notes", "memo", "comment", "comments", "description"},
}


def _normal(header: str) -> str:
    return " ".join(re.sub(r"[\W_]+", " ", header.casefold()).split())


def suggest_mapping(headers: list[str]) -> Mapping:
    """Prefill a target only when exactly one header clearly matches it. An ambiguous or unknown one is left for the person."""
    normal = [_normal(header) for header in headers]
    chosen = {}
    for target, aliases in _ALIASES.items():
        matches = [index for index, name in enumerate(normal) if name in aliases]
        chosen[target] = matches[0] if len(matches) == 1 else None
    return Mapping(**chosen)


def mapping_problems(mapping: Mapping, columns: int) -> list[str]:
    """Why this mapping cannot be used, in words, or an empty list. These are the reasons Continue stays disabled."""
    problems = []
    if mapping.date is None:
        problems.append("Choose which column is the Date.")
    if mapping.balance is None:
        problems.append("Choose which column is the Balance.")
    used = mapping.used()
    for target, column in used.items():
        if not 0 <= column < columns:
            problems.append(f"The {target} column does not exist in this file.")
    names = {"date": "Date", "balance": "Balance", "note": "Note"}
    seen: dict[int, str] = {}
    for target, column in used.items():
        if column in seen:
            problems.append(f"One column can't be both {names[seen[column]]} and {names[target]}. Choose a different column for one of them.")
        seen.setdefault(column, target)
    return problems


# -- dates --

DATE_FORMATS = ("YYYY-MM-DD", "MM/DD/YYYY", "DD/MM/YYYY", "MM/DD/YY", "DD/MM/YY", "DD.MM.YYYY", "DD.MM.YY",
                "Mon D, YYYY", "D Mon YYYY")

_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})", re.ASCII)
_SLASH4 = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})", re.ASCII)
_SLASH2 = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{2})", re.ASCII)
_DOT4 = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", re.ASCII)
_DOT2 = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{2})", re.ASCII)
_MONTH_FIRST = re.compile(r"([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})", re.ASCII)
_DAY_FIRST = re.compile(r"(\d{1,2})\s+([A-Za-z]+)\.?,?\s+(\d{4})", re.ASCII)

_MONTHS = {}
for _number, _names in enumerate((
        ("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"), ("may",), ("june", "jun"),
        ("july", "jul"), ("august", "aug"), ("september", "sep", "sept"), ("october", "oct"), ("november", "nov"),
        ("december", "dec")), start=1):
    for _name in _names:
        _MONTHS[_name] = _number


def _full_year(two_digits: int, today: date) -> int:
    """The most recent year not in the future that ends in these digits (in 2026: 99 is 1999, 26 is 2026, 45 is 1945)."""
    year = today.year - today.year % 100 + two_digits
    return year if year <= today.year else year - 100


def _calendar_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _read_date(fmt: str, text: str, today: date) -> date | None:
    """The calendar date `text` is in this format, or None. The future rule is not applied here."""
    text = text.strip()
    if fmt == "YYYY-MM-DD" and (m := _ISO.fullmatch(text)):
        return _calendar_date(int(m[1]), int(m[2]), int(m[3]))
    if fmt in ("MM/DD/YYYY", "DD/MM/YYYY", "DD.MM.YYYY") and (m := (_DOT4 if "." in fmt else _SLASH4).fullmatch(text)):
        month, day = (int(m[1]), int(m[2])) if fmt == "MM/DD/YYYY" else (int(m[2]), int(m[1]))
        return _calendar_date(int(m[3]), month, day)
    if fmt in ("MM/DD/YY", "DD/MM/YY", "DD.MM.YY") and (m := (_DOT2 if "." in fmt else _SLASH2).fullmatch(text)):
        month, day = (int(m[1]), int(m[2])) if fmt == "MM/DD/YY" else (int(m[2]), int(m[1]))
        return _calendar_date(_full_year(int(m[3]), today), month, day)
    if fmt == "Mon D, YYYY" and (m := _MONTH_FIRST.fullmatch(text)) and m[1].casefold() in _MONTHS:
        return _calendar_date(int(m[3]), _MONTHS[m[1].casefold()], int(m[2]))
    if fmt == "D Mon YYYY" and (m := _DAY_FIRST.fullmatch(text)) and m[2].casefold() in _MONTHS:
        return _calendar_date(int(m[3]), _MONTHS[m[2].casefold()], int(m[1]))
    return None


def parse_date(text: str, fmt: str, today: date) -> date:
    """A calendar date in the stated format, not in the future."""
    if fmt not in DATE_FORMATS:
        raise CsvError(f"{fmt!r} is not a date format Northstar reads.")
    if not text.strip():
        raise ValidationError("The date is blank.")
    parsed = _read_date(fmt, text, today)
    if parsed is None:
        raise ValidationError(f"{text.strip()!r} is not a date in the format {fmt}.")
    if parsed > today:
        raise ValidationError("The date can't be in the future.")
    return parsed


@dataclass(frozen=True)
class DateDetection:
    """`formats` are the formats under which every value is a real date. One means the column decides it (prefill it);
    several means the person must choose; none means `errors` say which records do not fit."""
    formats: list[str]
    errors: list[RowError] = field(default_factory=list)
    best: str | None = None        # when none fits every value, the one that fits most, so other errors are still found


def detect_date_format(cells: list[tuple[int, str]], today: date) -> DateDetection:
    """Per column, never per row. `cells` are (record number, text); blank cells are the row check's business."""
    present = [(record, text.strip()) for record, text in cells if text.strip()]
    fits = {fmt: [record for record, text in present if _read_date(fmt, text, today) is not None] for fmt in DATE_FORMATS}
    formats = [fmt for fmt in DATE_FORMATS if present and len(fits[fmt]) == len(present)]
    if formats or not present:
        return DateDetection(formats)
    # The format that fits the most values; on a tie the one that fits the first record, so the odd one out is a later row.
    best = max(DATE_FORMATS, key=lambda fmt: (len(fits[fmt]), present[0][0] in fits[fmt]))
    errors = []
    for record, text in present:
        if record in fits[best]:
            continue
        if any(_read_date(fmt, text, today) is not None for fmt in DATE_FORMATS):
            errors.append(RowError(record, None, f"{text!r} is in a different date format from the rest of the column."))
        else:
            errors.append(RowError(record, None, f"{text!r} is not a date in any format Northstar reads."))
    return DateDetection([], errors, best if fits[best] else None)


# -- amounts --

_GROUP_SPACES = "    "
_MINUS = "-−"


def _number(group: str | None, decimal: str, minor_units: int = 2) -> re.Pattern:
    tail = rf"(?:{re.escape(decimal)}\d{{1,{minor_units}}})?" if minor_units else ""
    head = rf"(?:\d{{1,3}}(?:{group}\d{{3}})+|\d+)" if group else r"\d+"
    return re.compile(head + tail, re.ASCII)


# Each format: the character that groups thousands (a regex, or None) and the decimal mark.
NUMBER_FORMATS = {
    "1,234.56": (",", "."),
    "1.234,56": (r"\.", ","),
    "1 234,56": (f"[{_GROUP_SPACES}]", ","),
    "1234.56": (None, "."),
    "1234,56": (None, ","),
}


@dataclass(frozen=True)
class Amount:
    cents: int
    symbol: str | None      # the currency symbol the cell carried, if any


def _is_symbol(char: str) -> bool:
    return unicodedata.category(char) == "Sc"


def _split_amount(text: str) -> tuple[bool, str | None, str]:
    """(negative, currency symbol, the number itself), or a ValidationError. Accepts a minus (ASCII or Unicode) before
    or after the symbol, parentheses for negative, and a symbol before or after the number."""
    s = text.strip()
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1].strip()
    symbol = None
    if s and s[0] in _MINUS:
        if negative:
            raise ValidationError(f"{text.strip()!r} uses both parentheses and a minus sign.")
        negative, s = True, s[1:].lstrip()
    if s and _is_symbol(s[0]):
        symbol, s = s[0], s[1:].lstrip()
        if s and s[0] in _MINUS:
            if negative:
                raise ValidationError(f"{text.strip()!r} has two minus signs.")
            negative, s = True, s[1:].lstrip()
    elif s and _is_symbol(s[-1]):
        symbol, s = s[-1], s[:-1].rstrip()
    return negative, symbol, s


def _amount_matches(core: str, minor_units: int = 2) -> list[str]:
    return [name for name, (group, decimal) in NUMBER_FORMATS.items() if _number(group, decimal, minor_units).fullmatch(core)]


def _to_cents(negative: bool, core: str, number_format: str, minor_units: int = 2) -> int:
    group, decimal = NUMBER_FORMATS[number_format]
    digits = re.sub(group, "", core) if group else core
    return money.parse_amount(("-" if negative else "") + digits.replace(decimal, "."), minor_units)


def parse_amount(text: str, number_format: str, minor_units: int = 2) -> Amount:
    """An amount in integer minor units, never through floating point. Blank is an error, zero is valid, signs are kept as typed."""
    if number_format not in NUMBER_FORMATS:
        raise CsvError(f"{number_format!r} is not a number format Northstar reads.")
    if not text.strip():
        raise ValidationError("The amount is blank.")
    negative, symbol, core = _split_amount(text)
    if not _number(*NUMBER_FORMATS[number_format], minor_units).fullmatch(core):
        raise ValidationError(f"{text.strip()!r} is not an amount in the format {number_format}. "
                              f"Use at most {minor_units} decimal places; amounts are never rounded.")
    return Amount(_to_cents(negative, core, number_format, minor_units), symbol)


@dataclass(frozen=True)
class NumberDetection:
    """Formats under which every value fits; with three decimals they may give different amounts."""
    formats: list[str]
    errors: list[RowError] = field(default_factory=list)
    best: str | None = None        # when none fits every value, the one that fits most, so other errors are still found


def detect_number_formats(cells: list[tuple[int, str]], minor_units: int = 2) -> NumberDetection:
    """Per column, never per row: a column that mixes formats (1,234.50 with 1.234,50) is an error naming the records."""
    present = []
    errors = []
    for record, text in cells:
        if not text.strip():
            continue
        try:
            _, _, core = _split_amount(text)
        except ValidationError as error:
            errors.append(RowError(record, None, str(error)))
            continue
        present.append((record, text.strip(), _amount_matches(core, minor_units)))
    if errors:
        return NumberDetection([], errors)
    formats = [name for name in NUMBER_FORMATS if present and all(name in matches for _, _, matches in present)]
    if formats or not present:
        return NumberDetection(formats)
    # The format that fits the most values; on a tie the one that fits the first record, so the odd one out is a later row.
    best = max(NUMBER_FORMATS, key=lambda name: (sum(name in matches for _, _, matches in present), name in present[0][2]))
    for record, text, matches in present:
        if best in matches:
            continue
        if matches:
            errors.append(RowError(record, None, f"{text!r} is in a different number format from the rest of the column."))
        else:
            errors.append(RowError(record, None, f"{text!r} is not an amount. Use at most {minor_units} decimal places."))
    return NumberDetection([], errors, best if any(best in matches for _, _, matches in present) else None)


# -- the whole file --

@dataclass(frozen=True)
class ParsedRow:
    record: int
    date: date
    cents: int
    note: str | None        # None when the cell is blank, which later steps read as "keep the existing note"


@dataclass(frozen=True)
class ParseResult:
    """Every row, or every error: when there is any error there are no rows, so nothing invalid is ever dropped silently.
    `unsupported_currencies` is retained as an empty field for older API consumers."""
    rows: list[ParsedRow]
    errors: list[RowError]
    date_format: str | None = None
    unsupported_currencies: list[str] = field(default_factory=list)
    number_format: str | None = None


def number_choices(cells: list[tuple[int, str]], minor_units: int) -> list[str]:
    """One choice per interpretation of the whole column, not one per equivalent spelling convention."""
    detection = detect_number_formats(cells, minor_units)
    seen, choices = set(), []
    for fmt in detection.formats:
        try:
            values = tuple(parse_amount(text, fmt, minor_units).cents for _, text in cells if text.strip())
        except ValidationError:
            # The review reports limits and malformed values; the mapping can still proceed to it.
            return detection.formats[:1] if minor_units < 3 else detection.formats
        if values not in seen:
            choices.append(fmt)
            seen.add(values)
    return choices


def canonical_amounts(table: Table, mapping: Mapping) -> bool:
    """Recognise the existing Northstar CSV contract, independently of filename and user locale."""
    return table.headers == ["Account ID", "Account Name", "Balance Date", "Balance Amount"] and mapping.date == 2 and mapping.balance == 3


def number_previews(samples: list[str], minor_units: int) -> dict[str, int | None]:
    """Read the first sample in each file convention; invalid readings are left for the review's row errors."""
    previews = {}
    for fmt in NUMBER_FORMATS:
        try:
            previews[fmt] = parse_amount(samples[0], fmt, minor_units).cents if samples else None
        except ValidationError:
            previews[fmt] = None
    return previews


def parse_file(table: Table, mapping: Mapping, date_format: str | None, today: date,
               minor_units: int = 2, number_format: str | None = None) -> ParseResult:
    """Check the whole file and return every row, or every blocking error with its record number. `date_format` is the one
    the person chose; when it is None the column has to decide it by itself."""
    problems = mapping_problems(mapping, len(table.headers))
    if problems:
        raise CsvError(" ".join(problems))
    errors: list[RowError] = []
    width = len(table.headers)
    good = []
    for row in table.rows:
        if len(row.cells) != width:
            errors.append(RowError(row.number, None, f"This record has {locales.speaking().integer(len(row.cells))} fields and the header has {locales.speaking().integer(width)}."))
        else:
            good.append(row)
    column = lambda index: [(row.number, row.cells[index]) for row in good]

    # A column that cannot settle its format is reported, and read with the format that fits most of it, so the other
    # problems in the file are listed too and the person is not sent round again for each one.
    chosen = decided = date_format
    reported_dates: set[int | None] = set()
    if chosen is None:
        detection = detect_date_format(column(mapping.date), today)
        errors += [RowError(e.record, mapping.date, e.message) for e in detection.errors]
        reported_dates = {e.record for e in detection.errors}
        if len(detection.formats) == 1:
            chosen = decided = detection.formats[0]
        elif len(detection.formats) > 1:
            errors.append(RowError(None, mapping.date,
                                   "The date format can't be told from the data. Choose one of: " + ", ".join(detection.formats) + "."))
        else:
            chosen = detection.best
    elif chosen not in DATE_FORMATS:
        raise CsvError(f"{chosen!r} is not a date format Northstar reads.")

    reported_amounts = set()
    if canonical_amounts(table, mapping):
        if number_format not in (None, "1234.56"):
            raise CsvError("Northstar CSV amounts use a decimal point and no thousands separators.")
        number_format = "1234.56"
    if number_format is None:
        amounts = detect_number_formats(column(mapping.balance), minor_units)
        errors += [RowError(e.record, mapping.balance, e.message) for e in amounts.errors]
        reported_amounts = {e.record for e in amounts.errors}
        choices = number_choices(column(mapping.balance), minor_units)
        if len(choices) > 1:
            errors.append(RowError(None, mapping.balance, "The number format can't be told from the data. Choose the number style."))
        number_format = choices[0] if choices else amounts.best
    elif number_format not in NUMBER_FORMATS:
        raise CsvError(f"{number_format!r} is not a number format Northstar reads.")

    parsed: list[ParsedRow] = []
    for row in good:
        failed = False
        day = cents = None
        if chosen is not None:
            try:
                day = parse_date(row.cells[mapping.date], chosen, today)
            except ValidationError as error:
                if row.number not in reported_dates:
                    errors.append(RowError(row.number, mapping.date, str(error)))
                failed = True
        elif not row.cells[mapping.date].strip():       # no format to read it with, but a blank is wrong whatever it is
            errors.append(RowError(row.number, mapping.date, "The date is blank."))
            failed = True
        if number_format is None and not row.cells[mapping.balance].strip():
            errors.append(RowError(row.number, mapping.balance, "The amount is blank."))
            failed = True
        if number_format is not None:
            try:
                amount = parse_amount(row.cells[mapping.balance], number_format, minor_units)
                cents = amount.cents
            except ValidationError as error:
                if row.number not in reported_amounts:
                    errors.append(RowError(row.number, mapping.balance, str(error)))
                failed = True
        note = None
        if mapping.note is not None:
            try:
                note = clean_note(row.cells[mapping.note])
            except ValidationError as error:
                errors.append(RowError(row.number, mapping.note, str(error)))
                failed = True
        if not failed and day is not None and cents is not None:
            parsed.append(ParsedRow(row.number, day, cents, note))

    errors.sort(key=lambda e: (e.record is not None, e.record or 0, e.column is None, e.column or 0))
    return ParseResult([] if errors else parsed, errors, decided, [], number_format)
