"""The Net Worth Bridge report: figures checked by hand on synthetic data, exact reconciliation with the Dashboard's net worth, and every state
the design names. Synthetic data only."""

from datetime import date

import pytest

from conftest import add_account, add_balance, op
from northstar import currencies, locales, networth, rates
from northstar.reportdefs.net_worth_bridge import NET_WORTH_BRIDGE as REPORT, _percent
from northstar.reports import engine, loader
from northstar.reports.errors import ReportInputError, ReportUnavailable

TODAY = date(2026, 11, 11)
ADMIN = {"id": 1, "is_admin": True}
SYSTEM = "(SELECT id FROM users WHERE is_system = 1)"
OPENING, CLOSING = "2026-05-31", "2026-06-30"
fmt = locales.speaking().date


def add_foreign(conn, name, code, type_name):
    return conn.execute(
        "INSERT INTO accounts (name, type_id, currency_id, created_by, updated_by) VALUES "
        f"(?, (SELECT id FROM account_types WHERE name = ?), (SELECT id FROM currencies WHERE code = ?), {SYSTEM}, {SYSTEM})",
        (name, type_name, code)).lastrowid


@pytest.fixture
def household(conn):
    """Six accounts. The euro rate is 1.10 until 31 May and 1.25 from 1 June 2026, so from 31 May to 30 June:

    usd_sav   Savings, dollars:    1,500.00 on 1 Mar                     asset       150,000 -> 150,000   change 0 (left out)
    eur_sav   Savings, euros:      1,200.00 on 1 Apr                     asset       132,000 -> 150,000   change +18,000 (only the rate moved)
    eur_over  Checking, euros:      -500.05 on 15 Feb                    asset       -55,006 ->  -62,506   change  -7,500 (half cents away from zero)
    empty     Checking, dollars:     no balance                          asset             0 ->        0   change 0 (left out)
    usd_card  Credit card, dollars:   250.50 on 1 Feb                    liability   -25,050 ->  -25,050   change 0 (left out)
    eur_loan  Loan, euros:            500.05 on 15 Feb                   liability   -55,006 ->  -62,506   change  -7,500
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


def run(conn, opening=OPENING, closing=CLOSING, filters="omit"):
    body = {"parameters": {"opening": opening, "closing": closing}}
    if filters != "omit":
        body["filters"] = filters
    return engine.calculate(conn, REPORT, ADMIN, body, TODAY)


def items(result):
    return {item["key"]: item for item in result["sections"]["headline"]["items"]}


def nodes(result):
    return result["sections"]["changes"]["nodes"]


def find(tree, ident):
    for node in tree:
        if node["id"] == ident:
            return node
        found = find(node.get("children", []), ident)
        if found:
            return found
    return None


def leaves(tree):
    return [leaf for node in tree for leaf in (leaves(node["children"]) if "children" in node else [node])]


# -- what it is --

def test_it_is_registered_and_opens_with_closing_today_and_opening_a_year_earlier_and_no_filters(conn):
    assert loader.get_report("net_worth_bridge") is REPORT
    assert (REPORT.title, REPORT.description) == ("Net Worth Bridge", "Why your net worth changed.")
    described = engine.describe(REPORT, TODAY, conn)
    assert [(p["key"], p["default"]) for p in described["parameters"]] == [("opening", "2025-11-11"), ("closing", "2026-11-11")]
    assert [(s["key"], s["kind"], s["view"], s["expanded"], s["columns"]) for s in described["sections"]] == [
        ("headline", "summary", "tiles", True, 12), ("bridge", "hierarchy", "waterfall", False, 12), ("changes", "hierarchy", "table", False, 12)]
    assert described["filters"]["enabled"] is True and described["filters"]["defaults"] == []


def test_the_closing_date_must_be_after_the_opening_date_and_not_in_the_future(conn, household):
    for opening, closing in ((CLOSING, CLOSING), (CLOSING, OPENING), (OPENING, "2026-11-12")):
        with pytest.raises(ReportInputError):
            run(conn, opening, closing)


# -- the figures, by hand --

def test_the_headline_is_opening_change_and_closing_with_their_dates_and_the_change_as_a_share(conn, household):
    got = items(run(conn))
    assert (got["opening"]["label"], got["change"]["label"], got["closing"]["label"]) == ("Opening balance", "Change", "Closing balance")
    assert (got["opening"]["value"], got["change"]["value"], got["closing"]["value"]) == (146_938, 3_000, 149_938)
    assert (got["opening"]["note"], got["change"]["note"], got["closing"]["note"]) == (fmt(OPENING), "+2.0%", fmt(CLOSING))


def test_the_change_figure_says_it_is_a_change_so_the_page_shows_its_sign_and_direction(conn, household):
    got = items(run(conn))
    assert got["change"]["signed"] is True
    assert "signed" not in got["opening"] and "signed" not in got["closing"]


def test_the_chart_draws_the_same_nodes_as_the_table_so_both_reconcile_to_the_same_totals(conn, household):
    result = run(conn)
    bridge = result["sections"]["bridge"]
    assert bridge["nodes"] == result["sections"]["changes"]["nodes"]
    assert (bridge["opening"], bridge["closing"]) == (items(result)["opening"]["value"], items(result)["closing"]["value"])
    assert bridge["opening"] + sum(n["value"] for n in bridge["nodes"]) == bridge["closing"]
    # An account that did not change is in the totals and in no node, so the chart starts from the whole and not from the sum of what changed.
    assert sum(n["opening"] for n in bridge["nodes"]) != bridge["opening"]


def test_the_chart_is_empty_and_the_table_is_empty_when_nothing_changed(conn, household):
    result = run(conn, "2026-06-10", "2026-06-30")
    got = items(result)
    assert result["sections"]["bridge"] == {"nodes": [], "opening": got["opening"]["value"], "closing": got["closing"]["value"]}
    assert result["sections"]["changes"] == {"nodes": []}


def test_opening_and_closing_equal_the_dashboards_net_worth_on_both_dates(conn, household):
    for opening, closing in (("2026-02-20", "2026-05-31"), (OPENING, CLOSING), ("2026-01-05", "2026-11-11")):
        got = items(run(conn, opening, closing))
        assert got["opening"]["value"] == networth.net_worth_on(conn, date.fromisoformat(opening))["net_worth"], (opening, closing)
        assert got["closing"]["value"] == networth.net_worth_on(conn, date.fromisoformat(closing))["net_worth"], (opening, closing)


def test_opening_plus_every_change_is_closing_exactly_and_every_parent_is_the_sum_of_its_accounts(conn, household):
    result = run(conn)
    got = items(result)
    assert got["opening"]["value"] + sum(n["value"] for n in nodes(result)) == got["closing"]["value"]
    for node in nodes(result):
        assert node["value"] == sum(c["value"] for c in node["children"]) and node["closing"] - node["opening"] == node["value"]
        assert all(c["closing"] - c["opening"] == c["value"] for c in node["children"])


def test_each_account_is_its_closing_value_minus_its_opening_value_signed_by_class_and_each_half_cent_rounds_away_from_zero(conn, household):
    result = run(conn)
    over = find(nodes(result), f"account_{household['eur_over']}")
    loan = find(nodes(result), f"account_{household['eur_loan']}")
    savings = find(nodes(result), f"account_{household['eur_sav']}")
    assert (over["opening"], over["closing"], over["value"]) == (-55_006, -62_506, -7_500)          # an overdrawn asset falling is a loss
    assert (loan["opening"], loan["closing"], loan["value"]) == (-55_006, -62_506, -7_500)          # a liability rising is a loss, and is stored positive
    assert (savings["opening"], savings["closing"], savings["value"]) == (132_000, 150_000, 18_000)


def test_a_reduced_debt_is_a_positive_change(conn, household):
    add_balance(conn, household["usd_card"], "2026-06-15", 5_050)
    conn.commit()
    card = find(nodes(run(conn)), f"account_{household['usd_card']}")
    assert (card["opening"], card["closing"], card["value"]) == (-25_050, -5_050, 20_000)


# -- what is left out, and the order --

def test_an_account_that_did_not_change_is_never_shown_and_nor_is_a_type_with_none_left(conn, household):
    result = run(conn)
    labels = {leaf["label"] for leaf in leaves(nodes(result))}
    assert labels == {"Test euro savings", "Test euro overdraft", "Test euro loan"}
    assert [n["label"] for n in nodes(result)] == ["Checking", "Loan", "Savings"]                     # Credit card had nothing that changed
    assert [leaf["label"] for leaf in find(nodes(result), f"type_{type_of(conn, 'Savings')}")["children"]] == ["Test euro savings"]
    assert items(result)["opening"]["note"] == fmt(OPENING)


def type_of(conn, name):
    return conn.execute("SELECT id FROM account_types WHERE name = ?", (name,)).fetchone()[0]


def test_a_type_whose_accounts_offset_to_zero_stays_because_its_accounts_changed(conn, household):
    a, b = add_account(conn, "Test fund a", 1, "Other investment"), add_account(conn, "Test fund b", 1, "Other investment")
    for account, first, second in ((a, 10_000, 15_000), (b, 15_000, 10_000)):
        add_balance(conn, account, "2026-05-01", first)
        add_balance(conn, account, "2026-06-15", second)
    conn.commit()
    other = find(nodes(run(conn)), f"type_{type_of(conn, 'Other investment')}")
    assert other["value"] == 0 and [(c["label"], c["value"]) for c in other["children"]] == [("Test fund a", 5_000), ("Test fund b", -5_000)]


def test_types_and_accounts_are_alphabetical_whatever_their_size(conn, household):
    add_balance(conn, household["usd_sav"], "2026-06-10", 900_000)
    conn.commit()
    result = run(conn)
    assert [n["label"] for n in nodes(result)] == sorted((n["label"] for n in nodes(result)), key=str.casefold)
    savings = find(nodes(result), f"type_{type_of(conn, 'Savings')}")
    assert [c["label"] for c in savings["children"]] == ["Test dollar savings", "Test euro savings"]   # the larger change is first by name, not by size


# -- where the figures come from --

def test_an_account_says_which_balances_it_rests_on_or_that_only_the_rate_moved_or_that_there_was_none(conn, household):
    add_balance(conn, household["usd_sav"], "2026-06-10", 160_000)
    new = add_account(conn, "Test new account", 1, "Savings")
    add_balance(conn, new, "2026-06-12", 70_000)
    conn.commit()
    result = run(conn)
    assert find(nodes(result), f"account_{household['usd_sav']}")["note"] == f"{fmt('2026-03-01')} → {fmt('2026-06-10')}"
    assert find(nodes(result), f"account_{household['eur_sav']}")["note"] == f"Balance {fmt('2026-04-01')}; only the exchange rate changed"
    added = find(nodes(result), f"account_{new}")
    assert added["note"] == f"No balance on {fmt(OPENING)}" and (added["opening"], added["closing"], added["value"]) == (0, 70_000, 70_000)
    assert find(nodes(result), f"type_{type_of(conn, 'Savings')}")["note"] == "3 accounts"


def test_an_account_links_to_its_page_and_the_section_says_a_change_includes_the_rate(conn, household):
    result = run(conn)
    assert find(nodes(result), f"account_{household['eur_sav']}")["link"] == {"to": "account", "id": household["eur_sav"]}
    assert [(n["code"], n["section"]) for n in result["notes"]] == [("includes_exchange_rates", "changes")]


# -- states --

def test_a_missing_rate_on_either_date_stops_the_whole_report(conn, household):
    currencies.update_currency(op(conn), "GBP", True, "2020-01-01", TODAY)
    add_balance(conn, add_foreign(conn, "Test pound savings", "GBP", "Savings"), "2026-06-15", 10_000)       # no pound rate has ever been entered
    conn.commit()
    for opening, closing in ((OPENING, CLOSING), ("2026-06-20", "2026-06-30")):
        with pytest.raises(ReportUnavailable) as raised:
            run(conn, opening, closing)
        assert raised.value.reason == "missing_rates" and raised.value.facts == {"missing_rates": ["GBP"]}


def test_nothing_changing_is_equal_totals_an_empty_table_and_one_general_note(conn, household):
    result = run(conn, "2026-06-10", "2026-06-30")
    got = items(result)
    assert got["opening"]["value"] == got["closing"]["value"] and got["change"]["value"] == 0 and got["change"]["note"] == "0.0%"
    assert nodes(result) == [] and [(n["code"], n.get("section")) for n in result["notes"]] == [("unchanged", None)]


def test_no_accounts_at_all_is_no_data(conn):
    result = run(conn)
    assert [(n["code"], n.get("section")) for n in result["notes"]] == [("no_data", None)] and nodes(result) == []
    assert items(result)["opening"]["value"] == items(result)["closing"]["value"] == 0 and "note" not in items(result)["change"]


def test_a_filter_changes_the_figures_and_the_table_together(conn, household):
    savings = type_of(conn, "Savings")
    result = run(conn, filters=[{"field": "type", "operator": "is", "value": savings}])
    got = items(result)
    assert (got["opening"]["value"], got["change"]["value"], got["closing"]["value"]) == (282_000, 18_000, 300_000)
    assert [n["label"] for n in nodes(result)] == ["Savings"] and result["filters"] == [{"field": "type", "operator": "is", "value": savings}]


def test_a_filter_that_matches_nothing_is_no_data(conn, household):
    result = run(conn, filters=[{"field": "name", "operator": "equals", "value": "No such account"}])
    assert [n["code"] for n in result["notes"]] == ["no_data"]


def test_a_date_condition_is_refused_because_the_report_has_its_own_dates(conn, household):
    for field in ("created_at", "type.created_at"):
        with pytest.raises(ReportInputError):
            run(conn, filters=[{"field": field, "operator": "is_empty"}])


# -- the share shown beside the change --

@pytest.mark.parametrize("change, opening, text", [
    (3_000, 146_938, "+2.0%"), (-3_000, 146_938, "−2.0%"), (0, 5, "0.0%"), (50, -100, "+50.0%"), (-50, -100, "−50.0%"),
    (1, 3, "+33.3%"), (1, 8, "+12.5%"), (1, 16, "+6.3%"), (5, 0, None),
])
def test_the_share_has_the_changes_sign_and_one_decimal_and_none_when_there_was_nothing_to_compare_with(change, opening, text):
    assert _percent(change, opening) == text
