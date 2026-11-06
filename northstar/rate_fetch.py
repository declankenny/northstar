"""Fetching exchange rates from the provider: the first job of the in-app scheduler (#131). See docs/design/currency/design.md.

The provider is Frankfurter. `base=EUR&quotes=USD` answers with 1 EUR in USD, which is the direction Northstar stores. The fetch is
insert-only: it adds the dates a currency has no rate for and never changes a rate that is stored, whether it came from the provider
or from an admin. For each collected currency it fills two gaps, found from the rates the provider has supplied: the days after the
newest of them up to today, and, once, the days from the currency's rates start up to the day before the oldest of them. A rate an
admin typed is not an edge, so one far from the rest never makes the history look covered. Both gaps are fetched in
spans of at most a year, newest first, and each span is checked whole and committed on its own, so a span that fails leaves no
hole inside what was stored, a rerun is safe, and a missed run mends itself at the next. The provider's own list of what it covers
starts the window no earlier than its data does, and a currency it does not list is skipped.

Everything the provider sends is data: a rate is accepted only when its text is a plain decimal Northstar can store, and nothing
the provider says is logged or kept, only our own message. A request carries only currency codes and dates.
"""

import http.client
import json
import logging
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

from northstar import currencies, rates, scheduler, system_properties, writer
from northstar.errors import ValidationError
from northstar.version import VERSION
from northstar.writer import Operation

log = logging.getLogger(__name__)

PROVIDER = "https://api.frankfurter.dev/v2"      # a constant: nothing in a request or a setting is a credential
JOB = "currency.rates.fetch"
TIME_PROPERTY = "currency.rate.fetch_time"
SPAN_DAYS = 366                    # the longest range asked for in one request
CALL_TIMEOUT_SECONDS = 30
MAX_BODY_BYTES = 4_000_000         # a year of one currency is about 25 KB, the list of currencies about 30 KB


def get_json(url: str, timeout: float):
    """The decoded JSON at an address, with every number kept as its own text so a rate is never a float. A busy or absent
    provider (no answer, 429, 5xx) is Retryable, and anything else it does wrong is an InvalidResponse. Tests replace this."""
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": f"Northstar/{VERSION}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(MAX_BODY_BYTES + 1)
    except urllib.error.HTTPError as err:
        if err.code == 429 or err.code >= 500:
            raise scheduler.Retryable("The rate provider is busy or down.") from None
        raise scheduler.InvalidResponse("The rate provider refused a request.") from None
    except (urllib.error.URLError, OSError, http.client.HTTPException):         # includes a timeout
        raise scheduler.Retryable("The rate provider did not answer.") from None
    if len(body) > MAX_BODY_BYTES:
        raise scheduler.InvalidResponse("The rate provider sent more than expected.")
    try:
        return json.loads(body, parse_float=str, parse_int=str)
    except ValueError:
        raise scheduler.InvalidResponse("The rate provider sent something that is not JSON.") from None


def collected(conn, system_id: int):
    """The currencies to collect: not the system currency, with a rates start, and enabled or with an open account."""
    return conn.execute(
        "SELECT c.id, c.code, c.rates_start FROM currencies c WHERE c.id != ? AND c.rates_start IS NOT NULL AND "
        "(c.is_enabled = 1 OR EXISTS (SELECT 1 FROM live_accounts a WHERE a.currency_id = c.id AND a.is_open = 1)) "
        "ORDER BY c.code", (system_id,)).fetchall()


def spans(first: date, last: date):
    """The ranges that cover first..last, each at most SPAN_DAYS long, newest first."""
    while first <= last:
        start = max(first, last - timedelta(days=SPAN_DAYS - 1))
        yield start, last
        last = start - timedelta(days=1)


def gaps(conn, currency_id: int, start: date, today: date) -> list[tuple[date, date]]:
    """What is missing, as ranges to ask for, newest first: the days after the newest provider rate, then the days before the
    oldest. Only a provider rate marks an edge: a rate an admin typed or corrected is skipped when stored, but it does not tell
    where the fetched history ends. A currency with no provider rate is one range from its start to today."""
    row = conn.execute("SELECT MIN(rate_date) AS oldest, MAX(rate_date) AS newest FROM exchange_rates "
                       "WHERE currency_id = ? AND source = 'provider'", (currency_id,)).fetchone()
    if row["oldest"] is None:
        return [(start, today)] if start <= today else []
    newest, oldest = date.fromisoformat(row["newest"]), date.fromisoformat(row["oldest"])
    found = []
    if newest < today:
        found.append((newest + timedelta(days=1), today))
    if start < oldest:
        found.append((start, oldest - timedelta(days=1)))
    return found


def read_coverage(ctx) -> dict[str, date]:
    """The first date the provider has data for, by currency code."""
    items = get_json(f"{PROVIDER}/currencies", ctx.call_timeout(CALL_TIMEOUT_SECONDS))
    if not isinstance(items, list):
        raise scheduler.InvalidResponse("The rate provider's list of currencies is not a list.")
    found = {}
    for item in items:
        try:
            found[item["iso_code"]] = date.fromisoformat(item["start_date"])
        except (KeyError, TypeError, ValueError):
            continue                # an entry with no usable start (one of the provider's own assets): not one of ours
    return found


def check_span(items, code: str, system_code: str, first: date, last: date) -> dict[str, str]:
    """The rates of one response as {date: canonical rate text}, or an InvalidResponse. A date outside first..last is dropped: one
    after `last` because Northstar stores no rate dated after today, and one before `first` because where its data is sparse the
    provider also answers with the last observation before the range (a span from 2009-10-25 came back with 2009-10-24), which
    belongs to the span before. Anything else wrong rejects the whole span."""
    bad = scheduler.InvalidResponse("The rate provider sent rates that could not be used.")
    if not isinstance(items, list):
        raise bad
    found: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict) or item.get("base") != code or item.get("quote") != system_code:
            raise bad
        day, text = item.get("date"), item.get("rate")
        if not isinstance(day, str) or not isinstance(text, str) or not day.isascii():
            raise bad
        try:
            when = date.fromisoformat(day)
            rate = rates.parse_rate(text)
        except (ValueError, ValidationError):
            raise bad from None
        if when < first or when > last:
            continue
        if day in found:
            raise bad
        found[day] = rate
    return found


def store(conn, currency_id: int, found: dict[str, str], kind: str) -> int:
    """Add the dates that have no rate yet, as the system user, and return how many were added. A stored rate is never touched."""
    if not found:
        return 0
    op = Operation(conn, None, kind)
    have = {row[0] for row in conn.execute("SELECT rate_date FROM exchange_rates WHERE currency_id = ? AND rate_date BETWEEN ? AND ?",
                                           (currency_id, min(found), max(found)))}
    added = 0
    for day in sorted(found):
        if day not in have:
            writer.insert(op, "exchange_rates", {"currency_id": currency_id, "rate_date": day, "rate": found[day], "source": "provider"})
            added += 1
    return added


def fetch_currency(ctx, currency, system_code: str, coverage: dict[str, date], today: date) -> None:
    """Fill the gaps of one currency, newest span first, each span committed on its own. Raises InvalidResponse for this
    currency, which stops it so nothing is left with a hole, and Retryable, which stops the whole run to be tried again."""
    code = currency["code"]
    provider_start = coverage.get(code)
    if provider_start is None:
        return
    kind = "scheduled" if ctx.started_by == "scheduled" else "cli"
    for gap_first, gap_last in gaps(ctx.conn, currency["id"], date.fromisoformat(currency["rates_start"]), today):
        for first, last in spans(max(gap_first, provider_start), gap_last):
            ctx.check()
            url = f"{PROVIDER}/rates?base={code}&quotes={system_code}&from={first.isoformat()}&to={last.isoformat()}"
            found = check_span(get_json(url, ctx.call_timeout(CALL_TIMEOUT_SECONDS)), code, system_code, first, last)
            ctx.commit(lambda conn: store(conn, currency["id"], found, kind))


def run(ctx) -> None:
    """The job. Currencies are fetched one after another. A currency whose rates are invalid is named in the failure at the
    end, after the others have been fetched and committed."""
    conn = ctx.conn
    system = currencies.system_currency(conn)
    wanted = [] if system is None else collected(conn, system.id)
    if not wanted:
        return
    today = ctx.now().astimezone(scheduler.zone_of(conn)).date()
    coverage = read_coverage(ctx)
    refused = []
    for currency in wanted:
        try:
            fetch_currency(ctx, currency, system.code, coverage, today)
        except scheduler.InvalidResponse:
            refused.append(currency["code"])
    if refused:
        raise scheduler.InvalidResponse(f"The provider sent rates that could not be used for {', '.join(refused)}.")


def status(conn) -> dict:
    """What the currency page says about the fetch: its start time (None when off), the zone it is read in, and the last run."""
    zone = scheduler.zone_of(conn)
    last = conn.execute("SELECT started_at, outcome, detail FROM sys_job_runs WHERE job = ? ORDER BY id DESC LIMIT 1", (JOB,)).fetchone()
    run_info = None
    if last is not None:
        local = datetime.strptime(last["started_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone(zone)
        run_info = {"date": local.date().isoformat(), "time": local.strftime("%H:%M"), "outcome": last["outcome"],
                    "detail": last["detail"]}
    name = system_properties.get_value(conn, system_properties.SYSTEM_TIMEZONE)
    return {"time": system_properties.get_value(conn, TIME_PROPERTY), "zone": name or "UTC", "last_run": run_info}
