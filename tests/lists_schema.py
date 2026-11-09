"""A small generated schema for testing the list framework on a database that is not Northstar's.

It has the shapes a second schema is likely to have: one table reached in several roles (`assignee`, `reviewer`, the leads of
a site, an area and a region), a path as deep as the framework allows, a view that leaves out soft-deleted rows, nullable
Yes or No, a scaled integer, a float, a UTC timestamp, a status and repeated values. Everything is synthetic and seeded.
"""

import random
import sqlite3

from northstar.lists.kinds import Category, Date, Integer, Number, Scaled, ScaledBy, Text, Timestamp, YesNo
from northstar.lists.listdef import ListDef
from northstar.lists.registry import Catalog, FieldDef, TableDef

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE unit   (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE team   (id INTEGER PRIMARY KEY, name TEXT NOT NULL, unit_id INTEGER NOT NULL REFERENCES unit(id));
CREATE TABLE person (id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
                     team_id INTEGER NOT NULL REFERENCES team(id), secret TEXT);
CREATE TABLE region (id INTEGER PRIMARY KEY, name TEXT NOT NULL, head_id INTEGER REFERENCES person(id));
CREATE TABLE area   (id INTEGER PRIMARY KEY, name TEXT NOT NULL, region_id INTEGER NOT NULL REFERENCES region(id),
                     lead_id INTEGER REFERENCES person(id));
CREATE TABLE site   (id INTEGER PRIMARY KEY, name TEXT NOT NULL, area_id INTEGER NOT NULL REFERENCES area(id),
                     lead_id INTEGER REFERENCES person(id));
CREATE TABLE family (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE kind   (id INTEGER PRIMARY KEY, name TEXT NOT NULL, family_id INTEGER NOT NULL REFERENCES family(id));
CREATE TABLE ticket (
    id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, title TEXT NOT NULL, notes TEXT,
    site_id INTEGER NOT NULL REFERENCES site(id), kind_id INTEGER NOT NULL REFERENCES kind(id),
    assignee_id INTEGER REFERENCES person(id), reviewer_id INTEGER REFERENCES person(id),
    opened_on TEXT NOT NULL, closed_at TEXT, score_x100 INTEGER, weight REAL, items INTEGER NOT NULL,
    passed INTEGER CHECK (passed IN (0, 1)), flagged INTEGER NOT NULL CHECK (flagged IN (0, 1)),
    status TEXT NOT NULL CHECK (status IN ('Open', 'Active', 'Closed')), deleted_at TEXT
);
CREATE VIEW ticket_live AS SELECT * FROM ticket WHERE deleted_at IS NULL;
-- amounts whose scale differs from row to row, and values worked out from them
CREATE TABLE measure (id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, decimals INTEGER NOT NULL);
CREATE TABLE factor  (measure_id INTEGER NOT NULL REFERENCES measure(id), from_day TEXT NOT NULL, value TEXT NOT NULL);
CREATE TABLE reading (id INTEGER PRIMARY KEY, label TEXT NOT NULL, amount INTEGER, taken_on TEXT NOT NULL,
                      measure_id INTEGER NOT NULL REFERENCES measure(id), note TEXT);
-- A value worked out by a function SQLite has been given (exact decimal arithmetic), with its scale and unit beside it. The
-- factor is the latest one on or before the day, and a reading with none has no worked value.
CREATE VIEW reading_values AS
SELECT r.*, work(r.amount, (SELECT f.value FROM factor f WHERE f.measure_id = r.measure_id AND f.from_day <= r.taken_on
                             ORDER BY f.from_day DESC LIMIT 1)) AS worked, m.decimals AS worked_scale, 'W' AS worked_unit
FROM reading r JOIN measure m ON m.id = r.measure_id;
-- a view that leaves out a column a table has a relation on
CREATE VIEW reading_without_measure AS SELECT id, label, amount FROM reading;
"""

STATUSES = ("Open", "Active", "Closed")


FACTORS = (("A", "2026-01-01", "1.5"), ("B", "2026-03-01", "0.25"))      # measure symbol, from day, factor


def work(amount, factor):
    """The function the database is given: an amount times a factor, exactly, truncated. Nothing here knows what it means."""
    if amount is None or factor is None:
        return None
    from decimal import Decimal
    return int(Decimal(amount) * Decimal(factor))


def _text(searchable=False):
    return FieldDef(Text(), searchable=searchable)


TABLES = {
    "unit": TableDef("unit", "name", {"name": _text()}),
    "team": TableDef("team", "name", {"name": _text()}),
    "person": TableDef("person", "name", {"name": _text(True), "email": _text()}, tell_apart="email",
                       denied=frozenset({"secret"})),
    "region": TableDef("region", "name", {"name": _text()}),
    "area": TableDef("area", "name", {"name": _text()}),
    "site": TableDef("site", "name", {"name": _text(True)}),
    "family": TableDef("family", "name", {"name": _text()}),
    "kind": TableDef("kind", "name", {"name": _text()}),
    "measure": TableDef("measure", "symbol", {"symbol": _text(), "decimals": FieldDef(Integer())}),
    # a view with a column that is worked out: its key and its relations are those of the table it is based on
    "reading_values": TableDef("reading_values", "label", {
        "label": _text(True), "taken_on": FieldDef(Date()), "note": _text(),
        "amount": FieldDef(ScaledBy(scale_from=("measure", "decimals"), unit_from=("measure", "symbol"))),
        "worked": FieldDef(ScaledBy(scale_from=("worked_scale",), unit_from=("worked_unit",))),
    }, based_on="reading"),
    "ticket": TableDef("ticket", "code", {
        "code": _text(True), "title": _text(True), "notes": _text(True),
        "opened_on": FieldDef(Date()), "closed_at": FieldDef(Timestamp()),
        "score_x100": FieldDef(Scaled(2), label="Score"), "weight": FieldDef(Number()),
        "items": FieldDef(Integer()), "passed": FieldDef(YesNo(nullable=True)), "flagged": FieldDef(YesNo()),
        "status": FieldDef(Category(STATUSES)),
    }, denied=frozenset({"deleted_at"}), labels={"assignee": "Assigned to"}),
}

READINGS = ListDef("readings", "reading_values", ("label", "taken_on", "amount", "worked"), ("taken_on", "desc"))
TICKETS = ListDef("tickets", "ticket", ("code", "title", "assignee", "site", "opened_on"), ("opened_on", "desc"),
                  source="ticket_live")


def build(seed: int = 7, tickets: int = 300, readings: int = 400) -> sqlite3.Connection:
    """A database with the schema above, filled deterministically."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.create_function("work", 2, work, deterministic=True)
    conn.executescript(SCHEMA)
    rng = random.Random(seed)
    for number in range(2):
        conn.execute("INSERT INTO unit (name) VALUES (?)", (f"Unit {number}",))
    for number in range(3):
        conn.execute("INSERT INTO team (name, unit_id) VALUES (?, ?)", (f"Team {number}", 1 + number % 2))
    names = ["Avery Reed", "Blake Moss", "avery reed", "Casey Dunn", "Dana Fox", "Émile Roy", "Fran Oak", "Avery Reed"]
    for number, name in enumerate(names):                       # two people share a name, one differs only in case
        conn.execute("INSERT INTO person (name, email, team_id, secret) VALUES (?, ?, ?, 'hidden')",
                     (name, f"p{number}@example.test", 1 + number % 3))
    conn.execute("INSERT INTO region (name, head_id) VALUES ('North', 1), ('South', NULL)")
    conn.execute("INSERT INTO area (name, region_id, lead_id) VALUES ('A1', 1, 2), ('A2', 2, NULL)")
    conn.execute("INSERT INTO site (name, area_id, lead_id) VALUES ('Site 1', 1, 3), ('Site 2', 1, NULL), ('Site 3', 2, 4)")
    conn.execute("INSERT INTO family (name) VALUES ('Alpha'), ('Beta')")
    conn.execute("INSERT INTO kind (name, family_id) VALUES ('Check', 1), ('Repair', 1), ('Audit', 2)")
    for number in range(1, tickets + 1):
        status = rng.choice(STATUSES)
        closed = f"2026-0{rng.randint(1, 9)}-1{rng.randint(0, 9)}T0{rng.randint(0, 9)}:30:00Z" if status == "Closed" else None
        passed = rng.choice([None, 0, 1]) if status != "Open" else None
        conn.execute(
            "INSERT INTO ticket (code, title, notes, site_id, kind_id, assignee_id, reviewer_id, opened_on, closed_at, "
            "score_x100, weight, items, passed, flagged, status, deleted_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"T-{number:04d}", rng.choice(["Replace part", "Annual check", "replace PART", "100% done", "a_b"]),
             rng.choice([None, "", "=1+1", "plain note", 'has "quotes", commas\nand lines']),
             rng.randint(1, 3), rng.randint(1, 3), rng.choice([None, 1, 2, 3, 8]), rng.choice([None, 2, 8]),
             f"2025-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}", closed,
             rng.choice([None, -250, 0, 1999, 2000]), rng.choice([None, 0.0, 1.5, 2.25]), rng.randint(0, 5),
             passed, rng.randint(0, 1), status, "2026-01-01T00:00:00Z" if number % 20 == 0 else None))
    conn.execute("INSERT INTO measure (symbol, decimals) VALUES ('A', 2), ('B', 0), ('C', 3)")
    for symbol, day, value in FACTORS:
        conn.execute("INSERT INTO factor (measure_id, from_day, value) VALUES ((SELECT id FROM measure WHERE symbol = ?), ?, ?)",
                     (symbol, day, value))
    for number in range(1, readings + 1):
        conn.execute("INSERT INTO reading (label, amount, taken_on, measure_id, note) VALUES (?,?,?,?,?)",
                     (f"R-{number:05d}", rng.choice([None, 0, 5, 1000, rng.randint(-5000, 90000)]),
                      f"2026-0{rng.randint(1, 5)}-{rng.randint(10, 28)}", rng.randint(1, 3), None))
    conn.commit()
    return conn


def catalog(conn) -> Catalog:
    return Catalog(conn, TABLES)
