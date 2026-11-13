"""The Assets & Liabilities report: figures checked by hand on synthetic data, reconciliation with the Dashboard's net worth, and every
state the design names. Synthetic data only."""

from datetime import date

import pytest

from conftest import add_account, add_balance, op
from northstar import currencies, locales, networth, rates
from northstar.reports import engine, loader
from northstar.reports.errors import ReportInputError, ReportUnavailable
from northstar.reportdefs.assets_liabilities import ASSETS_AND_LIABILITIES as REPORT

TODAY = date(2026, 11, 11)
ADMIN = {"id": 1, "is_admin": True}
SYSTEM = "(SELECT id FROM users WHERE is_system = 1)"


def add_foreign(conn, name, code, type_name):
    return conn.execute(
        "INSERT INTO accounts (name, type_id, currency_id, created_by, updated_by) VALUES "
        f"(?, (SELECT id FROM account_types WHERE name = ?), (SELECT id FROM currencies WHERE code = ?), {SYSTEM}, {SYSTEM})",
        (name, type_name, code)).lastrowid


def type_id(conn, name):
    return conn.execute("SELECT id FROM account_types WHERE name = ?", (name,)).fetchone()[0]


@pytest.fixture
def household(conn):
    """Six accounts, hand-calculated on 30 June 2026 (euro rate 1.25 from 1 June, 1.10 before).

    usd_sav   Savings, dollars:    1,500.00 on 1 Mar                      asset      150,000
    eur_sav   Savings, euros:      1,200.00 on 1 Apr  x 1.25 = 1,500.00   asset      150,000
    eur_over  Checking, euros:      -500.05 on 15 Feb x 1.25 = -625.06    asset      -62,506 (overdrawn)
    empty     Checking, dollars:     no balance                           asset            0
    usd_card  Credit card, dollars:   250.50 on 1 Feb                     liability   25,050
    eur_loan  Loan, euros:            500.05 on 15 Feb x 1.25 = 625.06    liability   62,506
    """
    currencies.update_currency(op(conn), "EUR", True, "2020-01-01", TODAY)
    rates.add_rate(op(conn), "EUR", "2026-01-01", "1.10", TODAY)
    rates.add_rate(op(conn), "EUR", "2026-06-01", "1.25", TODAY)
    ids = {"usd_sav": add_account(conn, "Test dollar savings", 1, "Savings"), "usd_card": add_account(conn, "Test card", 2, "Credit card"),
           "eur_sav": add_foreign(conn, "Test euro savings", "EUR", "Savings"), "eur_loan": add_foreign(conn, "Test euro loan", "EUR", "Loan"),
           "eur_over": add_foreign(conn, "Test euro overdraft", "EUR", "Checking"), "empty": add_account(conn, "Test empty", 1, "Checking")}
    for name, day, amount in (("usd_sav", "2026-03-01", 150_000), ("usd_card", "2026-02-01", 25_050), ("eur_sav", "2026-04-01", 120_000),
                              ("eur_loan", "2026-02-15", 50_005), ("eur_over", "2026-02-15", -50_005)):
        add_balance(conn, ids[name], day, amount)
    conn.commit()
    return ids


def run(conn, day="2026-06-30", filters="omit"):
    body = {"parameters": {"as_at": day}}
    if filters != "omit":
        body["filters"] = filters
    return engine.calculate(conn, REPORT, ADMIN, body, TODAY)


def items(result):
    return {item["key"]: item for item in result["sections"]["headline"]["items"]}


def find(nodes, ident):
    for node in nodes:
        if node["id"] == ident:
            return node
        found = find(node.get("children", []), ident)
        if found:
            return found
    return None


def leaves(nodes):
    return [leaf for node in nodes for leaf in (leaves(node["children"]) if "children" in node else [node])]


# -- what it is --

def test_it_is_registered_with_a_headline_and_two_half_width_sized_treemaps_and_opens_unfiltered_at_today():
    assert loader.get_report("assets_liabilities") is REPORT
    assert [(s.key, s.kind, s.view, s.sized, s.columns) for s in REPORT.sections] == [
        ("headline", "summary", "tiles", False, 12), ("assets", "hierarchy", "treemap", True, 6), ("liabilities", "hierarchy", "treemap", True, 6)]
    assert REPORT.description == "What you own and what you owe."
    assert REPORT.filters.exclude_dates is True and REPORT.filters.defaults == ()
    assert [(p.key, p.kind) for p in REPORT.params] == [("as_at", "date")]


def test_the_date_defaults_to_the_servers_today_and_the_future_is_refused(conn, household):
    assert engine.describe(REPORT, TODAY, conn)["parameters"][0]["default"] == "2026-11-11"
    with pytest.raises(ReportInputError):
        run(conn, "2026-11-12")


# -- the figures, by hand --

def test_the_headline_is_the_hand_calculated_figures_with_the_account_counts_that_add_up(conn, household):
    got = items(run(conn))
    assert (got["assets"]["value"], got["liabilities"]["value"], got["net_worth"]["value"]) == (237_494, 87_556, 149_938)
    assert (got["assets"]["note"], got["liabilities"]["note"], got["net_worth"]["note"]) == ("4 accounts", "2 accounts", "6 accounts")


def test_it_equals_the_dashboards_net_worth_for_the_same_date(conn, household):
    for day in ("2026-02-20", "2026-05-31", "2026-06-30", "2026-11-11"):
        expected = networth.net_worth_on(conn, date.fromisoformat(day))
        got = items(run(conn, day))
        assert (got["assets"]["value"], got["liabilities"]["value"], got["net_worth"]["value"]) == (
            expected["assets"], expected["liabilities"], expected["net_worth"]), day


def test_each_hierarchy_is_types_holding_accounts_and_every_parent_is_the_sum_of_its_accounts(conn, household):
    result = run(conn)
    assets, liabilities = result["sections"]["assets"]["nodes"], result["sections"]["liabilities"]["nodes"]
    assert [(n["label"], n["value"], len(n["children"])) for n in assets] == [("Savings", 300_000, 2), ("Checking", -62_506, 2)]
    assert [(n["label"], n["value"]) for n in liabilities] == [("Loan", 62_506), ("Credit card", 25_050)]
    assert sum(n["value"] for n in assets) == items(result)["assets"]["value"]
    assert sum(n["value"] for n in liabilities) == items(result)["liabilities"]["value"]


def test_types_and_their_accounts_are_largest_first_and_the_server_does_not_leave_it_to_the_database(conn, household):
    savings = run(conn)["sections"]["assets"]["nodes"][0]
    assert [(c["label"], c["value"]) for c in savings["children"]] == [("Test dollar savings", 150_000), ("Test euro savings", 150_000)]   # equal: by name
    checking = run(conn)["sections"]["assets"]["nodes"][1]
    assert [c["label"] for c in checking["children"]] == ["Test empty", "Test euro overdraft"]                                            # 0 before -62,506


# -- what is drawn and what is only listed --

def test_an_overdrawn_account_and_one_with_no_balance_have_no_area_but_stay_in_the_hierarchy_and_in_the_totals(conn, household):
    result = run(conn)
    over, empty = find(result["sections"]["assets"]["nodes"], f"account_{household['eur_over']}"), find(result["sections"]["assets"]["nodes"], f"account_{household['empty']}")
    assert (over["value"], over["size"], empty["value"], empty["size"]) == (-62_506, 0, 0, 0)
    checking = find(result["sections"]["assets"]["nodes"], f"type_{type_id(conn, 'Checking')}")
    assert checking["size"] == 0 and checking["value"] == -62_506                       # a type of nothing drawable has no area, and is still counted


def test_a_drawable_account_has_an_area_equal_to_its_value(conn, household):
    for leaf in leaves(run(conn)["sections"]["assets"]["nodes"] + run(conn)["sections"]["liabilities"]["nodes"]):
        assert leaf["size"] == max(leaf["value"], 0)


def test_an_overpaid_liability_has_no_area_either(conn, household):
    add_balance(conn, household["usd_card"], "2026-06-01", -1_000)
    conn.commit()
    card = find(run(conn)["sections"]["liabilities"]["nodes"], f"account_{household['usd_card']}")
    assert (card["value"], card["size"]) == (-1_000, 0)


# -- notes, links and colours --

def test_an_account_says_which_balance_it_stands_on_in_the_persons_own_date_format_or_that_it_has_none(conn, household):
    nodes = run(conn)["sections"]["assets"]["nodes"]
    assert find(nodes, f"account_{household['usd_sav']}")["note"] == f"Balance {locales.speaking().date('2026-03-01')}"
    assert find(nodes, f"account_{household['eur_sav']}")["note"] == f"Balance {locales.speaking().date('2026-04-01')}"
    assert find(nodes, f"account_{household['empty']}")["note"] == "No balance"
    assert find(nodes, f"type_{type_id(conn, 'Savings')}")["note"] == "2 accounts"
    assert find(nodes, f"type_{type_id(conn, 'Checking')}")["note"] == "2 accounts"


def test_an_account_takes_the_colour_of_its_type_and_opens_its_page(conn, household):
    result = run(conn)
    savings = type_id(conn, "Savings")
    for node in result["sections"]["assets"]["nodes"] + result["sections"]["liabilities"]["nodes"]:
        assert node["colour"] == {"kind": "account_type", "id": int(node["id"].removeprefix("type_"))}
        for leaf in node["children"]:
            assert leaf["colour"] == node["colour"]
    leaf = find(result["sections"]["assets"]["nodes"], f"account_{household['usd_sav']}")
    assert leaf["link"] == {"to": "account", "id": household["usd_sav"]} and leaf["colour"]["id"] == savings


# -- states --

def test_a_missing_exchange_rate_stops_the_whole_report_and_says_which_without_partial_figures(conn, household):
    currencies.update_currency(op(conn), "GBP", True, "2020-01-01", TODAY)
    add_balance(conn, add_foreign(conn, "Test pound savings", "GBP", "Savings"), "2026-03-01", 10_000)      # no pound rate has ever been entered
    conn.commit()
    with pytest.raises(ReportUnavailable) as raised:
        run(conn)
    assert raised.value.reason == "missing_rates" and raised.value.facts == {"missing_rates": ["GBP"]}


def test_no_accounts_at_all_is_one_report_wide_note_and_zero_figures(conn):
    result = run(conn)
    got = items(result)
    assert (got["assets"]["value"], got["liabilities"]["value"], got["net_worth"]["value"]) == (0, 0, 0)
    assert got["net_worth"]["note"] == "0 accounts" and result["sections"]["assets"] == {"nodes": []}
    assert [(n["code"], n.get("section")) for n in result["notes"]] == [("no_data", None)]


def test_no_liabilities_is_a_note_on_that_section_only(conn):
    add_balance(conn, add_account(conn, "Test only savings", 1, "Savings"), "2026-03-01", 10_000)
    conn.commit()
    result = run(conn)
    assert result["sections"]["liabilities"] == {"nodes": []} and items(result)["liabilities"]["note"] == "0 accounts"
    assert [(n["code"], n["section"]) for n in result["notes"]] == [("no_liabilities", "liabilities")]


def test_no_assets_is_a_note_on_that_section_only(conn):
    add_balance(conn, add_account(conn, "Test only card", 2, "Credit card"), "2026-03-01", 10_000)
    conn.commit()
    assert [(n["code"], n["section"]) for n in run(conn)["notes"]] == [("no_assets", "assets")]


def test_a_single_account_counts_as_one_account_not_one_accounts(conn):
    add_balance(conn, add_account(conn, "Test only savings", 1, "Savings"), "2026-03-01", 10_000)
    conn.commit()
    assert items(run(conn))["assets"]["note"] == "1 account"


def test_a_date_before_any_balance_lists_every_account_with_no_balance(conn, household):
    result = run(conn, "2025-01-01")
    got = items(result)
    assert (got["assets"]["value"], got["liabilities"]["value"]) == (0, 0) and got["net_worth"]["note"] == "6 accounts"
    assert all(leaf["note"] == "No balance" for leaf in leaves(result["sections"]["assets"]["nodes"] + result["sections"]["liabilities"]["nodes"]))


# -- filters --

def test_a_filter_changes_the_figures_and_both_lists_together_and_the_counts_still_add_up(conn, household):
    savings = type_id(conn, "Savings")
    result = run(conn, filters=[{"field": "type", "operator": "is", "value": savings}])
    got = items(result)
    assert (got["assets"]["value"], got["liabilities"]["value"], got["net_worth"]["value"]) == (300_000, 0, 300_000)
    assert [n["label"] for n in result["sections"]["assets"]["nodes"]] == ["Savings"] and result["sections"]["liabilities"] == {"nodes": []}
    assert (got["assets"]["note"], got["net_worth"]["note"]) == ("2 accounts", "2 accounts")
    assert result["filters"] == [{"field": "type", "operator": "is", "value": savings}]


def test_a_filter_that_matches_nothing_is_the_no_data_state(conn, household):
    result = run(conn, filters=[{"field": "name", "operator": "equals", "value": "No such account"}])
    assert [n["code"] for n in result["notes"]] == ["no_data"] and items(result)["net_worth"]["value"] == 0


def test_a_date_condition_is_refused_because_the_report_has_its_own_date(conn, household):
    for field in ("created_at", "type.created_at"):
        with pytest.raises(ReportInputError):
            run(conn, filters=[{"field": field, "operator": "is_empty"}])


def test_with_no_filters_sent_it_opens_with_none(conn, household):
    assert run(conn)["filters"] == [] and describe_filters(conn)["enabled"] is True


def describe_filters(conn):
    return engine.describe(REPORT, TODAY, conn)["filters"]
