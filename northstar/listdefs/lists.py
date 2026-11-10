"""The lists Northstar offers. Each is only data: which table its rows are of, its default columns and its default sort. The framework
reads a definition through `northstar.lists.loader` and never imports one, so adding a list edits no framework file."""

from northstar.lists import loader
from northstar.lists.listdef import ListDef

# Every live balance across all accounts, newest first. The source is the view of live balances with each one's value in the system
# currency, so a deleted account's balances are never listed. A column of the account is reached through the relation to it, and
# the column's header is its own name ("Type", "Currency"), the way the framework names a related column.
BALANCES = ListDef(
    "balances", "live_balance_values",
    ("as_of_date", "account", "account.type", "amount_cents", "account.currency", "reporting_value", "note"),
    ("as_of_date", "desc"),
)

loader.register(BALANCES)
