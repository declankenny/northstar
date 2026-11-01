"""docs/schema.md draws the schema. The diagram must say what the migrations build: the same tables, columns, types,
single-column keys and relationships. It is written in a strict subset of Mermaid so this file can read it."""

import re
from pathlib import Path

DOC = (Path(__file__).resolve().parent.parent / "docs" / "schema.md").read_text(encoding="utf-8")

ENTITY = re.compile(r"^(\w+) \{$")
ATTRIBUTE = re.compile(r'^(\w+) (\w+)(?: ((?:PK|FK|UK)(?:, (?:PK|FK|UK))*))?(?: "[^"]*")?$')
RELATIONSHIP = re.compile(r'^(\w+) (\|\||\|o)--o\{ (\w+) : "[^"]*"$')


def read_diagram(text):
    """The diagram's tables ({table: {column: (type, keys)}}) and relationships ({(parent, child, parent_required)})."""
    block = re.search(r"```mermaid\n(erDiagram\n.*?)```", text, re.S)
    assert block, "docs/schema.md has no mermaid erDiagram block"
    tables, relationships, current = {}, set(), None
    for number, raw in enumerate(block.group(1).splitlines()[1:], start=2):
        line = raw.strip()
        if not line:
            continue
        if line == "}" and current:
            current = None
        elif current and (m := ATTRIBUTE.match(line)):
            keys = set(m.group(3).split(", ")) if m.group(3) else set()
            tables[current][m.group(2)] = (m.group(1), keys)
        elif not current and (m := ENTITY.match(line)):
            current = m.group(1)
            tables[current] = {}
        elif not current and (m := RELATIONSHIP.match(line)):
            relationships.add((m.group(1), m.group(3), m.group(2) == "||"))
        else:
            raise AssertionError(f"docs/schema.md diagram line {number} is outside the supported subset: {line!r}")
    return tables, relationships


def read_schema(conn):
    """The same two things, read from a migrated database."""
    names = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
    tables, relationships = {}, set()
    for table in names:
        info = conn.execute(f"PRAGMA table_info({table})").fetchall()
        keys = {column["name"]: {"PK"} if column["pk"] else set() for column in info}
        for index in conn.execute(f"PRAGMA index_list({table})"):
            columns = [c["name"] for c in conn.execute(f"PRAGMA index_info({index['name']})")]
            if index["unique"] and index["origin"] == "u" and len(columns) == 1:
                keys[columns[0]].add("UK")
        foreign = conn.execute(f"PRAGMA foreign_key_list({table})").fetchall()
        not_null = {column["name"]: column["notnull"] for column in info}
        for fk in foreign:
            keys[fk["from"]].add("FK")
        for fk_id in {fk["id"] for fk in foreign}:
            parts = [fk for fk in foreign if fk["id"] == fk_id]
            required = all(not_null[fk["from"]] for fk in parts)
            relationships.add((parts[0]["table"], table, required))
        tables[table] = {c["name"]: (c["type"].lower(), keys[c["name"]]) for c in info}
    return tables, relationships


def differences(drawn, built):
    """What a person must fix, as readable lines. Empty when the diagram matches the schema."""
    problems = []
    (drawn_tables, drawn_links), (built_tables, built_links) = drawn, built
    for table in sorted(drawn_tables.keys() - built_tables.keys()):
        problems.append(f"the diagram draws table {table}, which the migrations do not create")
    for table in sorted(built_tables.keys() - drawn_tables.keys()):
        problems.append(f"the migrations create table {table}, which the diagram does not draw")
    for table in sorted(drawn_tables.keys() & built_tables.keys()):
        drawn_columns, built_columns = drawn_tables[table], built_tables[table]
        for column in sorted(drawn_columns.keys() - built_columns.keys()):
            problems.append(f"{table}.{column} is drawn but is not in the schema")
        for column in sorted(built_columns.keys() - drawn_columns.keys()):
            problems.append(f"{table}.{column} is in the schema but is not drawn")
        for column in sorted(drawn_columns.keys() & built_columns.keys()):
            if drawn_columns[column] != built_columns[column]:
                problems.append(f"{table}.{column} is drawn as {drawn_columns[column]} but the schema has "
                                f"{built_columns[column]} (type, keys)")
        if list(drawn_columns) != list(built_columns):
            problems.append(f"{table}: the columns are drawn in a different order from the schema")
    for link in sorted(drawn_links - built_links):
        problems.append(f"relationship {link} is drawn but is not in the schema (parent, child, parent required)")
    for link in sorted(built_links - drawn_links):
        problems.append(f"relationship {link} is in the schema but is not drawn (parent, child, parent required)")
    return problems


def test_the_diagram_matches_the_migrated_schema(conn):
    problems = differences(read_diagram(DOC), read_schema(conn))
    assert not problems, "docs/schema.md is out of step with the migrations:\n" + "\n".join(problems)


def test_the_comparison_notices_a_drifted_diagram(conn):
    """The check above is only worth having if it can fail."""
    built = read_schema(conn)
    for old, new in (
        ("        text note \"optional\"\n", ""),                              # a column left out
        ("        text email UK \"case-insensitive\"", "        text email"),  # a key lost
        ("        integer amount_cents", "        text amount_cents"),         # a wrong type
        ("    users ||--o{ sessions : \"user_id\"\n", ""),                     # a relationship left out
        ("    login_attempts {", "    login_attempt_log {"),                   # a table renamed
    ):
        assert old in DOC, f"the drift example {old!r} no longer matches docs/schema.md"
        assert differences(read_diagram(DOC.replace(old, new)), built), f"drift not noticed: {old!r}"


def test_a_line_the_reader_does_not_understand_is_an_error_not_a_skip():
    broken = DOC.replace("        integer id PK\n", "        integer id PK something odd\n", 1)
    try:
        read_diagram(broken)
    except AssertionError as error:
        assert "outside the supported subset" in str(error)
    else:
        raise AssertionError("an unsupported line was ignored")
