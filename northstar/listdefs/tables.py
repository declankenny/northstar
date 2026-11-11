"""What the list framework may offer from each of Northstar's tables. This is data: the engine (northstar/lists) knows none of it.

A table has an entry here, or is named in NOT_LISTABLE with the reason, and a test fails for a table that is neither, so adding
a table to the database forces the decision. Tables the application owns for itself (`sys_`) and the loaded catalogs (`ref_`)
are never lists.

A column that is not offered here is not a column of any list. The deleted flag, the system flag and the password hash are not
offered, and are also named as denied so that offering one by mistake fails a test.

A list that reads a view that leaves out deleted rows (`live_accounts`) sets it as its source, and a column that has to be worked out
is a column of a view that has an entry of its own and is based on the table (`live_balance_values`). A relation to
`accounts` or `account_types` from another table goes to the table itself, so a list must start from a source that already
excludes what should not be seen.
"""

from northstar.lists.kinds import Date, Integer, ScaledBy, Text, Timestamp, YesNo
from northstar.lists.registry import FieldDef, TableDef


def _text(searchable=False, label=None):
    return FieldDef(Text(), searchable=searchable, label=label)


def _audit():
    """The creation and change times every household table has. Who made them are relations to users."""
    return {"created_at": FieldDef(Timestamp()), "updated_at": FieldDef(Timestamp())}


TABLES = {
    "account_classes": TableDef("account_classes", "name", {"name": _text(), **_audit()}),
    "account_types": TableDef("account_types", "name", {
        "name": _text(True), "stale_after_days": FieldDef(Integer(), label="Stale after (days)"), **_audit()}),
    "accounts": TableDef("accounts", "name", {
        "name": _text(True), "is_open": FieldDef(YesNo(), label="Open"), "notes": _text(True), **_audit()},
        denied=frozenset({"deleted"}), record_page="/accounts/{id}"),
    # The live accounts with the figures that are worked out for each (migration 0025): its balance count, last balance and date, that
    # balance's value in the system currency, its age and whether it is stale. It is a view of `accounts`, so it has that table's key
    # and relations, and it leaves out a deleted account itself.
    "account_summaries": TableDef("account_summaries", "name", {
        "name": _text(True, "Account"), "is_open": FieldDef(YesNo(), label="Open"), "notes": _text(True),
        "balance_count": FieldDef(Integer(), label="Balances"),
        "last_date": FieldDef(Date(), label="Balance date"),
        "last_cents": FieldDef(ScaledBy(scale_from=("currency", "minor_units"), unit_from=("currency", "code")),
                               label="Last balance", groupable=False),
        "reporting_value": FieldDef(ScaledBy(scale_from=("reporting_scale",), unit_from=("reporting_unit",)),
                                    label="Reporting value", groupable=False),
        "days_since": FieldDef(Integer(), label="Balance age (days)"),
        "is_stale": FieldDef(YesNo(), label="Stale"), **_audit()},
        denied=frozenset({"deleted"}), based_on="accounts", record_page="/accounts/{id}"),
    # The balances of live accounts, each with its value in the system currency (migration 0020). It is a view of `balances`, so
    # it has that table's key and relations, and the covering test counts it for that table.
    "live_balance_values": TableDef("live_balance_values", "as_of_date", {
        "as_of_date": FieldDef(Date(), label="Date"),
        "amount_cents": FieldDef(ScaledBy(scale_from=("account", "currency", "minor_units"),
                                          unit_from=("account", "currency", "code")), label="Value", groupable=False),
        "reporting_value": FieldDef(ScaledBy(scale_from=("reporting_scale",), unit_from=("reporting_unit",)),
                                    label="Reporting value", groupable=False),       # the same number in two currencies would be one group
        "note": _text(True), "source": _text(), **_audit()},
        denied=frozenset({"version"}), based_on="balances", record_page="/balances/{id}"),
    # The currency catalog with how many live accounts use each (migration 0026), for the admin Currencies list. It is a view of
    # `currencies`, so it has that table's key and relations; it does not know which currency is the system currency.
    "currency_summaries": TableDef("currency_summaries", "code", {
        "code": _text(True), "name": _text(True), "minor_units": FieldDef(Integer(), label="Decimal places"),
        "is_enabled": FieldDef(YesNo(), label="Enabled"), "rates_start": FieldDef(Date(), label="Rates start"),
        "account_count": FieldDef(Integer(), label="Accounts"), **_audit()},
        based_on="currencies", record_page="/currencies/{value}", record_page_for="admin"),
    "currencies": TableDef("currencies", "code", {
        "code": _text(), "name": _text(True), "minor_units": FieldDef(Integer(), label="Decimal places"),
        "is_enabled": FieldDef(YesNo(), label="Enabled"), "rates_start": FieldDef(Date(), label="Rates start"), **_audit()},
        record_page="/currencies/{value}", record_page_for="admin"),      # a currency's page is for admins
    # Users show their name and can be walked into by no other table: a person's email is not offered from a relation.
    "users": TableDef("users", "display_name", {
        "display_name": _text(True, "Name"), "email": _text(True), "is_admin": FieldDef(YesNo(), label="Admin"), **_audit()},
        walkable=False, denied=frozenset({"password_hash", "is_system", "deleted"})),
}

NOT_LISTABLE = {
    "exchange_rates": "a currency's rates are listed on its own page, which has not moved onto the list framework",
    "system_properties": "the System properties page is a settings editor, not a list",
    "user_identities": "bindings to an identity provider are never shown as a list",
    "user_list_prefs": "a person's own choices for the lists are theirs alone and are never listed",
    "list_filters": "saved filters are made and managed in a list's own filter drawer, never listed",
}
