"""Reading a balance CSV file: encoding, delimiter, records, mapping, dates, amounts, currency and the whole-file check.
Synthetic data only."""

import itertools
import logging
import re
from datetime import date
from decimal import Decimal

import pytest

from northstar import csvparse
from northstar.csvparse import (CsvError, Mapping, ParseResult, RowError, detect_date_format, detect_number_formats,
                                mapping_problems, parse_amount, parse_date, parse_file, read_table, suggest_mapping)
from northstar.errors import ValidationError

TODAY = date(2026, 10, 30)
BASIC = Mapping(date=0, balance=1)


def table(text, **kw):
    return read_table(text.encode("utf-8"), **kw)


def result(text, mapping=BASIC, date_format=None, today=TODAY):
    return parse_file(table(text), mapping, date_format, today)


def messages(parsed: ParseResult):
    return [(e.record, e.column, e.message) for e in parsed.errors]


# -- the file: encoding and size --

def test_utf8_is_read_with_or_without_a_byte_order_mark():
    plain = read_table("Date,Balance\n2026-01-31,10.00\n".encode("utf-8"))
    marked = read_table(b"\xef\xbb\xbf" + "Date,Balance\n2026-01-31,10.00\n".encode("utf-8"))
    assert plain.headers == marked.headers == ["Date", "Balance"]           # the marker is not part of the first header


def test_non_ascii_text_survives():
    assert table("Date,Note\n2026-01-31,café 日本\n").rows[0].cells[1] == "café 日本"


@pytest.mark.parametrize("data", ["Date,Balance\n2026-01-31,café\n".encode("latin-1"), "Date,Balance\n".encode("utf-16")])
def test_other_encodings_are_refused_with_a_message_that_says_what_to_do(data):
    with pytest.raises(CsvError, match="not UTF-8 text.*CSV \\(UTF-8\\)"):
        read_table(data)


def test_a_file_over_two_megabytes_is_refused():
    with pytest.raises(CsvError, match="larger than 2 MB"):
        read_table(b"a," * (csvparse.MAX_BYTES // 2 + 1))


# -- the file: delimiter --

@pytest.mark.parametrize("delimiter, name", [(",", "comma"), (";", "semicolon"), ("\t", "tab")])
def test_the_delimiter_is_sniffed_and_returned(delimiter, name):
    found = table(delimiter.join(["Date", "Balance"]) + "\n" + delimiter.join(["2026-01-31", "10.00"]) + "\n")
    assert found.delimiter == delimiter and found.headers == ["Date", "Balance"], name


def test_a_semicolon_file_with_decimal_commas_is_not_read_as_commas():
    found = table("Date;Balance\n2026-01-31;1.234,56\n2026-02-28;2.000,00\n")
    assert found.delimiter == ";" and found.rows[0].cells == ["2026-01-31", "1.234,56"]


def test_a_delimiter_inside_quotes_is_not_a_delimiter():
    found = table('Date,Note\n2026-01-31,"one, two; three"\n')
    assert found.delimiter == "," and found.rows[0].cells[1] == "one, two; three"


def test_the_delimiter_can_be_overridden_and_a_bad_override_is_refused():
    assert table("Date;Balance\n2026-01-31;1\n", delimiter=";").headers == ["Date", "Balance"]
    with pytest.raises(CsvError, match="comma, a semicolon or a tab"):
        table("a|b\n1|2\n", delimiter="|")


def test_a_file_with_one_column_is_refused_rather_than_read_as_one_usable_column():
    with pytest.raises(CsvError, match="only one column"):
        table("Date|Balance\n2026-01-31|10\n")


# -- the file: records --

def test_records_are_numbered_from_the_header_and_a_multiline_record_counts_once():
    found = table('Date,Note\n2026-01-31,"line one\nline two"\n2026-02-28,x\n')
    assert [row.number for row in found.rows] == [2, 3]
    assert found.rows[0].cells[1] == "line one\nline two"


def test_blank_rows_are_ignored_but_keep_their_number():
    found = table("Date,Balance\n2026-01-31,1\n\n , \n2026-02-28,2\n")
    assert [row.number for row in found.rows] == [2, 5]


def test_duplicate_and_blank_headers_are_kept_distinct_by_position():
    found = table("Amount,,Amount\n1,2,3\n")
    assert found.headers == ["Amount", "", "Amount"]


def test_a_file_with_no_rows_or_nothing_is_refused():
    with pytest.raises(CsvError, match="header row but no data rows"):
        table("Date,Balance\n\n\n")
    with pytest.raises(CsvError, match="empty"):
        table("\n\n")


def test_twenty_thousand_rows_are_allowed_and_one_more_is_not():
    body = lambda n: "Date,Balance\n" + "2026-01-31,1\n" * n
    assert len(table(body(csvparse.MAX_ROWS)).rows) == 20_000
    with pytest.raises(CsvError, match="more than 20,000 rows"):
        table(body(csvparse.MAX_ROWS + 1))


def test_a_cell_too_large_for_the_csv_reader_is_a_file_error_not_a_crash():
    with pytest.raises(CsvError, match="not valid CSV"):
        table('Date,Note\n2026-01-31,"' + "x" * 200_000 + '"\n')


# -- which column is which --

def test_clear_headers_are_prefilled_whatever_their_case_or_punctuation():
    assert suggest_mapping(["Statement Date", "Closing_Balance", "Memo", "CCY"]) == Mapping(0, 1, 2)
    assert suggest_mapping(["AS OF", "Balance ($)"]) == Mapping(date=0, balance=1)


def test_unknown_ambiguous_and_doubly_claimed_headers_are_left_for_the_person():
    assert suggest_mapping(["Posted on", "Stuff"]) == Mapping()
    assert suggest_mapping(["Date", "Amount", "Amount"]) == Mapping(date=0)                # two columns want Balance
    assert suggest_mapping(["Date", "Balance", "Value"]) == Mapping(date=0)                # two aliases for the same target
    assert suggest_mapping(["", "", "Date"]) == Mapping(date=2)


def test_a_valid_mapping_has_no_problems_and_every_problem_is_explained():
    assert mapping_problems(Mapping(0, 1, 2), 4) == []
    assert mapping_problems(Mapping(), 3) == ["Choose which column is the Date.", "Choose which column is the Balance."]
    assert mapping_problems(Mapping(date=0, balance=0), 2) == [
        "One column can't be both Date and Balance. Choose a different column for one of them."]
    assert mapping_problems(Mapping(0, 1, note=7), 2) == ["The note column does not exist in this file."]
    assert mapping_problems(Mapping(0, 1, note=1), 2)[0].startswith("One column can't be both Balance and Note")


# -- dates --

@pytest.mark.parametrize("fmt, text, expected", [
    ("YYYY-MM-DD", "2026-01-31", date(2026, 1, 31)),
    ("MM/DD/YYYY", "01/31/2026", date(2026, 1, 31)),
    ("MM/DD/YYYY", "1/5/2026", date(2026, 1, 5)),
    ("DD/MM/YYYY", "31/01/2026", date(2026, 1, 31)),
    ("DD/MM/YYYY", "05/01/2026", date(2026, 1, 5)),
    ("MM/DD/YY", "01/31/26", date(2026, 1, 31)),
    ("DD/MM/YY", "31/01/26", date(2026, 1, 31)),
    ("DD.MM.YYYY", "31.10.2025", date(2025, 10, 31)),
    ("DD.MM.YYYY", "5.1.2026", date(2026, 1, 5)),
    ("DD.MM.YY", "31.10.25", date(2025, 10, 31)),
    ("Mon D, YYYY", "Oct 31, 2025", date(2025, 10, 31)),
    ("Mon D, YYYY", "october 31, 2025", date(2025, 10, 31)),
    ("Mon D, YYYY", "OCT. 3, 2025", date(2025, 10, 3)),
    ("Mon D, YYYY", "Sept 30, 2025", date(2025, 9, 30)),
    ("D Mon YYYY", "31 Oct 2025", date(2025, 10, 31)),
    ("D Mon YYYY", "3 September, 2025", date(2025, 9, 3)),
    ("YYYY-MM-DD", "  2026-01-31  ", date(2026, 1, 31)),
])
def test_every_date_format_reads_its_dates(fmt, text, expected):
    assert parse_date(text, fmt, TODAY) == expected


@pytest.mark.parametrize("fmt, text", [
    ("YYYY-MM-DD", "2026-02-30"), ("YYYY-MM-DD", "2026-1-5"), ("YYYY-MM-DD", "01/31/2026"),
    ("MM/DD/YYYY", "13/01/2026"), ("DD/MM/YYYY", "01/13/2026"), ("MM/DD/YYYY", "2/29/2025"),
    ("MM/DD/YY", "01/31/2026"), ("MM/DD/YYYY", "01/31/26"), ("DD.MM.YYYY", "31/10/2025"),
    ("Mon D, YYYY", "Smarch 3, 2026"), ("Mon D, YYYY", "31 Oct 2025"), ("D Mon YYYY", "Oct 31, 2025"),
    ("YYYY-MM-DD", "0000-01-01"), ("YYYY-MM-DD", "٢٠٢٦-٠١-٣١"),
])
def test_dates_that_do_not_fit_the_format_or_the_calendar_are_refused(fmt, text):
    with pytest.raises(ValidationError, match="not a date in the format"):
        parse_date(text, fmt, TODAY)


def test_a_future_date_and_a_blank_date_are_refused():
    with pytest.raises(ValidationError, match="can't be in the future"):
        parse_date("2026-10-31", "YYYY-MM-DD", TODAY)
    assert parse_date("2026-10-30", "YYYY-MM-DD", TODAY) == TODAY                        # today itself is fine
    with pytest.raises(ValidationError, match="blank"):
        parse_date("  ", "YYYY-MM-DD", TODAY)


@pytest.mark.parametrize("today, two_digits, year", [
    (date(2026, 10, 30), "99", 1999), (date(2026, 10, 30), "26", 2026), (date(2026, 10, 30), "45", 1945),
    (date(2026, 10, 30), "00", 2000), (date(2026, 10, 30), "27", 1927),
    (date(2005, 6, 1), "05", 2005), (date(2005, 6, 1), "06", 1906),
    (date(2100, 1, 1), "00", 2100), (date(2100, 1, 1), "99", 2099),
])
def test_two_digit_years_use_the_most_recent_year_not_in_the_future(today, two_digits, year):
    assert parse_date(f"01/01/{two_digits}", "MM/DD/YY", today).year == year


def test_a_two_digit_year_that_lands_on_a_future_date_this_year_is_still_refused():
    with pytest.raises(ValidationError, match="can't be in the future"):
        parse_date("12/31/26", "MM/DD/YY", TODAY)


def cells(*values):
    return [(number, value) for number, value in enumerate(values, start=2)]


@pytest.mark.parametrize("values, formats", [
    (["2026-01-31", "2026-02-28"], ["YYYY-MM-DD"]),
    (["01/31/2026", "02/28/2026"], ["MM/DD/YYYY"]),                          # a part above 12 decides the order
    (["31/01/2026", "28/02/2026"], ["DD/MM/YYYY"]),
    (["01/02/2026", "03/04/2026"], ["MM/DD/YYYY", "DD/MM/YYYY"]),             # both orders work: the person must choose
    (["01/02/26", "03/04/26"], ["MM/DD/YY", "DD/MM/YY"]),
    (["31.01.2026", "01.02.2026"], ["DD.MM.YYYY"]),                          # dotted dates are always day first
    (["31.01.26"], ["DD.MM.YY"]),
    (["Oct 31, 2025", "Nov 30, 2025"], ["Mon D, YYYY"]),
    (["31 Oct 2025"], ["D Mon YYYY"]),
    (["2026-01-31", "", "  "], ["YYYY-MM-DD"]),                              # blanks are the row check's business
])
def test_the_column_decides_the_date_format_or_leaves_the_choice(values, formats):
    detection = detect_date_format(cells(*values), TODAY)
    assert detection.formats == formats and detection.errors == []


def test_a_column_with_mixed_date_formats_is_an_error_naming_the_records():
    detection = detect_date_format(cells("2026-01-31", "01/31/2026", "2026-02-28", "next tuesday"), TODAY)
    assert detection.formats == []
    assert [(e.record, e.message) for e in detection.errors] == [
        (3, "'01/31/2026' is in a different date format from the rest of the column."),
        (5, "'next tuesday' is not a date in any format Northstar reads.")]


def test_a_column_with_no_dates_at_all_has_no_candidates_and_no_error_of_its_own():
    assert detect_date_format(cells("", " "), TODAY) == csvparse.DateDetection([])


# -- amounts --

@pytest.mark.parametrize("fmt, text, cents", [
    ("1,234.56", "1,234.56", 123456), ("1,234.56", "1,234,567.89", 123456789), ("1,234.56", "12.5", 1250),
    ("1,234.56", "1234", 123400), ("1,234.56", "0.05", 5), ("1,234.56", "0", 0), ("1,234.56", "0.00", 0),
    ("1.234,56", "1.234,56", 123456), ("1.234,56", "1.234", 123400), ("1.234,56", "12,5", 1250), ("1.234,56", "1.234.567,89", 123456789),
    ("1 234,56", "1 234,56", 123456), ("1 234,56", "1 234,56", 123456), ("1 234,56", "1 234,56", 123456),
    ("1 234,56", "1 234,56", 123456), ("1 234,56", "1 234", 123400),
    ("1234.56", "1234.56", 123456), ("1234.56", "5", 500),
    ("1234,56", "1234,56", 123456), ("1234,56", "5,5", 550),
])
def test_every_number_format_reads_its_amounts_into_integer_cents(fmt, text, cents):
    amount = parse_amount(text, fmt)
    assert amount.cents == cents and isinstance(amount.cents, int)


@pytest.mark.parametrize("text, cents, symbol", [
    ("-5.00", -500, None), ("−5.00", -500, None), ("(5.00)", -500, None), ("-$5.00", -500, "$"),
    ("$-5.00", -500, "$"), ("($5.00)", -500, "$"), ("$5.00", 500, "$"), ("5.00 $", 500, "$"), ("  $ 5.00 ", 500, "$"),
    ("-0.00", 0, None), ("(0)", 0, None), ("€5.00", 500, "€"), ("5.00€", 500, "€"), ("£1,000.00", 100000, "£"),
    ("¥100", 10000, "¥"), ("-€5", -500, "€"), ("€-5", -500, "€"),
])
def test_signs_parentheses_and_currency_symbols(text, cents, symbol):
    assert parse_amount(text, "1,234.56") == csvparse.Amount(cents, symbol)


@pytest.mark.parametrize("text", [
    "", "   ", ".5", "5.", "1.234", "5.123", "1,23,456", "1,2345", "12,34.56", "--5", "-(5)", "(-5)", "((5))", "5-", "$$5",
    "$5$", "abc", "5 dollars", "1e3", "0x10", "٣٠", "1..2", "$", "-",
])
def test_things_that_are_not_amounts_are_refused(text):
    with pytest.raises(ValidationError):
        parse_amount(text, "1,234.56")


def test_the_blank_amount_has_its_own_message_and_zero_is_valid():
    with pytest.raises(ValidationError, match="amount is blank"):
        parse_amount("  ", "1234.56")
    assert parse_amount("0", "1234.56").cents == 0


def test_the_largest_amount_is_the_same_limit_as_everywhere_else():
    assert parse_amount("99999999999.99", "1234.56").cents == 99_999_999_999_99
    with pytest.raises(ValidationError, match="too large"):
        parse_amount("100000000000.00", "1234.56")


def test_an_unknown_number_format_is_a_programming_error():
    with pytest.raises(CsvError):
        parse_amount("5", "1'234.56")


def test_two_decimal_formats_have_no_conflicting_interpretations():
    """With at most two decimal places, every string that fits more than one
    format means the same amount in all of them. Checked over every string of up to six characters from this alphabet."""
    disagreements = []
    for length in range(1, 7):
        for chars in itertools.product("0125.,  ", repeat=length):
            core = "".join(chars)
            values = {csvparse._to_cents(False, core, name) for name in csvparse._amount_matches(core)}
            if len(values) > 1:
                disagreements.append(core)
    assert disagreements == []


def test_three_decimals_allow_conflicting_interpretations():
    """At three decimals "1,234" is 1234 or 1.234, and the number format choice must return."""
    patterns = {name: csvparse._number(group, decimal, 3) for name, (group, decimal) in csvparse.NUMBER_FORMATS.items()}
    readings = set()
    for name, pattern in patterns.items():
        if pattern.fullmatch("1,234"):
            group, decimal = csvparse.NUMBER_FORMATS[name]
            digits = re.sub(group, "", "1,234") if group else "1,234"
            readings.add(Decimal(digits.replace(decimal, ".")))
    assert readings == {Decimal("1234"), Decimal("1.234")}


@pytest.mark.parametrize("values, formats", [
    (["1,234.50", "10.00"], ["1,234.56"]),
    (["1.234,50", "10,00"], ["1.234,56"]),
    (["1 234,50", "10,00"], ["1 234,56"]),
    (["1234.50", "10.00"], ["1,234.56", "1234.56"]),
    (["1234,50", "10,5"], ["1.234,56", "1 234,56", "1234,56"]),     # three formats fit, and agree on every value
    (["1,234", "5"], ["1,234.56"]),                         # "1,234" can only be 1234: as a decimal it has three places
    (["1.234", "5"], ["1.234,56"]),                         # and "1.234" can only be 1234 in a dot-grouped file
    (["-5", "(10)", "$20"], list(csvparse.NUMBER_FORMATS)),
    (["1,234.50", ""], ["1,234.56"]),
])
def test_the_column_decides_which_number_formats_fit(values, formats):
    detection = detect_number_formats(cells(*values))
    assert detection.formats == formats and detection.errors == []


def test_the_formats_that_remain_agree_on_every_value_of_the_column():
    detection = detect_number_formats(cells("1234", "-5", "$20"))
    assert len(detection.formats) == 5
    for text in ("1234", "-5", "$20"):
        assert len({parse_amount(text, name).cents for name in detection.formats}) == 1


def test_a_column_that_mixes_number_formats_is_an_error_naming_the_records():
    detection = detect_number_formats(cells("1,234.50", "1.234,50", "10.00", "1,234", "oops"))
    assert detection.formats == []
    assert [(e.record, e.message) for e in detection.errors] == [
        (3, "'1.234,50' is in a different number format from the rest of the column."),
        (6, "'oops' is not an amount. Use at most 2 decimal places.")]


def test_a_value_with_two_minus_signs_is_an_error_not_a_crash():
    detection = detect_number_formats(cells("10.00", "--5"))
    assert detection.formats == [] and [e.record for e in detection.errors] == [3]


# -- the whole file --

def test_a_file_with_only_a_date_and_a_balance_is_read_in_full():
    parsed = result("Date,Balance\n2026-01-31,1234.50\n2026-02-28,-20\n")
    assert parsed.errors == [] and parsed.date_format == "YYYY-MM-DD"
    assert [(r.record, r.date, r.cents, r.note) for r in parsed.rows] == [
        (2, date(2026, 1, 31), 123450, None), (3, date(2026, 2, 28), -2000, None)]


def test_a_european_file_is_read_with_its_delimiter_dates_and_numbers():
    parsed = result("Datum;Saldo;Notiz\n31.01.2026;1.234,50;erster\n28.02.2026;(20,00);\n", Mapping(0, 1, 2))
    assert parsed.errors == [] and parsed.date_format == "DD.MM.YYYY"
    assert [(r.date, r.cents, r.note) for r in parsed.rows] == [(date(2026, 1, 31), 123450, "erster"), (date(2026, 2, 28), -2000, None)]


def test_ignored_columns_have_no_effect_and_the_columns_can_be_in_any_order():
    parsed = result("Junk,Balance,More junk,Date\nzzz,10.00,???,2026-01-31\n", Mapping(date=3, balance=1))
    assert [(r.date, r.cents) for r in parsed.rows] == [(date(2026, 1, 31), 1000)]


def test_dates_the_data_cannot_decide_need_a_choice_and_a_choice_resolves_them():
    text = "Date,Balance\n01/02/2026,10\n03/04/2026,20\n"
    undecided = result(text)
    assert undecided.rows == [] and undecided.date_format is None
    assert messages(undecided) == [(None, 0, "The date format can't be told from the data. Choose one of: MM/DD/YYYY, DD/MM/YYYY.")]
    assert [r.date for r in result(text, date_format="MM/DD/YYYY").rows] == [date(2026, 1, 2), date(2026, 3, 4)]
    assert [r.date for r in result(text, date_format="DD/MM/YYYY").rows] == [date(2026, 2, 1), date(2026, 4, 3)]


def test_a_chosen_date_format_that_does_not_fit_is_reported_row_by_row():
    parsed = result("Date,Balance\n2026-01-31,1\n01/31/2026,2\n", date_format="YYYY-MM-DD")
    assert parsed.rows == [] and messages(parsed) == [(3, 0, "'01/31/2026' is not a date in the format YYYY-MM-DD.")]


def test_every_blocking_error_is_listed_with_its_record_number_and_no_row_is_dropped():
    text = ('Date,Balance,Note\n'
            '2026-01-31,10.00,fine\n'          # 2: good
            '2026-02-30,20.00,x\n'             # 3: not a calendar date
            '2026-03-31,abc,y\n'               # 4: not an amount
            '2026-04-30,,z\n'                  # 5: blank amount
            '2027-01-31,5.00,future\n'         # 6: the future
            '2026-05-31,1.00\n'                # 7: a field short
            '\n'                               # 8: blank, ignored
            '2026-06-30,2.00,' + 'n' * 501 + '\n')   # 9: note too long
    parsed = result(text, Mapping(0, 1, 2))
    assert parsed.rows == []                                         # all rows or the errors, never a partial result
    assert [(e.record, e.column) for e in parsed.errors] == [(3, 0), (4, 1), (5, 1), (6, 0), (7, None), (9, 2)]
    assert "future" in parsed.errors[3].message and "3 fields" not in parsed.errors[4].message
    assert parsed.errors[4].message == "This record has 2 fields and the header has 3."


def test_errors_in_a_file_with_multiline_records_point_at_the_right_record():
    parsed = result('Date,Note,Balance\n2026-01-31,"a\nb",1\n2026-02-30,x,2\n', Mapping(0, 2, 1))
    assert [e.record for e in parsed.errors] == [3]


def test_a_blank_date_is_an_error_even_when_the_column_cannot_decide_a_format():
    parsed = result("Date,Balance\n,1\n,2\n")
    assert [(e.record, e.message) for e in parsed.errors] == [(2, "The date is blank."), (3, "The date is blank.")]


def test_a_blank_amount_is_an_error_even_when_no_value_can_decide_a_format():
    parsed = result("Date,Balance\n2026-01-31,\n2026-02-28, \n")
    assert [(e.record, e.message) for e in parsed.errors] == [(2, "The amount is blank."), (3, "The amount is blank.")]


def test_mixed_number_formats_in_the_balance_column_stop_the_file():
    parsed = result("Date,Balance\n2026-01-31,1.234\n2026-02-28,1,234\n")
    assert parsed.rows == [] and [e.record for e in parsed.errors] == [3]


def test_a_note_is_trimmed_and_blank_means_keep_what_is_there():
    parsed = result("Date,Balance,Note\n2026-01-31,1,  hello  \n2026-02-28,2,   \n", Mapping(0, 1, 2))
    assert [r.note for r in parsed.rows] == ["hello", None]


def test_duplicate_dates_are_not_this_modules_job():
    parsed = result("Date,Balance\n2026-01-31,1\n2026-01-31,1\n")
    assert len(parsed.rows) == 2 and parsed.errors == []


def test_a_bad_mapping_or_date_format_is_a_programming_error_not_a_row_error():
    with pytest.raises(CsvError, match="Choose which column is the Balance"):
        result("Date,Balance\n2026-01-31,1\n", Mapping(date=0))
    with pytest.raises(CsvError, match="not a date format"):
        result("Date,Balance\n2026-01-31,1\n", date_format="YYYY/MM/DD")


# -- currency --

def test_currency_columns_are_ignored_and_symbols_do_not_decide_currency():
    text = "Date,Balance,Currency\n2026-01-31,€1.00,EUR\n2026-02-28,£2.00,\n"
    mapping = suggest_mapping(["Date", "Balance", "Currency"])
    assert mapping == Mapping(0, 1)
    parsed = result(text, mapping)
    assert parsed.errors == []
    assert [row.cents for row in parsed.rows] == [100, 200]


# -- uploaded content is never logged --

def test_reading_a_file_writes_nothing_to_the_log(caplog):
    caplog.set_level(logging.DEBUG)
    result("Date,Balance,Note\n2026-01-31,secret-looking,private words\n2026-02-30,1,x\n", Mapping(0, 1, 2))
    assert caplog.records == []


def test_other_problems_are_still_listed_when_a_columns_format_is_mixed():
    text = 'Date,Balance\n2026-01-31,1.234\n2026-02-28,"1,234"\n2026-03-31,\n2026-04-30,€5\n'
    parsed = result(text)
    assert parsed.rows == []
    assert [(e.record, e.column) for e in parsed.errors] == [(3, 1), (4, 1)]    # mixed and blank; the symbol is accepted
    assert parsed.unsupported_currencies == []


def test_a_file_of_the_largest_size_is_read_in_full():
    rows = "".join(f"2026-01-{day:02d},{day}.50\n" for day in range(1, 29)) * (csvparse.MAX_ROWS // 28)
    parsed = result("Date,Balance\n" + rows)
    assert parsed.errors == [] and len(parsed.rows) == (csvparse.MAX_ROWS // 28) * 28
