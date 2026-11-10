"""A list's view as a CSV file, on the generated schema (lists_schema.py): what is written, how, and for which rows."""

import csv
import io
from decimal import Decimal

import pytest

from lists_schema import READINGS, TICKETS, build, catalog
from northstar.errors import ValidationError
from northstar.lists import export
from northstar.lists.kinds import Number, Scaled, plain_decimal
from northstar.lists.query import iterate, run
from northstar.lists.request import parse_request


@pytest.fixture(scope="module")
def conn():
    return build()


@pytest.fixture(scope="module")
def cat(conn):
    return catalog(conn)


def request(cat, data=None, definition=TICKETS):
    return parse_request(cat, definition, data)


def file_text(conn, cat, data=None, definition=TICKETS):
    return "".join(export.stream(conn, cat, definition, request(cat, data, definition)))


def read(text):
    """The file as a person's spreadsheet reads it: the byte-order mark gone, the cells as written."""
    assert text.startswith(export.BOM)
    return list(csv.reader(io.StringIO(text[len(export.BOM):], newline="")))


def live(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM ticket WHERE deleted_at IS NULL ORDER BY id")]


def view_rows(conn, cat, data=None, definition=TICKETS):
    rows, page = [], 1
    while True:
        result = run(conn, cat, definition, request(cat, {**(data or {}), "page": page, "page_size": 100}, definition))
        rows += result.rows
        if page >= result.pages:
            return rows
        page += 1


# -- what the file is --

def test_it_starts_with_a_byte_order_mark_ends_its_lines_with_crlf_and_names_its_columns_as_they_read_on_screen(conn, cat):
    text = file_text(conn, cat, {"columns": ["code", "site.lead", "assignee", "score_x100"]})
    assert text.startswith("﻿")
    assert "\r\n" in text and "\n" not in text.replace("\r\n", "")                  # every line ends with CRLF (this file has no cell with a break)
    assert read(text)[0] == ["Code", "Site › Lead", "Assigned to", "Score"]


def test_it_has_every_matching_row_in_the_lists_order_whatever_a_page_would_hold(conn, cat):
    rows = read(file_text(conn, cat, {"columns": ["code"], "sort": {"field": "code", "direction": "desc"}, "page": 3, "page_size": 10}))
    codes = [r[0] for r in rows[1:]]
    assert len(codes) == len(live(conn)) > 100
    assert codes == [r["code"] for r in view_rows(conn, cat, {"columns": ["code"], "sort": {"field": "code", "direction": "desc"}})]
    assert codes == sorted(codes, reverse=True)


def test_it_has_only_the_rows_that_match_and_in_the_columns_asked_for_in_their_order(conn, cat):
    data = {"columns": ["status", "code"], "filters": [{"field": "status", "operator": "is", "value": "Closed"}], "search": "T-00"}
    rows = read(file_text(conn, cat, data))
    assert rows[0] == ["Status", "Code"]
    expected = [r for r in view_rows(conn, cat, data)]
    assert [r[1] for r in rows[1:]] == [r["code"] for r in expected] and expected
    assert {r[0] for r in rows[1:]} == {"Closed"}


def test_an_empty_result_is_the_headers_alone(conn, cat):
    text = file_text(conn, cat, {"columns": ["code", "status"], "filters": [{"field": "code", "operator": "equals", "value": "no such code"}]})
    assert text == "﻿Code,Status\r\n"


def test_a_grouped_list_exports_its_rows_in_grouped_order_with_no_group_rows(conn, cat):
    data = {"columns": ["code", "kind"], "group": "kind", "sort": {"field": "code", "direction": "asc"}}
    rows = read(file_text(conn, cat, data))
    assert rows[0] == ["Code", "Kind"]
    assert [r[0] for r in rows[1:]] == [r["code"] for r in view_rows(conn, cat, data)]
    kinds = [r[1] for r in rows[1:]]
    assert kinds == sorted(kinds, key=str.lower) and len(rows) - 1 == len(live(conn))


# -- how each kind is written --

def test_unicode_survives_the_trip_as_utf_8(conn, cat):
    conn.execute("UPDATE ticket SET assignee_id = (SELECT id FROM person WHERE name LIKE '%mile Roy') WHERE code = 'T-0001'")
    try:
        text = file_text(conn, cat, {"columns": ["code", "assignee"]})
        assert text.encode("utf-8").startswith(b"\xef\xbb\xbf")                      # the byte-order mark, as bytes
        sent = text.encode("utf-8").decode("utf-8-sig")
        assert [r[1] for r in read("﻿" + sent)[1:] if r[0] == "T-0001"] == ["Émile Roy"]
    finally:
        conn.rollback()


def test_quotes_commas_and_line_breaks_are_quoted_and_read_back_exactly(conn, cat):
    text = file_text(conn, cat, {"columns": ["code", "notes"]})
    assert 'has "quotes", commas\nand lines' in {r[1] for r in read(text)[1:]}
    wanted = {r["code"]: r["notes"] for r in live(conn)}
    for code, notes in read(text)[1:]:
        original = wanted[code] or ""
        assert notes == ("'" + original if original.startswith("=") else original)


def test_a_missing_value_is_an_empty_cell_for_every_kind(conn, cat):
    rows = read(file_text(conn, cat, {"columns": ["code", "notes", "assignee", "score_x100", "weight", "closed_at", "passed"]}))
    by_code = {r[0]: r for r in rows[1:]}
    for t in live(conn):
        row = by_code[t["code"]]
        if t["notes"] is None: assert row[1] == ""
        if t["assignee_id"] is None: assert row[2] == ""
        if t["score_x100"] is None: assert row[3] == ""
        if t["weight"] is None: assert row[4] == ""
        if t["closed_at"] is None: assert row[5] == ""
        if t["passed"] is None: assert row[6] == ""
    assert any(t["passed"] is None for t in live(conn)) and any(t["score_x100"] is None for t in live(conn))


def test_a_decimal_is_written_plain_in_its_own_places_and_a_negative_keeps_its_sign(conn, cat):
    rows = read(file_text(conn, cat, {"columns": ["code", "score_x100"]}))
    by_code = {r[0]: r[1] for r in rows[1:]}
    wanted = {r["code"]: r["score_x100"] for r in live(conn)}
    for code, stored in wanted.items():
        assert by_code[code] == ("" if stored is None else plain_decimal(stored, 2))
    assert {"-2.50", "0.00", "19.99", "20.00"} <= set(by_code.values())              # a negative, zero and two with places


def test_a_float_is_written_plain_never_in_scientific_notation(conn, cat):
    assert Number().export(0.0000001) == "0.0000001"
    assert Number().export(2.25) == "2.25"
    assert Number().export(-1.5) == "-1.5"
    assert Number().export(None) == ""
    assert Number().export(1e21) == "1000000000000000000000"


def test_yes_and_no_are_true_and_false_and_a_flag_that_can_be_empty_can_be(conn, cat):
    rows = read(file_text(conn, cat, {"columns": ["code", "flagged", "passed"]}))
    by_code = {r[0]: r for r in rows[1:]}
    for t in live(conn):
        assert by_code[t["code"]][1] == ("true" if t["flagged"] else "false")
        assert by_code[t["code"]][2] == {None: "", 0: "false", 1: "true"}[t["passed"]]


def test_a_date_is_iso_and_a_timestamp_is_its_utc_date(conn, cat):
    rows = read(file_text(conn, cat, {"columns": ["code", "opened_on", "closed_at"]}))
    by_code = {r[0]: r for r in rows[1:]}
    for t in live(conn):
        assert by_code[t["code"]][1] == t["opened_on"]
        assert by_code[t["code"]][2] == (t["closed_at"][:10] if t["closed_at"] else "")


def test_a_relation_writes_the_display_value_of_the_record_it_points_at(conn, cat):
    rows = read(file_text(conn, cat, {"columns": ["code", "site", "kind", "assignee", "site.lead"]}))
    by_code = {r[0]: r for r in rows[1:]}
    names = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM person")}
    sites = {r["id"]: (r["name"], r["lead_id"]) for r in conn.execute("SELECT id, name, lead_id FROM site")}
    kinds = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM kind")}
    for t in live(conn):
        row = by_code[t["code"]]
        assert row[1] == sites[t["site_id"]][0] and row[2] == kinds[t["kind_id"]]
        assert row[3] == (names[t["assignee_id"]] if t["assignee_id"] else "")
        lead = sites[t["site_id"]][1]
        assert row[4] == (names[lead] if lead else "")


# -- text that a spreadsheet could run --

@pytest.mark.parametrize("text, written", [
    ("=1+1", "'=1+1"), ("+1", "'+1"), ("-5 pending", "'-5 pending"), ("@SUM(A1)", "'@SUM(A1)"), ("\tx", "'\tx"), ("\rx", "'\rx"),
    ("plain", "plain"), ("1+1", "1+1"), ("a=b", "a=b"), ("", ""), (" =1", " =1"), ("'=1", "'=1"),
])
def test_text_that_starts_like_a_formula_is_made_plain_text_and_other_text_is_left_alone(text, written):
    assert export.neutralise(text) == written


def test_it_neutralises_text_cells_and_never_a_number_so_a_negative_amount_stays_a_number(conn, cat):
    rows = read(file_text(conn, cat, {"columns": ["code", "notes", "score_x100"]}))
    notes = {r[1] for r in rows[1:]}
    assert "'=1+1" in notes and "=1+1" not in notes
    scores = {r[2] for r in rows[1:]}
    assert "-2.50" in scores and "'-2.50" not in scores


def test_a_name_that_starts_like_a_formula_is_neutralised_too_because_a_relation_writes_a_name(conn, cat):
    conn.execute("INSERT INTO person (name, email, team_id, secret) VALUES ('=cmd|x', 'p99@example.test', 1, 'hidden')")
    conn.execute("UPDATE ticket SET assignee_id = (SELECT MAX(id) FROM person) WHERE code = 'T-0001'")
    try:
        rows = read(file_text(conn, cat, {"columns": ["code", "assignee"]}))
        assert [r[1] for r in rows[1:] if r[0] == "T-0001"] == ["'=cmd|x"]
    finally:
        conn.rollback()


# -- what it will not write --

@pytest.mark.parametrize("column", ["assignee.secret", "deleted_at", "id", "assignee.team.secret", "no_such_column", "assignee_id"])
def test_a_column_that_is_denied_or_not_there_cannot_be_asked_for(cat, column):
    with pytest.raises(ValidationError):
        request(cat, {"columns": ["code", column]})


def test_a_deleted_ticket_is_not_in_the_file_because_the_list_does_not_have_it(conn, cat):
    codes = {r[0] for r in read(file_text(conn, cat, {"columns": ["code"]}))[1:]}
    gone = {r["code"] for r in conn.execute("SELECT code FROM ticket WHERE deleted_at IS NOT NULL")}
    assert gone and not codes & gone


# -- many rows --

def test_a_big_list_is_written_in_chunks_and_every_row_is_there(conn):
    big = build(tickets=5, readings=3_000)
    cat_big = catalog(big)
    chunks = list(export.stream(big, cat_big, READINGS, request(cat_big, {"columns": ["label", "taken_on"], "sort": {"field": "label", "direction": "asc"}}, READINGS)))
    assert len(chunks) >= 15                                                        # not one string of the whole file
    assert max(chunk.count("\r\n") for chunk in chunks) <= export.ROWS_PER_CHUNK + 1
    rows = read("".join(chunks))
    assert len(rows) == 3_001 and [r[0] for r in rows[1:]] == sorted(r[0] for r in rows[1:])


def test_rows_are_read_one_statement_at_a_time_without_a_page_limit(conn, cat):
    count = sum(1 for _ in iterate(conn, cat, TICKETS, request(cat, {"columns": ["code"], "page": 2, "page_size": 10})))
    assert count == len(live(conn))


# -- amounts whose scale is not the column's own --

def test_an_amount_with_its_own_scale_is_written_plain_and_a_value_the_database_works_out_is_empty_when_it_has_none(conn):
    cat = catalog(conn)
    data = {"columns": ["label", "amount", "worked"], "page_size": 100}
    rows = read("".join(export.stream(conn, cat, READINGS, request(cat, data, READINGS))))
    assert rows[0] == ["Label", "Amount", "Worked"]
    shaped = {r["label"]: r for r in view_rows(conn, cat, {"columns": ["label", "amount", "worked"]}, READINGS)}
    for label, amount, worked in rows[1:]:
        for text, value in ((amount, shaped[label]["amount"]), (worked, shaped[label]["worked"])):
            if value is None:
                assert text == ""
            else:
                assert text == f"{Decimal(value['value']).scaleb(-value['scale']):.{value['scale']}f}"
                assert "," not in text and " " not in text
    assert any(r[2] == "" for r in rows[1:]) and any(r[2] != "" for r in rows[1:])


def test_a_stored_integer_with_a_scale_is_written_with_every_place():
    assert plain_decimal(-250, 2) == "-2.50"
    assert plain_decimal(5, 2) == "0.05"
    assert plain_decimal(0, 2) == "0.00"
    assert plain_decimal(12, 0) == "12"
    assert plain_decimal(-5, 3) == "-0.005"
    assert plain_decimal(1234567, 2) == "12345.67"
    assert Scaled(2).export(-250) == "-2.50" and Scaled(2).export(None) == ""
