import pytest

from northstar.errors import ValidationError
from northstar.money import MAX_CENTS, cents_to_input, format_cents, parse_cents


@pytest.mark.parametrize("text, cents", [
    ("1234.56", 123456),
    ("1,234.56", 123456),
    ("$1,234.56", 123456),
    ("  $25  ", 2500),
    ("25", 2500),
    ("25.5", 2550),
    ("0", 0),
    ("0.00", 0),
    (".5", 50),
    ("-25", -2500),
    ("-25.00", -2500),
    ("-$25.00", -2500),
    ("-0", 0),
    ("1,000,000.01", 100000001),
    ("0.07", 7),
])
def test_parse_cents(text, cents):
    assert parse_cents(text) == cents


@pytest.mark.parametrize("text", [
    "", "   ", None, "abc", "1.234", "5.", "--5", "$-5", "1e3", "1,23", "12,34.50", "1 2 3 x",
    "$", "-", ".", "١٢٣",  # Arabic-Indic digits
    "1.2.3", "25%", "(25.00)",
])
def test_parse_cents_rejects_junk(text):
    with pytest.raises(ValidationError, match="Enter an amount"):
        parse_cents(text)


def test_parse_cents_rejects_huge_amounts():
    assert parse_cents("99,999,999,999.99") == MAX_CENTS
    with pytest.raises(ValidationError, match="too large"):
        parse_cents("100,000,000,000.00")
    with pytest.raises(ValidationError, match="too large"):
        parse_cents("9" * 40)


def test_no_floating_point_rounding_surprises():
    # 0.1 + 0.2 style trouble can't happen: parsing is integer arithmetic.
    assert parse_cents("0.29") == 29
    assert parse_cents("1.15") == 115


@pytest.mark.parametrize("cents, shown", [
    (0, "$0.00"), (7, "$0.07"), (2500, "$25.00"), (123456, "$1,234.56"),
    (100000001, "$1,000,000.01"), (-2500, "-$25.00"), (-1, "-$0.01"),
])
def test_format_cents(cents, shown):
    assert format_cents(cents) == shown


@pytest.mark.parametrize("cents", [0, 7, 2500, 123456, -2500, -1, MAX_CENTS, -MAX_CENTS])
def test_input_text_round_trips(cents):
    assert parse_cents(cents_to_input(cents)) == cents
