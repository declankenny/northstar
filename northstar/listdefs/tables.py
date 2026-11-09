"""What the list framework may offer from each of Northstar's tables. This is data: the engine (northstar/lists) knows none of it.

A table has an entry here, or is named in NOT_LISTABLE with the reason, and a test fails for a table that is neither, so adding
a table to the database forces the decision. Tables the application owns for itself (`sys_`) and the loaded catalogs (`ref_`)
are never lists.

A column that is not offered here is not a column of any list. The deleted flag, the system flag and the password hash are not
offered, and are also named as denied so that offering one by mistake fails a test.

A list that reads a view that leaves out deleted rows (`live_accounts`, `live_balances`) sets it as its source. A relation to
`accounts` or `account_types` from another table goes to the table itself, so a list must start from a source that already
excludes what should not be seen.
"""

from northstar.lists.kinds import Date, Integer, ScaledBy, Text, Timestamp, YesNo, Computed
from northstar.lists.registry import FieldDef, TableDef
from northstar.listdefs import conversion


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
        denied=frozenset({"deleted"})),
    "balances": TableDef("balances", "as_of_date", {
        "as_of_date": FieldDef(Date(), label="Date"),
        "amount_cents": FieldDef(ScaledBy(scale_from=("account", "currency", "minor_units"),
                                          unit_from=("account", "currency", "code")), label="Value"),
        "reporting_value": FieldDef(Computed(
            inputs=("amount_cents", "account.currency.minor_units", "account.currency", "as_of_date"),
            compute=conversion.reporting_value("as_of_date")), label="Reporting value"),
        "note": _text(True), "source": _text(), **_audit()},
        denied=frozenset({"version"})),
    "currencies": TableDef("currencies", "code", {
        "code": _text(), "name": _text(True), "minor_units": FieldDef(Integer(), label="Decimal places"),
        "is_enabled": FieldDef(YesNo(), label="Enabled"), "rates_start": FieldDef(Date(), label="Rates start"), **_audit()}),
    # Users show their name and can be walked into by no other table: a person's email is not offered from a relation.
    "users": TableDef("users", "display_name", {
        "display_name": _text(True, "Name"), "email": _text(True), "is_admin": FieldDef(YesNo(), label="Admin"), **_audit()},
        walkable=False, denied=frozenset({"password_hash", "is_system", "deleted"})),
}

NOT_LISTABLE = {
    "exchange_rates": "a currency's rates are listed on its own page, which has not moved onto the list framework",
    "system_properties": "the System properties page is a settings editor, not a list",
    "user_identities": "bindings to an identity provider are never shown as a list",
}
