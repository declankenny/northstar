"""What is particular to Northstar in the list framework: its tables and how an amount is converted. The engine in
northstar/lists knows none of this, and a test fails if it ever imports any of it."""

from northstar.lists.registry import Catalog


def catalog(conn) -> Catalog:
    """The registry read against a Northstar database. Cheap enough to build for each request.

    The tables the application owns for itself (`sys_`) and the loaded catalogs (`ref_`) are never lists, and neither are the
    ones named in NOT_LISTABLE, so a foreign key to one of them is not a relation a person can follow."""
    from northstar.listdefs.tables import NOT_LISTABLE, TABLES

    names = (row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'"))
    owned = {name for name in names if name.startswith(("sys_", "ref_"))}
    return Catalog(conn, TABLES, excluded=owned | set(NOT_LISTABLE))
