"""JSON endpoints for importing balances from a CSV file into one account (issue 108, part of 79).

Like the other routes, these call the plain functions (csvparse and balance_import) and add no rules of their own. The server
keeps nothing between the steps: every request carries the file again (as base64 text, at most MAX_BODY_BYTES in all), so a
review can never be stale in the server's memory, only in the account, which the commit checks. The account comes only from
the address, never from the file. Problems in the rows are not a failed request: `review` answers 200 with them listed.
"""

import base64
import binascii
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from pydantic import ValidationError as BadShape

from northstar import accounts, balance_import, balances, clock, csvparse
from northstar.balance_import import Expectation, PlannedRow, Reviewed
from northstar.errors import ValidationError
from northstar.web.auth_routes import current_user, run

router = APIRouter(prefix="/api/accounts/{account_id}/import")

# The base64 file (a third bigger than the file) and the `reviewed` value, which has an entry for every date in the file,
# with room to spare. Enforced while the body is read, so a request that does not say how long it is cannot get round it.
MAX_BODY_BYTES = 6 * 1024 * 1024
SAMPLES = 5                 # first values of a column shown on the mapping screen
ROWS_SHOWN = 200            # of each outcome that is not "unchanged"; the counts are always complete


class MappingBody(BaseModel):
    date: int | None = None
    balance: int | None = None
    note: int | None = None
    currency: int | None = None


class FileBody(BaseModel):
    content: str                       # the file, base64
    file_name: str | None = None


class ReviewBody(FileBody):
    mapping: MappingBody
    date_format: str | None = None
    policy: Literal["skip", "replace"] = "skip"


class ExpectationBody(BaseModel):
    date: str
    balance_id: int | None
    version: int | None


class ReviewedBody(BaseModel):
    fingerprint: str
    expectations: list[ExpectationBody]


class CommitBody(ReviewBody):
    reviewed: ReviewedBody


class ColumnOut(BaseModel):
    index: int
    header: str
    samples: list[str]
    date_formats: list[str]            # the formats under which every value is a date: one decides it, several need a choice


class ReadOut(BaseModel):
    delimiter: str
    row_count: int
    columns: list[ColumnOut]
    suggested: MappingBody
    date_formats: list[str]            # every format the import reads, for the choice
    today: str


class ProblemOut(BaseModel):
    record: int | None                 # the header is record 1; None when it is about the whole file
    column: int | None
    message: str


class RowOut(BaseModel):
    record: int
    date: str
    outcome: str
    amount_cents: int
    old_cents: int | None
    note: str | None
    old_note: str | None
    result_note: str | None


class ReviewedOut(BaseModel):
    fingerprint: str
    expectations: list[ExpectationBody]


class ReviewOut(BaseModel):
    can_commit: bool
    errors: list[ProblemOut]
    unsupported_currencies: list[str]
    date_format: str | None
    counts: dict[str, int] | None      # complete, whatever is listed below
    rows: list[RowOut]                 # newest first, at most ROWS_SHOWN of each outcome that is not "unchanged"
    hidden: dict[str, int]             # how many more of each outcome there are than are listed
    reviewed: ReviewedOut | None       # to be sent back with the commit; only when it can be committed


class CommitOut(BaseModel):
    added: int
    updated: int
    unchanged: int
    skipped: int


async def limited_json(request: Request) -> dict:
    """The JSON body, refused with 413 when it is over MAX_BODY_BYTES, whether or not the request says how long it is."""
    too_big = HTTPException(status_code=413, detail="That upload is too large. A file may be at most 2 MB.")
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise too_big
    received = bytearray()
    async for chunk in request.stream():
        received += chunk
        if len(received) > MAX_BODY_BYTES:
            raise too_big
    try:
        body = json.loads(received)
    except ValueError:
        raise ValidationError("The request is not in the form the import expects.") from None
    if not isinstance(body, dict):
        raise ValidationError("The request is not in the form the import expects.")
    return body


def shaped(model, body: dict):
    try:
        return model.model_validate(body)
    except BadShape:
        raise ValidationError("The request is not in the form the import expects.") from None


def file_bytes(body: FileBody) -> bytes:
    try:
        return base64.b64decode(body.content, validate=True)
    except (binascii.Error, ValueError):
        raise ValidationError("The file did not arrive intact. Choose it again.") from None


def open_account(conn, account_id: int):
    """A missing or deleted account is NotFoundError, and a closed one is refused, as for any change to its balances."""
    return balances.require_open(accounts.get_account(conn, account_id))


def mapping_of(body: MappingBody) -> csvparse.Mapping:
    return csvparse.Mapping(body.date, body.balance, body.note, body.currency)


def problems(errors) -> list[dict]:
    return [{"record": e.record, "column": e.column, "message": e.message} for e in errors]


def sample_values(table: csvparse.Table, column: int) -> list[str]:
    shown = []
    for _, cell in table.values(column):
        if cell.strip():
            shown.append(cell)
            if len(shown) == SAMPLES:
                break
    return shown


def date_formats(table: csvparse.Table, column: int, today) -> list[str]:
    """The formats under which every value of the column is a date. Every value has to fit, so when the first few do not
    fit any format the answer is none, and the whole column (up to 20,000 values) need not be read to find that out."""
    cells = table.values(column)
    first = [cell for cell in cells if cell[1].strip()][:SAMPLES]
    if not csvparse.detect_date_format(first, today).formats:
        return []
    return csvparse.detect_date_format(cells, today).formats


def read(conn, account_id: int, body: FileBody) -> dict:
    open_account(conn, account_id)
    today = clock.today()
    table = csvparse.read_table(file_bytes(body))
    columns = [{"index": index, "header": header, "samples": sample_values(table, index),
                "date_formats": date_formats(table, index, today)}
               for index, header in enumerate(table.headers)]
    suggested = csvparse.suggest_mapping(table.headers)
    return {"delimiter": table.delimiter, "row_count": len(table.rows), "columns": columns,
            "suggested": {target: getattr(suggested, target) for target in csvparse.TARGETS},
            "date_formats": list(csvparse.DATE_FORMATS), "today": today.isoformat()}


def listed(plan: balance_import.ImportPlan) -> tuple[list[dict], dict[str, int]]:
    """The rows worth looking at, newest first and capped per outcome, and how many more there are than are listed."""
    shown, hidden, seen = [], {}, {}
    for row in sorted(plan.rows, key=lambda r: r.date, reverse=True):
        if row.outcome == "unchanged":
            continue
        seen[row.outcome] = seen.get(row.outcome, 0) + 1
        if seen[row.outcome] > ROWS_SHOWN:
            hidden[row.outcome] = hidden.get(row.outcome, 0) + 1
            continue
        shown.append(row_out(row))
    return shown, hidden


def row_out(row: PlannedRow) -> dict:
    return {"record": row.record, "date": row.date.isoformat(), "outcome": row.outcome, "amount_cents": row.cents,
            "old_cents": row.old_cents, "note": row.note, "old_note": row.old_note, "result_note": row.result_note}


def review(conn, account_id: int, body: ReviewBody) -> dict:
    open_account(conn, account_id)
    today = clock.today()
    parsed = csvparse.parse_file(csvparse.read_table(file_bytes(body)), mapping_of(body.mapping), body.date_format, today)
    nothing = {"can_commit": False, "unsupported_currencies": parsed.unsupported_currencies,
               "date_format": body.date_format or parsed.date_format, "counts": None, "rows": [], "hidden": {}, "reviewed": None}
    if parsed.errors:
        return {**nothing, "errors": problems(parsed.errors)}
    plan = balance_import.plan_import(conn, account_id, parsed.rows, body.policy)
    if plan.errors:
        return {**nothing, "errors": problems(plan.errors)}
    shown, hidden = listed(plan)
    reviewed = plan.reviewed
    return {**nothing, "can_commit": True, "errors": [], "counts": plan.counts, "rows": shown, "hidden": hidden,
            "reviewed": {"fingerprint": reviewed.fingerprint,
                         "expectations": [{"date": e.date, "balance_id": e.balance_id, "version": e.version}
                                          for e in reviewed.expectations]}}


def commit(conn, actor_id: int, account_id: int, body: CommitBody) -> dict:
    open_account(conn, account_id)
    parsed = csvparse.parse_file(csvparse.read_table(file_bytes(body)), mapping_of(body.mapping), body.date_format, clock.today())
    if parsed.errors:
        raise ValidationError(f"The file has {len(parsed.errors)} problem(s) that must be fixed first. Review it again.")
    reviewed = Reviewed([Expectation(e.date, e.balance_id, e.version) for e in body.reviewed.expectations],
                        body.reviewed.fingerprint)
    result = balance_import.commit_import(conn, actor_id, account_id, parsed.rows, body.policy, reviewed, body.file_name,
                                          mapping_of(body.mapping), body.date_format or parsed.date_format)
    return {"added": result.added, "updated": result.updated, "unchanged": result.unchanged, "skipped": result.skipped}


@router.post("/read", response_model=ReadOut)
def read_file(account_id: int, request: Request, body: dict = Depends(limited_json)):
    """The file as columns with their first values, the delimiter, and the mapping and date formats the data suggests."""
    sent = shaped(FileBody, body)
    return run(request, lambda conn: read(conn, account_id, sent))


@router.post("/review", response_model=ReviewOut)
def review_file(account_id: int, request: Request, body: dict = Depends(limited_json)):
    """What importing would do. Reads only; nothing is written."""
    sent = shaped(ReviewBody, body)
    return run(request, lambda conn: review(conn, account_id, sent))


@router.post("/commit", response_model=CommitOut)
def commit_file(account_id: int, request: Request, body: dict = Depends(limited_json)):
    """Write the import, or refuse (409 with the dates that changed) and write nothing."""
    sent = shaped(CommitBody, body)
    actor = current_user(request)["id"]
    return run(request, lambda conn: commit(conn, actor, account_id, sent))
