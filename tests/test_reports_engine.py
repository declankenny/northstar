"""Registering reports, describing them and calculating them: what is checked at each step and what every failure looks like.
Synthetic data only."""

import ast
import sqlite3
from pathlib import Path

import pytest

from conftest import add_account
from northstar import db
from northstar.errors import NotFoundError
from northstar.networth import NoRate
from northstar.reports import engine, loader, params
from northstar.reports.errors import ReportDefectError, ReportDefinitionError, ReportInputError, ReportUnavailable
from northstar.reports.population import FixedPopulation
from northstar.reports.reportdef import FilterDecl, ReportDef, ReportResult
from northstar.reports.sections import SectionDef
from reports_synthetic import ALL, AS_OF, NONE, PAIR, RANGE, register_all, unregister_all
from datetime import date

TODAY = date(2026, 11, 11)
ADMIN = {"id": 1, "is_admin": True}
MEMBER = {"id": 2, "is_admin": False}


@pytest.fixture(autouse=True)
def reports():
    register_all()
    yield
    unregister_all()


@pytest.fixture
def household(conn):
    ids = [add_account(conn, name, 1, "Savings") for name in ("One", "Two", "Three")]
    conn.commit()
    return ids


def simple(calculate, **extra):
    """A report with a summary section, whose calculation is the one given."""
    return ReportDef("probe", "Probe", "A probe.", extra.pop("params", ()), (SectionDef("s", "summary", "tiles", "S"),), calculate, **extra)


def ok(ctx):
    return ReportResult({"s": {"items": []}})


# -- registering --

def test_registering_checks_the_definition_and_refuses_a_repeat():
    with pytest.raises(ValueError, match="already registered"):
        loader.register(AS_OF)
    for bad in (simple(ok, population="people"), ReportDef("Bad Key", "T", "D", (), AS_OF.sections, ok),
                ReportDef("a", "", "D", (), AS_OF.sections, ok), ReportDef("a", "T", "", (), AS_OF.sections, ok),
                ReportDef("a", "T", "D", (), AS_OF.sections, "not callable"), simple(ok, filters=FilterDecl("")),
                ReportDef("a", "T", "D", (), (), ok)):
        with pytest.raises(ReportDefinitionError):
            loader.register(bad)
    assert "a" not in loader._DEFINITIONS and "probe" not in loader._DEFINITIONS


def test_the_shape_of_a_filter_declaration_is_checked_when_it_is_registered():
    """Only the shape: what the exclusions and the default conditions mean needs the registry, so that is checked whenever the report is
    used (tests/test_reports_filters.py)."""
    for bad in (FilterDecl(exclude_dates="yes"), FilterDecl(exclude=["type"]), FilterDecl(exclude=("",)), FilterDecl(exclude=(3,)),
                FilterDecl(defaults=("x",)), FilterDecl(defaults=[{"field": "type"}]), "type"):
        with pytest.raises(ReportDefinitionError):
            loader.register(simple(ok, filters=bad))
    assert "probe" not in loader._DEFINITIONS
    loader.register(simple(ok, filters=FilterDecl()))                            # no exclusions and no defaults: everything, unrestricted
    loader._DEFINITIONS.pop("probe")
    loader.register(simple(ok, filters=FilterDecl(exclude_dates=True, exclude=("type.name",),
                                                  defaults=({"field": "type", "operator": "is", "value": 1},))))
    loader._DEFINITIONS.pop("probe")


def test_an_unknown_report_is_not_found_and_an_admin_only_report_is_hidden_from_others():
    with pytest.raises(NotFoundError):
        loader.get_report("nothing")
    assert [d.key for d in loader.visible_to(ADMIN)] == ["assets_liabilities", "synthetic_as_of", "synthetic_none", "synthetic_pair", "synthetic_range"]
    assert [d.key for d in loader.visible_to(MEMBER)] == ["assets_liabilities", "synthetic_as_of", "synthetic_pair", "synthetic_range"]


def test_the_framework_never_imports_a_definition():
    """Adding a report must edit no framework file, so nothing under northstar/reports may import northstar.reportdefs."""
    folder = Path(__file__).resolve().parent.parent / "northstar" / "reports"
    found = []
    for file in sorted(folder.glob("*.py")):
        for node in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
            names = [node.module] if isinstance(node, ast.ImportFrom) and node.module else [a.name for a in getattr(node, "names", [])] if isinstance(node, ast.Import) else []
            if any(name and name.startswith("northstar.reportdefs") for name in names):
                found.append(file.name)
    assert not found


# -- describing --

def test_a_report_is_described_with_its_defaults_resolved_for_the_servers_today():
    described = engine.describe(PAIR, TODAY)
    assert described["today"] == "2026-11-11"
    assert {p["key"]: p["default"] for p in described["parameters"]} == {"opening": "2025-11-11", "closing": "2026-11-11"}
    assert described["sections"] == [{"key": "detail", "kind": "rows", "view": "table", "title": "Detail", "sized": False, "columns": 12}]
    assert described["filters"] == {"enabled": False}


def test_a_description_is_public_metadata_only():
    described = engine.describe(RANGE, TODAY)
    assert set(described) == {"key", "title", "description", "today", "parameters", "sections", "filters"}      # the population stays internal
    assert "calculate" not in str(described) and "function" not in str(described)
    interval = [p for p in described["parameters"] if p["key"] == "interval"][0]
    assert interval["choices"] == [{"value": "month", "label": "Month"}, {"value": "week", "label": "Week"}]


def test_the_date_rules_are_public_so_the_page_can_tell_a_strict_pair_from_an_inclusive_range():
    def rules(definition):
        return {p["key"]: p["rules"] for p in engine.describe(definition, TODAY)["parameters"]}

    assert rules(AS_OF) == {"as_at": [{"rule": "not_future"}]}
    assert rules(PAIR) == {"opening": [{"rule": "not_future"}], "closing": [{"rule": "not_future"}, {"rule": "after", "other": "opening"}]}
    assert rules(RANGE) == {"start": [{"rule": "not_future"}], "end": [{"rule": "not_future"}, {"rule": "on_or_after", "other": "start"}],
                            "interval": []}


def test_a_report_with_no_parameters_has_none_to_describe():
    assert engine.describe(NONE, TODAY)["parameters"] == []


# -- calculating --

def test_a_report_is_calculated_with_every_section_checked_and_the_parents_sized(conn, household):
    result = engine.calculate(conn, AS_OF, ADMIN, {"parameters": {"as_at": "2026-11-11"}, "filters": []}, TODAY)
    assert result["report"] == "synthetic_as_of" and result["filters"] == [] and result["today"] == "2026-11-11"
    assert result["parameters"] == {"as_at": "2026-11-11"}
    assert result["currency"] == {"code": "USD", "minor_units": 2}
    tree = {n["id"]: n for n in result["sections"]["composition"]["nodes"]}
    odd, even = tree["group_odd"], tree["group_even"]
    assert odd["size"] == sum(c["size"] for c in odd["children"]) and even["size"] == 0       # the negative leaves have no size
    assert even["value"] < 0                                                                  # and their value is still negative
    items = {i["key"]: i["value"] for i in result["sections"]["headline"]["items"]}
    assert items["total"] == odd["value"] + even["value"] and items["as_at"] == "2026-11-11"
    assert result["notes"][0]["section"] == "composition"


def test_a_report_with_no_accounts_is_an_honest_empty_result_not_an_error(conn):
    result = engine.calculate(conn, AS_OF, ADMIN, {"parameters": {"as_at": "2026-11-11"}}, TODAY)
    assert result["sections"]["composition"]["nodes"] == [] and result["sections"]["headline"]["items"][0]["value"] == 0


def test_the_request_must_name_every_parameter_and_nothing_is_filled_in(conn, household):
    with pytest.raises(ReportInputError) as error:
        engine.calculate(conn, PAIR, ADMIN, {"parameters": {"opening": "2026-01-01"}}, TODAY)
    assert error.value.path == ["parameters", "closing"]
    with pytest.raises(ReportInputError) as error:
        engine.calculate(conn, PAIR, ADMIN, {}, TODAY)
    assert error.value.path == ["parameters"]


def test_a_request_with_the_wrong_shape_is_refused_with_where(conn):
    for body, path in (([], []), ({"parameters": {}, "surprise": 1}, ["surprise"]), ({"parameters": {}, "filters": "x"}, ["filters"]),
                       ({"parameters": []}, ["parameters"])):
        with pytest.raises(ReportInputError) as error:
            engine.calculate(conn, NONE, ADMIN, body, TODAY)
        assert error.value.path == path


def test_a_report_that_cannot_be_filtered_refuses_any_filter_and_never_silently_drops_one(conn, household):
    condition = {"field": "account", "operator": "is", "value": household[0]}
    with pytest.raises(ReportInputError, match="cannot be filtered") as error:
        engine.calculate(conn, NONE, ADMIN, {"parameters": {}, "filters": [condition]}, TODAY)
    assert error.value.path == ["filters"]
    engine.calculate(conn, NONE, ADMIN, {"parameters": {}, "filters": []}, TODAY)           # an empty list is no filter


def test_the_calculation_gets_a_population_the_framework_built_and_not_the_filters(conn, household):
    seen = {}

    def spy(ctx):
        seen["population"] = ctx.population.account_ids()
        seen["fields"] = set(vars(ctx))
        return ok(ctx)

    engine.calculate(conn, simple(spy), ADMIN, {"parameters": {}}, TODAY)
    assert seen["population"] == tuple(sorted(household))
    assert seen["fields"] == {"conn", "today", "parameters", "population", "currency"}      # no user: authorization is the population's


def test_a_deleted_account_is_not_in_the_population(conn, household):
    conn.execute("UPDATE accounts SET deleted = 1 WHERE id = ?", (household[0],))
    seen = {}
    engine.calculate(conn, simple(lambda ctx: seen.update(ids=ctx.population.account_ids()) or ok(ctx)), ADMIN, {"parameters": {}}, TODAY)
    assert household[0] not in seen["ids"] and len(seen["ids"]) == 2


def test_who_asks_decides_the_population_and_goes_no_further(conn, household, monkeypatch):
    """The user reaches the framework's population builder and never the calculation."""
    asked = []

    def narrowed(connection, user):
        asked.append(user["id"])
        return FixedPopulation(household[:1])

    monkeypatch.setattr(engine, "visible_accounts", narrowed)
    seen = {}
    engine.calculate(conn, simple(lambda ctx: seen.update(ids=ctx.population.account_ids()) or ok(ctx)), MEMBER, {"parameters": {}}, TODAY)
    assert asked == [MEMBER["id"]] and seen["ids"] == (household[0],)


def test_the_fixed_population_is_sorted_without_repeats_and_refuses_what_is_not_an_account_id():
    assert FixedPopulation([3, 1, 3, 2]).account_ids() == (1, 2, 3)
    for bad in ([0], [True], ["1"], [1.5]):
        with pytest.raises(ValueError):
            FixedPopulation(bad)


def test_a_calculation_reads_inside_one_consistent_read_and_cannot_write(conn, household):
    inside = {}

    def reader(ctx):
        inside["transaction"] = ctx.conn.in_transaction
        inside["query_only"] = ctx.conn.execute("PRAGMA query_only").fetchone()[0]
        return ok(ctx)

    engine.calculate(conn, simple(reader), ADMIN, {"parameters": {}}, TODAY)
    assert inside == {"transaction": True, "query_only": 1}
    assert not conn.in_transaction and conn.execute("PRAGMA query_only").fetchone()[0] == 0   # the connection is as it was

    def writer(ctx):
        ctx.conn.execute("UPDATE accounts SET name = 'changed' WHERE id = ?", (household[0],))
        return ok(ctx)

    with pytest.raises(ReportDefectError):
        engine.calculate(conn, simple(writer), ADMIN, {"parameters": {}}, TODAY)
    assert conn.execute("SELECT name FROM accounts WHERE id = ?", (household[0],)).fetchone()["name"] == "One"


def test_a_read_transaction_joins_one_that_is_open_but_is_still_read_only_and_restores_the_connection(conn, household):
    with db.write_transaction(conn):
        with db.read_transaction(conn):
            assert conn.in_transaction
            with pytest.raises(sqlite3.OperationalError):             # the outer transaction is writable, this block is not
                conn.execute("UPDATE accounts SET name = 'changed' WHERE id = ?", (household[0],))
        assert conn.in_transaction                                  # the outer block is still open
        assert conn.execute("PRAGMA query_only").fetchone()[0] == 0
        conn.execute("UPDATE accounts SET name = 'by the outer block' WHERE id = ?", (household[0],))     # and may write again
    assert not conn.in_transaction
    assert conn.execute("SELECT name FROM accounts WHERE id = ?", (household[0],)).fetchone()["name"] == "by the outer block"


# -- the three kinds of failure --

def test_the_currency_is_read_inside_the_same_snapshot_as_the_population_and_the_calculation(conn, household, monkeypatch):
    """Every database-derived input shares one consistency boundary: the currency is read after the snapshot has begun."""
    inside = {}
    real = engine.currencies.system_currency

    def spy(connection):
        inside["currency"] = connection.in_transaction and connection.execute("PRAGMA query_only").fetchone()[0] == 1
        return real(connection)

    monkeypatch.setattr(engine.currencies, "system_currency", spy)
    engine.calculate(conn, simple(ok), ADMIN, {"parameters": {}}, TODAY)
    assert inside["currency"] is True
    assert not conn.in_transaction and conn.execute("PRAGMA query_only").fetchone()[0] == 0


def test_an_unset_system_currency_is_unavailable_data_not_a_mistake(conn):
    conn.execute("UPDATE system_properties SET value = NULL, read_only = 0 WHERE name = 'system.currency'")
    with pytest.raises(ReportUnavailable) as error:
        engine.calculate(conn, NONE, ADMIN, {"parameters": {}}, TODAY)
    assert error.value.details["code"] == "unavailable_data" and error.value.reason == "no_system_currency"
    assert not conn.in_transaction and conn.execute("PRAGMA query_only").fetchone()[0] == 0      # the snapshot ended with the refusal


def test_a_missing_exchange_rate_is_unavailable_data_with_a_stable_reason(conn):
    def no_rate(ctx):
        raise NoRate("2026-01-01", ["EUR"])

    with pytest.raises(ReportUnavailable) as error:
        engine.calculate(conn, simple(no_rate), ADMIN, {"parameters": {}}, TODAY)
    assert error.value.details == {"code": "unavailable_data", "reason": "missing_rates", "missing_rates": ["EUR"]}
    assert "EUR" in str(error.value)                                # the message stays readable; the page classifies by code


def test_invalid_input_carries_a_code_and_a_path(conn):
    with pytest.raises(ReportInputError) as error:
        engine.calculate(conn, AS_OF, ADMIN, {"parameters": {"as_at": "2999-01-01"}}, TODAY)
    assert error.value.details == {"code": "invalid_input", "path": ["parameters", "as_at"]}


def test_a_calculation_that_breaks_is_a_defect_whose_message_holds_no_data(conn):
    def explode(ctx):
        raise KeyError("a-secret-account-name")

    with pytest.raises(ReportDefectError) as error:
        engine.calculate(conn, simple(explode), ADMIN, {"parameters": {}}, TODAY)
    assert "a-secret-account-name" not in str(error.value) and isinstance(error.value.__cause__, KeyError)


@pytest.mark.parametrize("returned, why", [
    (lambda ctx: {"s": {"items": []}}, "not a ReportResult"),
    (lambda ctx: ReportResult(["s"]), "sections not a mapping"),
    (lambda ctx: ReportResult({}), "a declared section is missing"),
    (lambda ctx: ReportResult({"s": {"items": []}, "extra": {}}), "an undeclared section"),
    (lambda ctx: ReportResult({"s": {"rows": []}}), "the wrong kind of data"),
    (lambda ctx: ReportResult({"s": {"items": [{"key": "a", "label": "A", "kind": "money", "value": True}]}}), "a boolean as money"),
    (lambda ctx: ReportResult({"s": {"items": []}}, [{"code": "x", "text": "t", "section": "ghost"}]), "a note on an unknown section"),
])
def test_a_wrong_result_is_a_defect_and_never_a_partial_result(conn, returned, why):
    with pytest.raises(ReportDefectError):
        engine.calculate(conn, simple(returned), ADMIN, {"parameters": {}}, TODAY)


def test_the_four_synthetic_reports_cover_four_different_shapes(conn, household):
    shapes = {}
    for definition, parameters in ((AS_OF, {"as_at": "2026-11-11"}), (PAIR, {"opening": "2026-01-01", "closing": "2026-06-01"}),
                                   (NONE, {}), (RANGE, {"start": "2026-01-01", "end": "2026-06-01", "interval": "week"})):
        result = engine.calculate(conn, definition, ADMIN, {"parameters": parameters}, TODAY)
        shapes[definition.key] = (tuple(p.kind for p in definition.params), tuple(s.kind for s in definition.sections))
        assert set(result["sections"]) == {s.key for s in definition.sections}
    assert len(set(shapes.values())) == 4
    assert len(ALL) == 4
