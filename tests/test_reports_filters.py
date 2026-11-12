"""A report's filters: what it may be filtered by (everything the registry offers except what it excludes), that its declaration is
checked whichever endpoint is asked first, what a request that names no filters means, and that filtering only narrows what the
framework authorized. Synthetic data only."""

import json
from dataclasses import replace
from datetime import date

import pytest

from conftest import add_account, type_id, with_db
from northstar import clock
from northstar.listdefs import tables as registry_tables
from northstar.lists.kinds import Text
from northstar.lists.registry import FieldDef
from northstar.reports import engine, filters, loader
from northstar.reports.errors import ReportDefectError, ReportInputError
from northstar.reports.population import FixedPopulation
from northstar.reports.reportdef import FilterDecl, ReportDef, ReportResult
from northstar.reports.sections import SectionDef

TODAY = date(2026, 11, 11)
ADMIN = {"id": 1, "is_admin": True}
MEMBER = {"id": 2, "is_admin": False}
SEEN = {}


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(clock, "today", lambda: TODAY)
    SEEN.clear()
    yield
    for key in [k for k in loader._DEFINITIONS if k.startswith("probe")]:
        loader._DEFINITIONS.pop(key)


def make_household(conn):
    """Alpha and Beta in dollars (Savings, Checking), Gamma in euros (Savings), Delta a dollar credit card, and a deleted one."""
    ids = {
        "alpha": add_account(conn, "Alpha", 1, "Savings"), "beta": add_account(conn, "Beta", 1, "Checking"),
        "delta": add_account(conn, "Delta", 2, "Credit card"), "zed": add_account(conn, "Zed", 1, "Savings"),
    }
    ids["gamma"] = conn.execute(                                                                 # an account's currency cannot be changed, so it is made in euros
        "INSERT INTO accounts (name, type_id, currency_id, created_by, updated_by) VALUES ('Gamma', ?, (SELECT id FROM currencies WHERE code = 'EUR'), "
        "(SELECT id FROM users WHERE is_system = 1), (SELECT id FROM users WHERE is_system = 1))", (type_id(conn, "Savings"),)).lastrowid
    conn.execute("UPDATE accounts SET deleted = 1 WHERE id = ?", (ids["zed"],))
    conn.commit()
    return ids


@pytest.fixture
def household(conn):
    return make_household(conn)


@pytest.fixture
def api_household(client):
    """The same household in the database the test client's application reads."""
    with with_db(client) as conn:
        return make_household(conn)


def spy(ctx):
    SEEN["ids"] = ctx.population.account_ids()
    SEEN["fields"] = set(vars(ctx))
    return ReportResult({"s": {"items": []}})


def register(filters_decl, key="probe", admin_only=False):
    definition = ReportDef(key, key.title(), "A probe.", (), (SectionDef("s", "summary", "tiles", "S"),), spy, filters=filters_decl, admin_only=admin_only)
    loader.register(definition)
    return definition


def run(definition, filters_sent="omit", conn=None, user=ADMIN):
    body = {"parameters": {}} if filters_sent == "omit" else {"parameters": {}, "filters": filters_sent}
    return engine.calculate(conn, definition, user, body, TODAY)


def names(conn, ids):
    return sorted(conn.execute("SELECT name FROM accounts WHERE id = ?", (i,)).fetchone()[0] for i in ids)


def keys_of(tree):
    """Every key the drawer would offer, relations and what lies below them."""
    found = []
    for node in [*tree["fields"], *tree["relations"]]:
        found.append(node["key"])
        if node.get("children"):
            found += keys_of(node["children"])
    return found


def condition(field, operator, value=None):
    return {"field": field, "operator": operator, **({} if value is None else {"value": value})}


# -- filtering narrows what the framework authorized --

def test_filters_narrow_the_population_and_conditions_combine_with_and(conn, household):
    definition = register(FilterDecl())
    savings = type_id(conn, "Savings")
    run(definition, [condition("type", "is_any_of", [savings])], conn)
    assert names(conn, SEEN["ids"]) == ["Alpha", "Gamma"]                                      # a deleted account is in no population
    euro = conn.execute("SELECT id FROM currencies WHERE code = 'EUR'").fetchone()[0]
    run(definition, [condition("type", "is_any_of", [savings]), condition("currency", "is", euro)], conn)
    assert names(conn, SEEN["ids"]) == ["Gamma"]
    run(definition, [condition("name", "contains", "e")], conn)                                 # Beta, Delta (and Gamma? no "e" in Gamma: a, m)
    assert names(conn, SEEN["ids"]) == ["Beta", "Delta"]
    run(definition, [condition("is_open", "is_yes")], conn)
    assert names(conn, SEEN["ids"]) == ["Alpha", "Beta", "Delta", "Gamma"]
    run(definition, [], conn)
    assert names(conn, SEEN["ids"]) == ["Alpha", "Beta", "Delta", "Gamma"]
    run(definition, [condition("name", "equals", "Nobody")], conn)
    assert SEEN["ids"] == ()                                                                    # nothing matches: an empty population, not an error


def test_the_calculation_never_sees_the_filters_and_the_answer_says_which_were_applied(conn, household):
    definition = register(FilterDecl())
    sent = [condition("name", "contains", "a")]
    result = run(definition, sent, conn)
    assert SEEN["fields"] == {"conn", "today", "parameters", "population", "currency"}
    assert result["filters"] == sent


def test_filtering_only_narrows_what_the_framework_authorized(conn, household, monkeypatch):
    """Whatever matches, an account the person may not see is never in the population."""
    monkeypatch.setattr(engine, "visible_accounts", lambda connection, user: FixedPopulation([household["alpha"], household["beta"]]))
    definition = register(FilterDecl())
    run(definition, [condition("name", "contains", "a")], conn)                                 # Alpha, Beta, Delta, Gamma all contain an "a"
    assert names(conn, SEEN["ids"]) == ["Alpha", "Beta"]
    run(definition, [], conn)
    assert names(conn, SEEN["ids"]) == ["Alpha", "Beta"]
    run(definition, [condition("name", "equals", "Gamma")], conn)
    assert SEEN["ids"] == ()


# -- what a request that names no filters means --

def test_omitted_filters_are_the_reports_own_an_empty_list_is_none_and_explicit_ones_replace_them(conn, household):
    savings = type_id(conn, "Savings")
    opening = condition("type", "is_any_of", [savings])
    definition = register(FilterDecl(defaults=(opening,)))
    result = run(definition, "omit", conn)
    assert names(conn, SEEN["ids"]) == ["Alpha", "Gamma"] and result["filters"] == [opening]
    result = run(definition, [], conn)
    assert names(conn, SEEN["ids"]) == ["Alpha", "Beta", "Delta", "Gamma"] and result["filters"] == []          # Clear filters stays cleared
    other = condition("name", "equals", "Beta")
    result = run(definition, [other], conn)
    assert names(conn, SEEN["ids"]) == ["Beta"] and result["filters"] == [other]                      # replaces the opening conditions
    assert engine.describe(definition, TODAY, conn)["filters"]["defaults"] == [opening]


def test_a_report_with_no_opening_conditions_starts_unfiltered(conn, household):
    definition = register(FilterDecl())
    assert run(definition, "omit", conn)["filters"] == []
    assert len(SEEN["ids"]) == 4


# -- requests are refused, naming where --

@pytest.mark.parametrize("sent, path", [
    ([condition("no_such_field", "equals", "x")], ["filters", 0, "field"]),
    ([condition("name", "contains", "a"), condition("name", "equals", "b")], ["filters", 1, "field"]),                       # one condition per field
    ([condition("name", "is_after", "x")], ["filters", 0, "operator"]),
    ([condition("name", "contains", "")], ["filters", 0, "value"]),
    ([{"operator": "equals", "value": "x"}], ["filters", 0]),
    (["name"], ["filters", 0]),
    ([{"field": "name", "operator": "equals", "value": "x", "extra": 1}], ["filters", 0]),
    ([condition("name", "contains", "a"), condition("type", "is", "not a number")], ["filters", 1, "value"]),
    ("name", ["filters"]),
    ([condition("name", "contains", "a")] * 31, ["filters"]),
])
def test_a_request_with_something_wrong_in_its_filters_is_refused_whole_naming_the_condition_and_the_part(conn, household, sent, path):
    definition = register(FilterDecl())
    with pytest.raises(ReportInputError) as error:
        run(definition, sent, conn)
    assert error.value.path == path
    assert "ids" not in SEEN                                                                     # nothing was calculated: never partly applied


def test_a_report_that_cannot_be_filtered_says_so_and_offers_nothing(conn, household):
    definition = register(None)
    with pytest.raises(ReportInputError, match="cannot be filtered"):
        run(definition, [condition("name", "contains", "a")], conn)
    run(definition, [], conn)
    assert engine.describe(definition, TODAY)["filters"] == {"enabled": False}
    with pytest.raises(ReportInputError, match="cannot be filtered") as error:
        engine.choices(conn, definition, ADMIN, "type")
    assert error.value.path == ["field"]


# -- dates --

DATE_PATHS = ["created_at", "updated_at", "type.created_at", "type.updated_at", "currency.created_at", "currency.rates_start"]


@pytest.mark.parametrize("field", DATE_PATHS)
def test_a_report_that_excludes_dates_refuses_a_date_on_every_path_and_one_that_does_not_accepts_it(conn, household, field):
    excluding, allowing = register(FilterDecl(exclude_dates=True), "probe_no_dates"), register(FilterDecl(), "probe_dates")
    with pytest.raises(ReportInputError, match="is a date") as error:
        run(excluding, [condition(field, "after", "2026-01-01")], conn)
    assert error.value.path == ["filters", 0, "field"]
    run(allowing, [condition(field, "after", "2026-01-01")], conn)                                 # the same condition, a report that allows it


def test_excluding_dates_leaves_everything_else_available_and_removes_the_dates_from_what_is_offered(conn, household):
    tree = engine.describe(register(FilterDecl(exclude_dates=True), "probe_no_dates"), TODAY, conn)["filters"]["fields"]
    offered = keys_of(tree)
    assert not set(DATE_PATHS) & set(offered)
    assert {"name", "is_open", "notes", "type", "type.class", "type.stale_after_days", "currency", "currency.name", "currency.minor_units", "created_by", "updated_by"} <= set(offered)
    everything = keys_of(engine.describe(register(FilterDecl(), "probe_dates"), TODAY, conn)["filters"]["fields"])
    assert set(DATE_PATHS) <= set(everything)


def test_what_is_offered_is_exactly_what_a_request_would_accept(conn, household):
    definition = register(FilterDecl(exclude_dates=True, exclude=("type.stale_after_days",)), "probe_rules")
    rules = filters.prepare(conn, definition)
    offered = set(keys_of(engine.describe(definition, TODAY, conn)["filters"]["fields"]))
    registry = set(keys_of(engine.describe(register(FilterDecl(), "probe_all"), TODAY, conn)["filters"]["fields"]))
    assert offered == {key for key in registry if rules.refusal(key) is None} and offered < registry


# -- named exclusions, on whole path segments --

def test_excluding_a_relation_excludes_it_and_everything_beneath_it(conn, household):
    definition = register(FilterDecl(exclude=("type",)))
    offered = set(keys_of(engine.describe(definition, TODAY, conn)["filters"]["fields"]))
    assert "type" not in offered and not any(key.startswith("type.") for key in offered) and {"currency", "currency.name"} <= offered
    for field, operator, value in (("type", "is_any_of", [1]), ("type.class", "is_any_of", [1]), ("type.stale_after_days", "at_least", 1)):
        with pytest.raises(ReportInputError, match="not available as a filter") as error:
            run(definition, [condition(field, operator, value)], conn)
        assert error.value.path == ["filters", 0, "field"]
    run(definition, [condition("currency", "is", 1)], conn)


def test_excluding_one_field_of_a_relation_leaves_its_other_fields(conn, household):
    definition = register(FilterDecl(exclude=("type.stale_after_days",)))
    offered = set(keys_of(engine.describe(definition, TODAY, conn)["filters"]["fields"]))
    assert "type.stale_after_days" not in offered and {"type", "type.class"} <= offered
    with pytest.raises(ReportInputError, match="not available as a filter"):
        run(definition, [condition("type.stale_after_days", "at_least", 1)], conn)
    run(definition, [condition("type", "is_any_of", [type_id(conn, "Savings")])], conn)
    run(definition, [condition("type.class", "is_any_of", [1])], conn)


@pytest.mark.parametrize("bad", ["typ", "type.nam", "types", "Type", "no_such", "type..name", ".type", "type.class.nope", "deleted", "password_hash"])
def test_an_exclusion_that_names_nothing_the_registry_offers_is_a_fault_in_the_report(conn, household, bad):
    """A misspelled or obsolete exclusion must not become a restriction that quietly stops applying."""
    definition = register(FilterDecl(exclude=(bad,)))
    with pytest.raises(ReportDefectError, match="excludes"):
        engine.describe(definition, TODAY, conn)


# -- the declaration is checked whichever endpoint is asked first --

def test_a_bad_exclusion_is_found_by_a_calculation_and_by_choices_without_describing_the_report_first(conn, household):
    definition = register(FilterDecl(exclude=("typ",)))
    with pytest.raises(ReportDefectError, match="excludes 'typ'"):
        run(definition, "omit", conn)
    with pytest.raises(ReportDefectError, match="excludes 'typ'"):
        engine.choices(conn, definition, ADMIN, "currency")
    assert "ids" not in SEEN                                                                     # and nothing was calculated


def test_the_same_fault_is_a_500_with_no_result_on_each_endpoint_even_when_the_definition_is_never_fetched(client, household):
    register(FilterDecl(exclude=("typ",)))
    post = client.post("/api/reports/probe", json={"parameters": {}})
    assert post.status_code == 500 and post.json()["code"] == "calculation_error" and "sections" not in post.json()
    assert client.get("/api/reports/probe/choices/currency").status_code == 500
    assert client.get("/api/reports/probe").status_code == 500


@pytest.mark.parametrize("opening", [
    condition("no_such_field", "equals", "x"), condition("name", "is_after", "x"), condition("name", "contains", ""),
    condition("created_at", "after", "2026-01-01"),                                              # a date, in a report that excludes dates
    condition("type", "is_any_of", [1, 2]),                                                      # fine: used for the control below
])
def test_an_opening_condition_the_rules_refuse_is_a_fault_and_never_a_reason_to_widen_the_report(conn, household, opening):
    definition = register(FilterDecl(exclude_dates=True, defaults=(opening,)))
    if opening["field"] == "type":
        engine.describe(definition, TODAY, conn)
        return
    with pytest.raises(ReportDefectError, match="default filters do not hold"):
        engine.describe(definition, TODAY, conn)
    with pytest.raises(ReportDefectError):
        run(definition, "omit", conn)
    with pytest.raises(ReportDefectError):
        run(definition, [], conn)                                                                # even a request that overrides them: the report is broken


def test_every_registered_report_has_filter_rules_that_hold_against_the_real_registry(conn):
    """From the first real report on, a typo in an exclusion fails here and not on a person's page."""
    import northstar.reportdefs  # noqa: F401  registers the household's reports
    for definition in loader._DEFINITIONS.values():
        filters.prepare(conn, definition)


# -- what the page is told --

def test_the_definition_offers_the_fields_in_the_lists_shape_and_nothing_about_the_population(conn, household):
    definition = register(FilterDecl(exclude_dates=True))
    offered = engine.describe(definition, TODAY, conn)["filters"]
    assert set(offered) == {"enabled", "fields", "defaults"} and offered["enabled"] is True and offered["defaults"] == []
    assert set(offered["fields"]) == {"fields", "relations"}
    node = next(n for n in offered["fields"]["fields"] if n["key"] == "name")
    assert {"key", "label", "path_label", "kind", "operators", "choices"} <= set(node)
    text = json.dumps(offered)
    for private in ("live_accounts", "population", "SELECT", "account_summaries", "last_cents", "reporting_value"):
        assert private not in text


def test_describing_a_report_that_can_be_filtered_needs_the_database(conn):
    with pytest.raises(ValueError, match="needs the database"):
        engine.describe(register(FilterDecl()), TODAY)


# -- the registry decides what is offered, and a report only restricts --

def test_a_field_added_to_the_registry_is_offered_to_a_report_that_does_not_exclude_it(conn, household, monkeypatch):
    """The rule, on purpose: a report adds restrictions and never access, so what the registry offers reaches every report that
    does not exclude it."""
    conn.execute("ALTER TABLE accounts ADD COLUMN nickname TEXT")
    conn.execute("UPDATE accounts SET nickname = 'Rainy day' WHERE id = ?", (household["alpha"],))
    conn.commit()
    accounts = registry_tables.TABLES["accounts"]
    monkeypatch.setattr(registry_tables, "TABLES", {**registry_tables.TABLES, "accounts": replace(accounts, fields={**accounts.fields, "nickname": FieldDef(Text())})})
    plain, excluding = register(FilterDecl(), "probe_plain"), register(FilterDecl(exclude=("nickname",)), "probe_excluding")
    assert "nickname" in keys_of(engine.describe(plain, TODAY, conn)["filters"]["fields"])
    assert "nickname" not in keys_of(engine.describe(excluding, TODAY, conn)["filters"]["fields"])
    run(plain, [condition("nickname", "contains", "Rainy")], conn)
    assert names(conn, SEEN["ids"]) == ["Alpha"]
    with pytest.raises(ReportInputError, match="not available as a filter"):
        run(excluding, [condition("nickname", "contains", "Rainy")], conn)


def test_the_registrys_denied_fields_are_not_offered_by_any_report(conn, household):
    offered = set(keys_of(engine.describe(register(FilterDecl()), TODAY, conn)["filters"]["fields"]))
    for hidden in ("deleted", "id", "password_hash", "type_id", "created_by.email", "created_by.password_hash", "last_cents", "days_since"):
        assert hidden not in offered
    with pytest.raises(ReportInputError):
        run(register(FilterDecl(), "probe_other"), [condition("deleted", "is_yes")], conn)


# -- the choices endpoint --

def test_choices_are_the_records_the_accounts_the_person_may_see_point_at(conn, household):
    definition = register(FilterDecl())
    answer = engine.choices(conn, definition, ADMIN, "type")
    assert answer["kind"] == "records" and answer["more"] is False
    assert [o["value"] for o in answer["options"]] == ["Checking", "Credit card", "Savings"]    # only the types in use, and a deleted account's alone is not
    assert answer["options"][0]["id"] == type_id(conn, "Checking")
    assert sorted(o["value"] for o in engine.choices(conn, definition, ADMIN, "currency")["options"]) == ["EUR", "USD"]


def test_choices_are_drawn_from_the_authorized_accounts_and_not_from_every_record(conn, household, monkeypatch):
    monkeypatch.setattr(engine, "visible_accounts", lambda connection, user: FixedPopulation([household["beta"]]))
    definition = register(FilterDecl())
    assert [o["value"] for o in engine.choices(conn, definition, MEMBER, "type")["options"]] == ["Checking"]
    assert [o["value"] for o in engine.choices(conn, definition, MEMBER, "currency")["options"]] == ["USD"]


def test_choices_refuse_a_field_the_report_does_not_offer_one_without_choices_and_one_that_is_not_a_field(conn, household):
    definition = register(FilterDecl(exclude_dates=True, exclude=("type",)))
    for field, message in (("type", "not available as a filter"), ("type.class", "not available as a filter"), ("created_at", "is a date"),
                           ("currency.created_at", "is a date"), ("name", "no list of choices"), ("is_open", "no list of choices"),
                           ("no_such", "not a column"), ("", "does not exist"), (None, "does not exist")):
        with pytest.raises(ReportInputError, match=message) as error:
            engine.choices(conn, definition, ADMIN, field)
        assert error.value.path == ["field"]
    assert engine.choices(conn, definition, ADMIN, "currency")["options"]


def test_the_choices_endpoint_needs_a_person_who_may_see_the_report(client, member_client, anon_client, household):
    register(FilterDecl(), "probe_open")
    register(FilterDecl(), "probe_admin", admin_only=True)
    assert anon_client.get("/api/reports/probe_open/choices/type").status_code == 401
    assert client.get("/api/reports/nothing/choices/type").status_code == 404
    assert member_client.get("/api/reports/probe_open/choices/type").status_code == 200
    assert member_client.get("/api/reports/probe_admin/choices/type").status_code == 403           # the same as the report's own endpoints
    assert member_client.get("/api/reports/probe_admin").status_code == 403
    assert member_client.post("/api/reports/probe_admin", json={"parameters": {}}).status_code == 403
    assert client.get("/api/reports/probe_admin/choices/type").status_code == 200


def test_the_endpoints_carry_the_filters_and_say_where_a_bad_one_is(client, api_household):
    register(FilterDecl(exclude_dates=True), "probe_wire")
    described = client.get("/api/reports/probe_wire").json()["filters"]
    assert described["enabled"] is True and "type" in keys_of(described["fields"])
    answer = client.get("/api/reports/probe_wire/choices/type")
    assert answer.status_code == 200 and {o["value"] for o in answer.json()["options"]} == {"Checking", "Credit card", "Savings"}
    bad = client.post("/api/reports/probe_wire", json={"parameters": {}, "filters": [condition("created_at", "after", "2026-01-01")]})
    assert bad.status_code == 422 and bad.json()["code"] == "invalid_input" and bad.json()["path"] == ["filters", 0, "field"]
    refused = client.get("/api/reports/probe_wire/choices/created_at")
    assert refused.status_code == 422 and refused.json()["path"] == ["field"]
    good = client.post("/api/reports/probe_wire", json={"parameters": {}, "filters": [condition("name", "contains", "a")]})
    assert good.status_code == 200 and good.json()["filters"] == [condition("name", "contains", "a")]


def test_an_exclusion_is_a_whole_path_segment_and_never_a_prefix_of_the_text(conn, household, monkeypatch):
    """Excluding `name` must not take `name_short` with it, and excluding `type` must not take `type_note`."""
    conn.execute("ALTER TABLE accounts ADD COLUMN name_short TEXT")
    conn.commit()
    accounts = registry_tables.TABLES["accounts"]
    monkeypatch.setattr(registry_tables, "TABLES", {**registry_tables.TABLES, "accounts": replace(accounts, fields={**accounts.fields, "name_short": FieldDef(Text())})})
    definition = register(FilterDecl(exclude=("name",)))
    offered = set(keys_of(engine.describe(definition, TODAY, conn)["filters"]["fields"]))
    assert "name" not in offered and "name_short" in offered
    run(definition, [condition("name_short", "contains", "x")], conn)
    with pytest.raises(ReportInputError, match="not available as a filter"):
        run(definition, [condition("name", "contains", "x")], conn)


def test_a_field_reached_through_a_date_is_a_date_for_a_report_that_excludes_dates(conn, household, monkeypatch):
    """A relation whose display value is a date is a date, so what lies beneath it is refused and not offered, though those fields are
    not dates themselves. (No such relation exists today; this makes one.)"""
    types = registry_tables.TABLES["account_types"]
    monkeypatch.setattr(registry_tables, "TABLES", {**registry_tables.TABLES, "account_types": replace(types, display="created_at")})
    excluding, allowing = register(FilterDecl(exclude_dates=True), "probe_no_dates"), register(FilterDecl(), "probe_dates")
    offered = set(keys_of(engine.describe(excluding, TODAY, conn)["filters"]["fields"]))
    assert not {key for key in offered if key == "type" or key.startswith("type.")} and "currency" in offered
    for field, operator, value in (("type", "after", "2026-01-01"), ("type.stale_after_days", "at_least", 1), ("type.class", "is_any_of", [1])):
        with pytest.raises(ReportInputError, match="is a date"):
            run(excluding, [condition(field, operator, value)], conn)
    assert "type.stale_after_days" in set(keys_of(engine.describe(allowing, TODAY, conn)["filters"]["fields"]))
