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

# Every live account with its last balance and how old it is. Open accounts are the shared default filter (migration 0025), which is
# data, so it is not here; and the page is the heading, the Add account button and the table.
ACCOUNTS = ListDef(
    "accounts", "account_summaries",
    ("name", "type.class", "type", "currency", "last_cents", "reporting_value", "last_date", "days_since", "is_stale", "balance_count"),
    ("name", "asc"),
)

# The currency catalog, for admins: about 150 rows, so a page shows 100. Whether a currency is enabled and how many accounts use it
# are columns, so "enabled" and "in use" are filters a person makes. A currency's code opens its page, where it is switched on or off
# and its rates are kept.
CURRENCIES = ListDef(
    "currencies", "currency_summaries",
    ("code", "name", "minor_units", "is_enabled", "account_count"),
    ("code", "asc"), page_size=100, admin_only=True,
)

# One account's balances, newest first, twelve to a page: the account page's history. A fixed list: a person cannot filter, search,
# group, choose its columns or its page size, or export it, and nothing is saved for it. The page names the account, and the list
# is only that account's live balances. The date opens the balance's page, where it is changed or deleted.
ACCOUNT_BALANCES = ListDef(
    "account_balances", "account_balances", ("as_of_date", "amount_cents", "change_cents"), ("as_of_date", "desc"),
    scope="b.account_id = :account", params=("account",), page_size=12, customisable=False,
)

loader.register(BALANCES)
loader.register(ACCOUNT_BALANCES)
loader.register(ACCOUNTS)
loader.register(CURRENCIES)
