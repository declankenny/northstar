"""A list's view as a CSV file: every row the request matches, in its order, the columns it asks for, written by the kinds.

The file is UTF-8 with a byte-order mark, because a spreadsheet that opens a UTF-8 file without one reads it as the local code page and
garbles every accent. Lines end with CRLF and a cell is quoted when it holds a quote, a comma or a line break. Dates are YYYY-MM-DD,
amounts plain decimals with no symbol or separator, Yes and No are true and false, a missing value is an empty cell and a relation
writes the display value of the record it points at. Text that a spreadsheet could read as a formula is made plain text (see `neutralise`).
"""

import csv
import io
import sqlite3
from collections.abc import Iterator

from northstar.lists.listdef import ListDef
from northstar.lists.query import iterate
from northstar.lists.registry import Catalog
from northstar.lists.request import ListRequest

BOM = "\ufeff"
FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")
ROWS_PER_CHUNK = 200


def neutralise(text: str) -> str:
    """Text that starts like a formula, which a spreadsheet would run when the file is opened, gets an apostrophe in front, which makes
    it text. It is for text only: an amount that starts with a minus is a number and is written as it is."""
    return "'" + text if text.startswith(FORMULA_STARTS) else text


def header(catalog: Catalog, definition: ListDef, request: ListRequest) -> list[str]:
    """The column names as they read on screen, the whole path of a related column ("Account › Type"), so each is unique."""
    return [catalog.resolve(definition.table, key).label for key in request.columns]


def stream(conn: sqlite3.Connection, catalog: Catalog, definition: ListDef, request: ListRequest, viewer=frozenset()) -> Iterator[str]:
    """The file as text, in chunks: the header first, then every matching row. Nothing limits it but the request's own filters. It reads
    one statement, so the whole file is one consistent read, and it holds a chunk at a time, however many rows there are."""
    kinds = [catalog.resolve(definition.table, key).kind for key in request.columns]
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    out.write(BOM)
    writer.writerow(header(catalog, definition, request))
    pending = 0
    for row in iterate(conn, catalog, definition, request, viewer):
        writer.writerow([neutralise(text) if kind.exports_text else text
                         for kind, text in ((kind, kind.export(row[key])) for kind, key in zip(kinds, request.columns))])
        pending += 1
        if pending >= ROWS_PER_CHUNK:
            yield out.getvalue()
            out.seek(0)
            out.truncate()
            pending = 0
    yield out.getvalue()
