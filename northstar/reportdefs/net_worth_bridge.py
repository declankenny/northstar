"""Net Worth Bridge: why net worth changed between two dates.

An opening date and a closing date (closing strictly after opening, neither in the future). Each account's change is its signed value on
the closing date minus its signed value on the opening date, each from the shared positions (`northstar.positions`: the latest balance
and rate on or before the date, an account with no balance counting zero, an asset adding and a liability subtracting, so a reduced debt
is a positive change). A type's change is the sum of its accounts', so opening net worth plus the changes equals closing net worth
exactly, in integer minor units, and both totals equal the Dashboard's net worth for the same date and accounts.

* An account whose change is zero is never in the result, and neither is a type with no account left. A type whose accounts offset to zero
  stays, because its accounts changed.
* A change is both the change in the balance and the change in exchange rates. They are not split: splitting them exactly would need an
  unexplained rounding adjustment. A note on the section says so.
* The same nodes are drawn twice: as a waterfall (`bridge`) and as a table (`changes`). The waterfall also carries the opening and closing
  net worth, which are not the sums of the nodes' (an account that did not change is in them and in no node).
* Types and accounts are alphabetical. Each node carries its opening and closing amounts, and an account says which balances they rest
  on, so a table or a chart needs no arithmetic of its own.
* The report is filtered by every account field except dates (it has dates of its own) and opens with no filters.
"""

from decimal import ROUND_HALF_UP, Decimal

from northstar import locales
from northstar.positions import account_positions
from northstar.reportdefs.common import account_names, accounts_text
from northstar.reports import loader, params
from northstar.reports.reportdef import FilterDecl, ReportContext, ReportDef, ReportResult
from northstar.reports.sections import SectionDef

KEY = "net_worth_bridge"


def _percent(change: int, opening: int) -> str | None:
    """The change as a share of the size of the opening net worth, to one decimal place, for display only (never used in a figure)."""
    if opening == 0:
        return None
    share = (Decimal(abs(change)) * 100 / Decimal(abs(opening))).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return f"{'+' if change > 0 else '−' if change < 0 else ''}{share}%"       # the sign is the change's, whatever the opening net worth's


def _balances_note(before, after) -> str:
    """Which balances an account's opening and closing figures rest on."""
    date = locales.speaking().date
    if before.balance is None:
        return f"No balance on {date(before.day)}"
    if before.balance.id == after.balance.id:
        return f"Balance {date(before.balance.as_of_date)}; only the exchange rate changed"
    return f"{date(before.balance.as_of_date)} → {date(after.balance.as_of_date)}"


def calculate(ctx: ReportContext) -> ReportResult:
    opening_day, closing_day = ctx.parameters["opening"], ctx.parameters["closing"]
    both = account_positions(ctx.conn, ctx.population, [opening_day, closing_day])           # a missing rate on either day stops the whole report
    before, after = {p.account_id: p for p in both[opening_day]}, {p.account_id: p for p in both[closing_day]}
    names = account_names(ctx)
    opening_total = sum(p.signed_value for p in before.values())
    closing_total = sum(p.signed_value for p in after.values())
    types: dict[int, tuple[str, list[dict]]] = {}
    for account_id, start in before.items():
        end = after[account_id]
        change = end.signed_value - start.signed_value
        if change == 0:
            continue
        name, type_id, type_name = names[account_id]
        types.setdefault(type_id, (type_name, []))[1].append(
            {"id": f"account_{account_id}", "label": name, "value": change, "opening": start.signed_value, "closing": end.signed_value,
             "note": _balances_note(start, end), "link": {"to": "account", "id": account_id}})
    nodes = []
    for type_id, (type_name, leaves) in types.items():
        leaves.sort(key=lambda n: (n["label"].casefold(), n["id"]))
        nodes.append({"id": f"type_{type_id}", "label": type_name, "value": sum(n["value"] for n in leaves), "note": accounts_text(len(leaves)),
                      "opening": sum(n["opening"] for n in leaves), "closing": sum(n["closing"] for n in leaves), "children": leaves})
    nodes.sort(key=lambda n: (n["label"].casefold(), n["id"]))
    change_total = closing_total - opening_total
    date = locales.speaking().date
    change_item = {"key": "change", "label": "Change", "kind": "money", "value": change_total, "signed": True}
    if (percent := _percent(change_total, opening_total)) is not None:
        change_item["note"] = percent
    headline = {"items": [
        {"key": "opening", "label": "Opening balance", "kind": "money", "value": opening_total, "note": date(opening_day)},
        change_item,
        {"key": "closing", "label": "Closing balance", "kind": "money", "value": closing_total, "note": date(closing_day)},
    ]}
    notes = []
    if not before:
        notes.append({"code": "no_data", "text": "There are no accounts to show."})
    elif not nodes:
        notes.append({"code": "unchanged", "text": "Net worth is the same on both dates: nothing changed."})
    else:
        notes.append({"code": "includes_exchange_rates", "section": "changes",
                      "text": "A change includes the change in the balance and the change in exchange rates."})
    return ReportResult({"headline": headline, "bridge": {"nodes": nodes, "opening": opening_total, "closing": closing_total}, "changes": {"nodes": nodes}}, notes)


NET_WORTH_BRIDGE = ReportDef(
    KEY, "Net Worth Bridge", "Why your net worth changed.", params.ordered_pair(),
    (SectionDef("headline", "summary", "tiles", "Net worth"),
     SectionDef("bridge", "hierarchy", "waterfall", "How net worth changed", expanded=False),
     SectionDef("changes", "hierarchy", "table", "Detail", expanded=False)),
    calculate, filters=FilterDecl(exclude_dates=True))

loader.register(NET_WORTH_BRIDGE)
