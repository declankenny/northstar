"""What more than one report needs of the accounts it counts. Plain functions; a report imports what it uses."""

import json

from northstar.reports.reportdef import ReportContext


def accounts_text(count: int) -> str:
    return "1 account" if count == 1 else f"{count:,} accounts"


def account_names(ctx: ReportContext) -> dict[int, tuple[str, int, str]]:
    """Each account's name, its type's id and its type's name, for the accounts counted."""
    ids = json.dumps(list(ctx.population.account_ids()))
    return {row["id"]: (row["name"], row["type_id"], row["type_name"]) for row in ctx.conn.execute(
        "SELECT a.id, a.name, a.type_id, t.name AS type_name FROM live_accounts a JOIN account_types t ON t.id = a.type_id "
        "WHERE a.id IN (SELECT value FROM json_each(?))", (ids,))}
