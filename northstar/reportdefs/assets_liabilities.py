"""Assets & Liabilities: what you own and what you owe, on one date.

The proof of the reporting framework. One as-at date (today unless asked, never in the future), the household's accounts at their
positions on that date (`northstar.positions`, so every figure equals the Dashboard's net worth for the same date and accounts), and
three sections: the headline figures, and two hierarchies, assets and liabilities, each by account type and then account.

* Value is signed and exact. A parent is the sum of its children, so a type's value and account count include every account in it and
  the lists add up to the headline figures.
* Area (`size`) is the part of a value a block can show: an overdrawn asset, an overpaid liability and an account with no balance have
  none. Such an account is kept in the hierarchy (and so in the page's list, marked "not in the chart") and is simply not drawn.
* A node's colour comes from its account type, so an account is the colour of its type. An account's note says which balance the figure
  rests on, or that there is none; a type's says how many accounts it holds (the page does not know the noun).
* With no accounts at all, the report says `no_data` and the page shows its empty state, with Clear filters when there are any.
* The report is filtered by every account field except dates (it has a date of its own) and opens with no filters.
"""

from northstar import locales
from northstar.networth import ASSET, LIABILITY
from northstar.reportdefs.common import account_names, accounts_text
from northstar.positions import AccountPosition, account_positions, totals
from northstar.reports import loader, params
from northstar.reports.reportdef import FilterDecl, ReportContext, ReportDef, ReportResult
from northstar.reports.sections import SectionDef

KEY = "assets_liabilities"
TYPE_KIND = "account_type"


def _balance_note(position: AccountPosition) -> str:
    if position.balance is None:
        return "No balance"
    return f"Balance {locales.speaking().date(position.balance.as_of_date)}"


def _hierarchy(positions: list[AccountPosition], names: dict[int, tuple[str, int, str]]) -> dict:
    """Account types, each holding its accounts, the largest first (by value, then name, so the order never depends on the database)."""
    types: dict[int, tuple[str, list[dict]]] = {}
    for position in positions:
        name, type_id, type_name = names[position.account_id]
        leaf = {"id": f"account_{position.account_id}", "label": name, "value": position.value, "size": max(position.value, 0),
                "note": _balance_note(position), "colour": {"kind": TYPE_KIND, "id": type_id},
                "link": {"to": "account", "id": position.account_id}}
        types.setdefault(type_id, (type_name, []))[1].append(leaf)
    nodes = []
    for type_id, (type_name, leaves) in types.items():
        leaves.sort(key=lambda n: (-n["value"], n["label"].casefold(), n["id"]))
        nodes.append({"id": f"type_{type_id}", "label": type_name, "value": sum(n["value"] for n in leaves), "note": accounts_text(len(leaves)),
                      "colour": {"kind": TYPE_KIND, "id": type_id}, "children": leaves})
    nodes.sort(key=lambda n: (-n["value"], n["label"].casefold(), n["id"]))
    return {"nodes": nodes}


def calculate(ctx: ReportContext) -> ReportResult:
    day = ctx.parameters["as_at"]
    positions = list(account_positions(ctx.conn, ctx.population, [day])[day])        # a missing rate stops the whole report
    names = account_names(ctx)
    assets = [p for p in positions if p.class_name == ASSET]
    liabilities = [p for p in positions if p.class_name == LIABILITY]
    figures = totals(positions)
    headline = {"items": [
        {"key": "assets", "label": "Assets", "kind": "money", "value": figures.assets, "note": accounts_text(len(assets))},
        {"key": "liabilities", "label": "Liabilities", "kind": "money", "value": figures.liabilities, "note": accounts_text(len(liabilities))},
        {"key": "net_worth", "label": "Net worth", "kind": "money", "value": figures.net_worth, "note": accounts_text(len(positions))},
    ]}
    notes = []
    if not positions:
        notes.append({"code": "no_data", "text": "There are no accounts to show."})
    else:
        if not assets:
            notes.append({"code": "no_assets", "text": "No assets.", "section": "assets"})
        if not liabilities:
            notes.append({"code": "no_liabilities", "text": "No liabilities.", "section": "liabilities"})
    return ReportResult({"headline": headline, "assets": _hierarchy(assets, names), "liabilities": _hierarchy(liabilities, names)}, notes)


ASSETS_AND_LIABILITIES = ReportDef(
    KEY, "Assets & Liabilities", "What you own and what you owe.", params.as_of(),
    (SectionDef("headline", "summary", "tiles", "Net worth"),
     SectionDef("assets", "hierarchy", "treemap", "Assets", sized=True, columns=6),
     SectionDef("liabilities", "hierarchy", "treemap", "Liabilities", sized=True, columns=6)),
    calculate, filters=FilterDecl(exclude_dates=True))

loader.register(ASSETS_AND_LIABILITIES)
