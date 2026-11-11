"""A report's parameters: the date conventions, defaults and how they resolve, the rules, and reading a request. Synthetic data only."""

from datetime import date

import pytest

from northstar.reports import params
from northstar.reports.errors import ReportDefectError, ReportDefinitionError, ReportInputError
from northstar.reports.params import After, Literal, NotFuture, Offset, OnOrAfter, ParamDef, Today

TODAY = date(2026, 11, 11)


# -- shifting a date --

@pytest.mark.parametrize("start, years, months, days, expected", [
    (date(2026, 11, 11), -1, 0, 0, date(2025, 11, 11)),
    (date(2028, 2, 29), -1, 0, 0, date(2027, 2, 28)),             # the day the target year lacks becomes the month's last
    (date(2028, 2, 29), -4, 0, 0, date(2024, 2, 29)),
    (date(2026, 3, 31), 0, -1, 0, date(2026, 2, 28)),
    (date(2026, 1, 31), 0, 1, 0, date(2026, 2, 28)),
    (date(2026, 12, 31), 0, 2, 0, date(2027, 2, 28)),
    (date(2026, 1, 15), 0, -2, -15, date(2025, 10, 31)),          # months first (to 15 November), then days
])
def test_a_date_is_shifted_by_calendar_years_and_months_then_days(start, years, months, days, expected):
    assert params.shift(start, years, months, days) == expected


def test_a_shift_outside_the_calendar_is_refused():
    with pytest.raises(ValueError):
        params.shift(date(1, 1, 1), years=-1)


# -- the three date conventions --

def test_as_of_is_one_date_that_defaults_to_today_and_may_not_be_in_the_future():
    definition = params.as_of()
    assert [p.key for p in definition] == ["as_at"]
    assert params.resolve_defaults(definition, TODAY) == {"as_at": "2026-11-11"}
    assert params.read(definition, {"as_at": "2026-11-11"}, TODAY) == {"as_at": TODAY}
    with pytest.raises(ReportInputError) as error:
        params.read(definition, {"as_at": "2026-11-12"}, TODAY)
    assert error.value.path == ["parameters", "as_at"] and "future" in str(error.value)


def test_an_ordered_pair_defaults_to_a_year_ending_today_and_the_second_must_be_strictly_after_the_first():
    definition = params.ordered_pair()
    assert params.resolve_defaults(definition, TODAY) == {"opening": "2025-11-11", "closing": "2026-11-11"}
    assert params.resolve_defaults(definition, date(2028, 2, 29)) == {"opening": "2027-02-28", "closing": "2028-02-29"}
    params.read(definition, {"opening": "2026-01-01", "closing": "2026-01-02"}, TODAY)
    for opening, closing in (("2026-01-02", "2026-01-02"), ("2026-02-01", "2026-01-01")):        # equal and reversed
        with pytest.raises(ReportInputError) as error:
            params.read(definition, {"opening": opening, "closing": closing}, TODAY)
        assert error.value.path == ["parameters", "closing"] and "after" in str(error.value)


def test_an_inclusive_range_allows_a_single_day_and_the_end_may_not_be_before_the_start():
    definition = params.inclusive_range()
    params.read(definition, {"start": "2026-05-05", "end": "2026-05-05"}, TODAY)
    with pytest.raises(ReportInputError) as error:
        params.read(definition, {"start": "2026-05-06", "end": "2026-05-05"}, TODAY)
    assert error.value.path == ["parameters", "end"]


def test_the_pair_and_the_range_are_not_the_same_rule():
    same_day = {"opening": "2026-05-05", "closing": "2026-05-05"}
    with pytest.raises(ReportInputError):
        params.read(params.ordered_pair(), same_day, TODAY)
    params.read(params.inclusive_range(), {"start": "2026-05-05", "end": "2026-05-05"}, TODAY)


# -- reading a request --

def test_every_parameter_must_be_named_and_none_may_be_unknown():
    definition = params.ordered_pair()
    with pytest.raises(ReportInputError) as error:
        params.read(definition, {"opening": "2026-01-01"}, TODAY)
    assert error.value.path == ["parameters", "closing"] and "required" in str(error.value)
    with pytest.raises(ReportInputError) as error:
        params.read(definition, {"opening": "2026-01-01", "closing": "2026-02-01", "extra": 1}, TODAY)
    assert error.value.path == ["parameters", "extra"]
    with pytest.raises(ReportInputError):
        params.read(definition, [], TODAY)


@pytest.mark.parametrize("value", ["2026-1-1", "20260101", "2026-02-30", "2026-13-01", "", None, 20260101, True, "2026-01-01 "])
def test_a_date_must_be_a_real_date_written_year_month_day(value):
    with pytest.raises(ReportInputError):
        params.read(params.as_of(), {"as_at": value}, TODAY)


def test_a_choice_must_be_one_of_the_offered_values():
    definition = (ParamDef("interval", "Interval", "choice", Literal("month"), choices=(("month", "Month"), ("week", "Week"))),)
    assert params.read(definition, {"interval": "week"}, TODAY) == {"interval": "week"}
    for bad in ("day", "", None, 1):
        with pytest.raises(ReportInputError):
            params.read(definition, {"interval": bad}, TODAY)


def test_a_whole_number_is_a_real_integer_within_its_limits_and_never_a_boolean():
    definition = (ParamDef("depth", "Depth", "integer", Literal(2), minimum=1, maximum=5),)
    assert params.read(definition, {"depth": 3}, TODAY) == {"depth": 3}
    for bad in (0, 6, True, 2.0, "2", None):
        with pytest.raises(ReportInputError):
            params.read(definition, {"depth": bad}, TODAY)


def test_the_effective_parameters_are_echoed_as_a_request_carries_them():
    definition = params.ordered_pair() + (ParamDef("depth", "Depth", "integer", Literal(2)),)
    values = params.read(definition, {"opening": "2026-01-01", "closing": "2026-02-01", "depth": 2}, TODAY)
    assert params.serialise(definition, values) == {"opening": "2026-01-01", "closing": "2026-02-01", "depth": 2}


# -- the definition's defaults --

def test_a_default_that_names_an_unknown_parameter_is_refused_at_registration():
    bad = (ParamDef("a", "A", "date", Offset("missing", years=-1)),)
    with pytest.raises(ReportDefinitionError, match="not another date parameter"):
        params.check("r", bad)


def test_defaults_that_depend_on_each_other_in_a_circle_are_refused():
    bad = (ParamDef("a", "A", "date", Offset("b", days=-1)), ParamDef("b", "B", "date", Offset("a", days=1)))
    with pytest.raises(ReportDefinitionError, match="circle"):
        params.check("r", bad)
    with pytest.raises(ReportDefinitionError):
        params.check("r", (ParamDef("a", "A", "date", Offset("a", days=-1)),))            # a parameter cannot default from itself


def test_a_default_of_the_wrong_kind_is_refused():
    for bad in (ParamDef("a", "A", "integer", Today()), ParamDef("a", "A", "choice", Today(), choices=(("x", "X"),)),
                ParamDef("a", "A", "integer", Offset("b", days=1)), ParamDef("a", "A", "date", "today")):
        with pytest.raises(ReportDefinitionError):
            params.check("r", (bad, ParamDef("b", "B", "date", Today())))


@pytest.mark.parametrize("bad", [
    ParamDef("a", "A", "date", Literal("2026-02-30")),                                      # not a real date
    ParamDef("a", "A", "date", Literal("2999-01-01"), rules=(NotFuture(),)),                # a literal that is in the future
    ParamDef("a", "A", "choice", Literal("z"), choices=(("x", "X"),)),                       # not one of the choices
    ParamDef("a", "A", "integer", Literal(0), minimum=1),                                    # below its minimum
    ParamDef("a", "A", "integer", Literal(True)),                                            # a boolean is not a number
])
def test_a_literal_default_that_does_not_hold_is_refused_at_registration(bad):
    with pytest.raises(ReportDefinitionError):
        params.check("r", (bad,))


def test_a_date_default_that_only_fails_on_some_days_is_found_at_registration():
    # Tomorrow is fine on no day: the default is always in the future, so "not in the future" can never hold.
    bad = (ParamDef("a", "A", "date", Offset("b", days=1), rules=(NotFuture(),)), ParamDef("b", "B", "date", Today()))
    with pytest.raises(ReportDefinitionError, match="do not hold"):
        params.check("r", bad)


def test_other_definition_mistakes_are_refused():
    cases = [
        (ParamDef("A", "A", "date", Today()),),                                              # not a plain lowercase key
        (ParamDef("a", "", "date", Today()),),                                               # no label
        (ParamDef("a", "A", "money", Today()),),                                             # unknown kind
        (ParamDef("a", "A", "date", Today()), ParamDef("a", "B", "date", Today())),          # repeated key
        (ParamDef("a", "A", "date", Today(), choices=(("x", "X"),)),),                       # choices on a date
        (ParamDef("a", "A", "choice", Literal("x"), choices=()),),                           # a choice with none
        (ParamDef("a", "A", "choice", Literal("x"), choices=(("x", "X"), ("x", "Y"))),),     # repeated choices
        (ParamDef("a", "A", "integer", Literal(1), minimum=5, maximum=1),),
        (ParamDef("a", "A", "date", Today(), rules=(After("nobody"),)),),                    # a rule about nothing
        (ParamDef("a", "A", "integer", Literal(1), rules=(NotFuture(),)),),                  # a date rule on a number
        (ParamDef("a", "A", "date", Today(), rules=(OnOrAfter("a"),)),),                     # after itself
    ]
    for case in cases:
        with pytest.raises(ReportDefinitionError):
            params.check("r", case)


def test_a_default_that_does_not_hold_today_is_a_defect_not_a_user_error():
    # Resolving works, but a rule fails on the resolved value, which the engine reports as a fault in the report.
    from northstar.reports import engine
    from northstar.reports.reportdef import ReportDef, ReportResult
    from northstar.reports.sections import SectionDef
    bad = ReportDef("r", "R", "R.", (ParamDef("a", "A", "date", Offset("b", days=1), rules=(NotFuture(),)),
                                     ParamDef("b", "B", "date", Today())),
                    (SectionDef("s", "summary", "tiles", "S"),), lambda ctx: ReportResult({}))
    with pytest.raises(ReportDefectError):
        engine.describe(bad, TODAY)
