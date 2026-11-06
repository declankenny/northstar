"""Fetching exchange rates (#131): which currencies and which dates are asked for, what is stored, how a bad or absent provider is
handled, the run's record, the command line and the page. The provider is a fake, so nothing touches the network. Synthetic data only."""

import http.client
import io
import urllib.error
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from northstar import currencies, jobs, rate_fetch, rates, scheduler, system_properties as sp
from northstar.errors import ValidationError
from northstar.scheduler import Env, InvalidResponse, Retryable, run_due, run_now
from tests.conftest import op, type_id
from tests.test_scheduler import FakeClock, lock, make_env, runs

UTC = timezone.utc
TODAY = date(2026, 6, 3)
JOB = "currency.rates.fetch"


def day(offset=0, start=TODAY):
    return (start + timedelta(days=offset)).isoformat()


def rate_for(d: date) -> str:
    return f"{1 + (d.toordinal() % 50) / 1000:.4f}"


class Provider:
    """A stand-in for get_json. `covers` is {code: first date of data}, and every date from there to the asked `to` has a rate.
    `ahead` makes it also answer two days past `to`, as the real provider does for a weekend."""

    def __init__(self, covers, ahead=0, fail=None, bad=None):
        self.covers, self.ahead, self.fail, self.bad = covers, ahead, fail or {}, bad or {}
        self.urls, self.rate_calls = [], []

    def __call__(self, url, timeout):
        self.urls.append(url)
        parts = urlparse(url)
        if parts.path.endswith("/currencies"):
            return [{"iso_code": code, "start_date": start} for code, start in self.covers.items()]
        query = {k: v[0] for k, v in parse_qs(parts.query).items()}
        self.rate_calls.append(query)
        number = len(self.rate_calls)
        if number in self.fail:
            raise self.fail[number]
        code = query["base"]
        if code in self.bad:
            return self.bad[code](query)
        first = max(date.fromisoformat(query["from"]), date.fromisoformat(self.covers[code]))
        last = date.fromisoformat(query["to"]) + timedelta(days=self.ahead)
        count = (last - first).days + 1
        return [{"date": (first + timedelta(days=i)).isoformat(), "base": code, "quote": query["quotes"],
                 "rate": rate_for(first + timedelta(days=i))} for i in range(max(count, 0))]


@pytest.fixture
def provider(monkeypatch):
    def install(covers, **kw):
        fake = Provider(covers, **kw)
        monkeypatch.setattr(rate_fetch, "get_json", fake)
        return fake
    return install


def enable(conn, code, start="2026-05-01"):
    currencies.update_currency(op(conn), code, True, start, TODAY)


def put_provider(conn, code, first, last, rate="1.2000"):
    """Rates a past fetch stored: one row a day from first to last with source provider."""
    currency = conn.execute("SELECT id FROM currencies WHERE code = ?", (code,)).fetchone()[0]
    system = "(SELECT id FROM users WHERE is_system = 1)"
    for i in range((last - first).days + 1):
        conn.execute("INSERT INTO exchange_rates (currency_id, rate_date, rate, source, created_by, updated_by) "
                     f"VALUES (?, ?, ?, 'provider', {system}, {system})", (currency, (first + timedelta(days=i)).isoformat(), rate))


def stored(conn, code):
    return {r["rate_date"]: (r["rate"], r["source"]) for r in conn.execute(
        "SELECT rate_date, rate, source FROM exchange_rates e JOIN currencies c ON c.id = e.currency_id WHERE c.code = ?", (code,))}


def go(conn, at=None, registry=None):
    clock = FakeClock(at or datetime(2026, 6, 3, 18, 0, tzinfo=UTC))
    env = make_env(conn, registry or jobs.REGISTRY, clock)
    return run_due(env), env, clock


# -- which dates are asked for --

def test_a_first_fetch_stores_every_day_from_the_rates_start_to_today_as_provider_rates(conn, provider):
    enable(conn, "EUR")
    fake = provider({"EUR": "2000-01-01"})
    assert go(conn)[0] == [(JOB, "succeeded")]
    got = stored(conn, "EUR")
    assert sorted(got) == [day(i, date(2026, 5, 1)) for i in range(34)]
    assert got["2026-05-01"] == (rate_for(date(2026, 5, 1)), "provider") and {v[1] for v in got.values()} == {"provider"}
    assert fake.rate_calls == [{"base": "EUR", "quotes": "USD", "from": "2026-05-01", "to": "2026-06-03"}]
    assert runs(conn, JOB)[0]["detail"] == "Completed."


def test_the_direction_asked_for_is_the_foreign_currency_as_base_and_the_system_currency_as_quote(conn, provider):
    enable(conn, "JPY")
    fake = provider({"JPY": "2000-01-01"})
    go(conn)
    assert fake.rate_calls[0]["base"] == "JPY" and fake.rate_calls[0]["quotes"] == "USD"


def test_a_date_after_today_is_dropped(conn, provider):
    enable(conn, "EUR")
    provider({"EUR": "2000-01-01"}, ahead=2)           # the provider fills the weekend ahead
    go(conn)
    assert max(stored(conn, "EUR")) == "2026-06-03"


def test_only_the_days_after_the_newest_provider_rate_are_asked_for_and_a_stored_rate_is_never_changed(conn, provider):
    enable(conn, "EUR")
    put_provider(conn, "EUR", date(2026, 5, 1), date(2026, 6, 1))
    rates.add_rate(op(conn), "EUR", "2026-06-02", "7.7777", TODAY)               # typed after the last fetch
    fake = provider({"EUR": "2000-01-01"})
    go(conn)
    assert fake.rate_calls == [{"base": "EUR", "quotes": "USD", "from": "2026-06-02", "to": "2026-06-03"}]
    got = stored(conn, "EUR")
    assert got["2026-06-02"] == ("7.7777", "manual") and got["2026-06-01"] == ("1.2000", "provider")
    assert got["2026-06-03"][1] == "provider"


def test_a_corrected_provider_rate_is_not_overwritten_either(conn, provider):
    enable(conn, "EUR")
    provider({"EUR": "2000-01-01"})
    go(conn)
    rate_id = conn.execute("SELECT id FROM exchange_rates WHERE rate_date = '2026-06-03'").fetchone()[0]
    rates.correct_rate(op(conn), "EUR", rate_id, "5.5555")
    conn.execute("DELETE FROM sys_job_runs")
    go(conn)
    assert stored(conn, "EUR")["2026-06-03"] == ("5.5555", "manual")


def test_history_before_the_oldest_provider_rate_is_fetched_once_and_nothing_is_asked_for_when_nothing_is_missing(conn, provider):
    enable(conn, "EUR", "2026-04-01")
    put_provider(conn, "EUR", date(2026, 5, 1), date(2026, 5, 1))
    fake = provider({"EUR": "2000-01-01"})
    go(conn)
    assert {tuple(c[k] for k in ("from", "to")) for c in fake.rate_calls} == {("2026-05-02", "2026-06-03"), ("2026-04-01", "2026-04-30")}
    assert fake.rate_calls[0]["from"] == "2026-05-02"           # the newest gap first
    assert min(stored(conn, "EUR")) == "2026-04-01" and stored(conn, "EUR")["2026-05-01"] == ("1.2000", "provider")
    conn.execute("DELETE FROM sys_job_runs")
    fake.rate_calls.clear()
    go(conn, at=datetime(2026, 6, 3, 19, 0, tzinfo=UTC))
    assert fake.rate_calls == []


def test_a_long_gap_is_asked_for_in_spans_of_at_most_a_year_newest_first_and_each_is_stored_on_its_own(conn, provider):
    enable(conn, "EUR", "2024-01-01")
    fake = provider({"EUR": "2000-01-01"})
    go(conn)
    spans = [(date.fromisoformat(c["from"]), date.fromisoformat(c["to"])) for c in fake.rate_calls]
    assert len(spans) == 3 and spans[0][1] == TODAY
    assert all((b - a).days + 1 <= rate_fetch.SPAN_DAYS for a, b in spans)
    assert all(spans[i][0] == spans[i + 1][1] + timedelta(days=1) for i in range(2)) and spans[-1][0] == date(2024, 1, 1)
    assert len(stored(conn, "EUR")) == (TODAY - date(2024, 1, 1)).days + 1


def test_a_manual_rate_far_from_the_rest_does_not_make_the_fetch_think_the_history_is_covered(conn, provider):
    enable(conn, "EUR", "2024-01-01")
    rates.add_rate(op(conn), "EUR", "2024-01-01", "9.9999", TODAY)             # typed at the far edge, as the start date
    rates.add_rate(op(conn), "EUR", "2025-03-01", "8.8888", TODAY)
    fake = provider({"EUR": "2000-01-01"}, fail={n: Retryable("The rate provider did not answer.") for n in range(3, 7)})
    assert go(conn)[0] == [(JOB, "failed")]                                    # the third span never arrived: two of three are stored
    assert len(stored(conn, "EUR")) < (TODAY - date(2024, 1, 1)).days + 1
    fake.rate_calls.clear()
    assert go(conn, at=datetime(2026, 6, 4, 18, 0, tzinfo=UTC))[0] == [(JOB, "succeeded")]
    got = stored(conn, "EUR")
    assert sorted(got) == [day(i, date(2024, 1, 1)) for i in range((date(2026, 6, 4) - date(2024, 1, 1)).days + 1)]       # no hole anywhere
    assert got["2024-01-01"] == ("9.9999", "manual") and got["2025-03-01"] == ("8.8888", "manual")


def test_where_the_providers_history_is_sparse_the_answer_that_starts_before_the_span_is_still_accepted(conn, provider):
    enable(conn, "EUR", "2026-05-20")

    def carry_in(q):
        return [{"date": "2026-05-19", "base": "EUR", "quote": "USD", "rate": "1.0000"},
                {"date": q["from"], "base": "EUR", "quote": "USD", "rate": "1.1000"}]
    provider({"EUR": "2000-01-01"}, bad={"EUR": carry_in})
    assert go(conn)[0] == [(JOB, "succeeded")]
    assert stored(conn, "EUR") == {"2026-05-20": ("1.1000", "provider")}


def test_the_window_starts_no_earlier_than_the_providers_own_data(conn, provider):
    enable(conn, "EUR", "2024-01-01")
    fake = provider({"EUR": "2025-06-01"})
    go(conn)
    assert min(stored(conn, "EUR")) == "2025-06-01" and min(c["from"] for c in fake.rate_calls) == "2025-06-01"
    fake.rate_calls.clear()
    conn.execute("DELETE FROM sys_job_runs")
    go(conn, at=datetime(2026, 6, 3, 19, 0, tzinfo=UTC))
    assert fake.rate_calls == []                                     # the days before the provider's data are not asked for again


def test_today_is_the_date_in_the_installation_zone(conn, provider):
    sp.set_property(op(conn), "system.timezone", "America/Chicago")
    enable(conn, "EUR", "2026-06-01")
    fake = provider({"EUR": "2000-01-01"})
    sp.set_property(op(conn), "currency.rate.fetch_time", "20:00")
    go(conn, at=datetime(2026, 6, 4, 2, 0, tzinfo=UTC))             # 21:00 on June 3 in Chicago, June 4 in UTC
    assert fake.rate_calls[0]["to"] == "2026-06-03"


# -- which currencies --

def test_the_system_currency_and_a_disabled_currency_with_no_open_account_are_not_collected(conn, provider):
    enable(conn, "EUR")
    enable(conn, "GBP")
    currencies.update_currency(op(conn), "GBP", False, None, TODAY)
    fake = provider({"EUR": "2000-01-01", "GBP": "2000-01-01", "USD": "2000-01-01"})
    go(conn)
    assert {c["base"] for c in fake.rate_calls} == {"EUR"}


def test_a_disabled_currency_with_an_open_account_is_still_collected_and_a_closed_one_is_not(conn, provider):
    enable(conn, "EUR")
    rates.add_rate(op(conn), "EUR", "2026-05-01", "1.1000", TODAY)
    from northstar import balances
    balances.add_account_with_balance(op(conn), "asset", "Test euros", type_id(conn, "Savings"), None, "10.00",
                                                "2026-05-12", TODAY, None, "EUR")
    currencies.update_currency(op(conn), "EUR", False, None, TODAY)
    fake = provider({"EUR": "2000-01-01"})
    go(conn)
    assert {c["base"] for c in fake.rate_calls} == {"EUR"}
    conn.execute("UPDATE accounts SET is_open = 0")
    fake.rate_calls.clear()
    conn.execute("DELETE FROM sys_job_runs")
    go(conn, at=datetime(2026, 6, 4, 18, 0, tzinfo=UTC))
    assert fake.rate_calls == []


def test_a_currency_the_provider_does_not_list_is_skipped_without_failing_the_run(conn, provider):
    enable(conn, "EUR")
    enable(conn, "KWD")
    fake = provider({"EUR": "2000-01-01"})
    assert go(conn)[0] == [(JOB, "succeeded")]
    assert {c["base"] for c in fake.rate_calls} == {"EUR"} and stored(conn, "KWD") == {}


def test_nothing_is_asked_when_there_is_nothing_to_collect_or_no_system_currency(conn, provider):
    fake = provider({"EUR": "2000-01-01"})
    assert go(conn)[0] == [(JOB, "succeeded")] and fake.urls == []
    conn.execute("UPDATE system_properties SET value = NULL, read_only = 0 WHERE name = 'system.currency'")
    conn.execute("UPDATE currencies SET is_enabled = 1, rates_start = '2026-05-01' WHERE code = 'EUR'")
    conn.execute("DELETE FROM sys_job_runs")
    go(conn, at=datetime(2026, 6, 4, 18, 0, tzinfo=UTC))
    assert fake.urls == []


# -- what is accepted --

@pytest.mark.parametrize("name, mutate", [
    ("not a list", lambda q: {"rate": "1.1"}),
    ("an item that is not an object", lambda q: ["x"]),
    ("the wrong base", lambda q: [{"date": q["from"], "base": "GBP", "quote": "USD", "rate": "1.1"}]),
    ("the wrong quote", lambda q: [{"date": q["from"], "base": "EUR", "quote": "GBP", "rate": "1.1"}]),
    ("a rate in scientific notation", lambda q: [{"date": q["from"], "base": "EUR", "quote": "USD", "rate": "1e-05"}]),
    ("a rate of zero", lambda q: [{"date": q["from"], "base": "EUR", "quote": "USD", "rate": "0.0"}]),
    ("a negative rate", lambda q: [{"date": q["from"], "base": "EUR", "quote": "USD", "rate": "-1.5"}]),
    ("too many digits", lambda q: [{"date": q["from"], "base": "EUR", "quote": "USD", "rate": "1.1234567890123"}]),
    ("a rate that is not text", lambda q: [{"date": q["from"], "base": "EUR", "quote": "USD", "rate": None}]),
    ("a date that is not a date", lambda q: [{"date": "tomorrow", "base": "EUR", "quote": "USD", "rate": "1.1"}]),
    ("a date twice", lambda q: [{"date": q["from"], "base": "EUR", "quote": "USD", "rate": "1.1"}] * 2),
])
def test_a_span_with_anything_unusable_is_rejected_whole_and_nothing_of_that_currency_is_stored(conn, provider, name, mutate):
    enable(conn, "EUR")
    enable(conn, "GBP")
    provider({"EUR": "2000-01-01", "GBP": "2000-01-01"}, bad={"EUR": mutate})
    result, env, _ = go(conn)
    assert result == [(JOB, "failed")]
    assert runs(conn, JOB)[0]["detail"] == "Invalid response: The provider sent rates that could not be used for EUR."
    assert stored(conn, "EUR") == {} and len(stored(conn, "GBP")) == 34        # the others were fetched and kept


def test_rates_are_stored_as_the_providers_own_decimal_text_and_a_whole_number_rate_is_accepted(conn, provider):
    enable(conn, "JPY", "2026-06-02")

    def series(q):
        return [{"date": "2026-06-02", "base": "JPY", "quote": "USD", "rate": "0.0063614"},
                {"date": "2026-06-03", "base": "JPY", "quote": "USD", "rate": "1"}]
    provider({"JPY": "2000-01-01"}, bad={"JPY": series})
    go(conn)
    assert stored(conn, "JPY") == {"2026-06-02": ("0.0063614", "provider"), "2026-06-03": ("1", "provider")}


def test_the_check_of_a_span_keeps_dates_inside_it_and_drops_earlier_and_later_ones():
    items = [{"date": d, "base": "EUR", "quote": "USD", "rate": "1.5"} for d in ("2026-05-31", "2026-06-02", "2026-06-03", "2026-06-04")]
    assert rate_fetch.check_span(items, "EUR", "USD", date(2026, 6, 1), date(2026, 6, 3)) == {"2026-06-02": "1.5", "2026-06-03": "1.5"}
    assert rate_fetch.check_span([], "EUR", "USD", date(2026, 6, 1), date(2026, 6, 3)) == {}


def test_a_rate_is_stored_only_for_a_date_that_has_none_even_if_one_appears_between_the_fetch_and_the_commit(conn):
    enable(conn, "EUR")
    rates.add_rate(op(conn), "EUR", "2026-06-02", "4.4444", TODAY)
    currency = conn.execute("SELECT id FROM currencies WHERE code = 'EUR'").fetchone()[0]
    added = rate_fetch.store(conn, currency, {"2026-06-01": "1.0", "2026-06-02": "2.0", "2026-06-03": "3.0"}, "scheduled")
    assert added == 2 and stored(conn, "EUR")["2026-06-02"] == ("4.4444", "manual")
    assert rate_fetch.store(conn, currency, {}, "scheduled") == 0


# -- failures --

def test_a_provider_that_does_not_answer_is_retried_and_what_was_committed_is_kept_and_not_fetched_again(conn, provider):
    enable(conn, "EUR", "2024-01-01")
    fake = provider({"EUR": "2000-01-01"}, fail={2: Retryable("The rate provider did not answer.")})
    result, env, clock = go(conn)
    assert result == [(JOB, "succeeded")]
    assert len(stored(conn, "EUR")) == (TODAY - date(2024, 1, 1)).days + 1
    firsts = [c["from"] for c in fake.rate_calls]
    assert len(firsts) == len(set(firsts)) + 1 and fake.rate_calls[1]["from"] == fake.rate_calls[2]["from"]   # only the span that failed was asked twice
    assert clock.at >= datetime(2026, 6, 3, 18, 0, 30, tzinfo=UTC)                                    # it paused before trying again


def test_a_provider_that_never_answers_fails_the_run_after_the_retries_and_the_next_run_mends_it(conn, provider):
    enable(conn, "EUR")
    fake = provider({"EUR": "2000-01-01"}, fail={n: Retryable("The rate provider did not answer.") for n in range(1, 5)})
    result, env, clock = go(conn)
    assert result == [(JOB, "failed")]
    assert runs(conn, JOB)[0]["detail"].startswith("Could not complete: Gave up after 4 tries")
    assert stored(conn, "EUR") == {} and lock(conn, JOB) == (None, None)
    result, _, _ = go(conn, at=datetime(2026, 6, 4, 18, 0, tzinfo=UTC))                        # tomorrow
    assert result == [(JOB, "succeeded")]
    assert max(stored(conn, "EUR")) == "2026-06-04"


def test_a_failure_never_carries_provider_text_into_the_run_or_the_log(conn, provider, caplog):
    enable(conn, "EUR")
    secret = "https://user:hunter2@api.example.com/x?key=abc123"
    provider({"EUR": "2000-01-01"}, bad={"EUR": lambda q: [{"date": secret, "base": "EUR", "quote": "USD", "rate": secret}]})
    go(conn)
    assert "hunter2" not in runs(conn, JOB)[0]["detail"] and "hunter2" not in caplog.text and "abc123" not in caplog.text


# -- the run's record and who made the rates --

def test_scheduled_rates_are_an_operation_of_kind_scheduled_by_the_system_user_and_a_command_line_run_is_cli(conn, provider):
    enable(conn, "EUR", "2026-06-02")
    provider({"EUR": "2000-01-01"})
    go(conn)
    system = conn.execute("SELECT id FROM users WHERE is_system = 1").fetchone()[0]
    header = conn.execute("SELECT kind, user_id FROM sys_operations ORDER BY id DESC LIMIT 1").fetchone()
    assert (header["kind"], header["user_id"]) == ("scheduled", system)
    assert conn.execute("SELECT COUNT(*) FROM sys_record_changes WHERE tablename = 'exchange_rates' AND change = 'INSERT'").fetchone()[0] == 2
    clock = FakeClock(datetime(2026, 6, 4, 19, 0, tzinfo=UTC))             # the next day has one new rate to add
    assert run_now(make_env(conn, jobs.REGISTRY, clock), jobs.REGISTRY[0]) == "succeeded"
    header = conn.execute("SELECT kind FROM sys_operations ORDER BY id DESC LIMIT 1").fetchone()
    assert header["kind"] == "cli" and runs(conn, JOB)[-1]["started_by"] == "manual"


def test_the_job_is_registered_with_its_time_property_and_the_property_starts_at_18_00_and_can_be_cleared(conn):
    assert [(j.name, j.time_property) for j in jobs.REGISTRY] == [(JOB, "currency.rate.fetch_time")]
    assert sp.get_value(conn, "currency.rate.fetch_time") == "18:00"
    assert sp.set_property(op(conn), "currency.rate.fetch_time", "") is None


def test_the_fetch_is_due_at_its_time_and_off_when_the_time_is_empty(conn, provider):
    enable(conn, "EUR")
    fake = provider({"EUR": "2000-01-01"})
    assert go(conn, at=datetime(2026, 6, 3, 17, 59, tzinfo=UTC))[0] == []
    sp.set_property(op(conn), "currency.rate.fetch_time", "")
    assert go(conn, at=datetime(2026, 6, 3, 23, 0, tzinfo=UTC))[0] == [] and fake.urls == []
    sp.set_property(op(conn), "currency.rate.fetch_time", "18:00")
    assert go(conn, at=datetime(2026, 6, 3, 18, 0, tzinfo=UTC))[0] == [(JOB, "succeeded")]


# -- talking to the provider --

class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def reply(monkeypatch, body=None, error=None):
    def urlopen(request, timeout):
        assert request.get_header("User-agent").startswith("Northstar/") and "@" not in request.get_header("User-agent")
        if error:
            raise error
        return Response(body)
    monkeypatch.setattr(rate_fetch.urllib.request, "urlopen", urlopen)


def http_error(code):
    return urllib.error.HTTPError("https://api.example.com/secret?key=abc123", code, "x", {}, io.BytesIO(b"{}"))


@pytest.mark.parametrize("error", [http_error(429), http_error(500), http_error(503), urllib.error.URLError("boom"), TimeoutError("slow"),
                                   ConnectionResetError("reset"), http.client.IncompleteRead(b"x")])
def test_a_provider_that_is_busy_or_not_answering_is_retryable(monkeypatch, error):
    reply(monkeypatch, error=error)
    with pytest.raises(Retryable) as caught:
        rate_fetch.get_json("https://api.example.com/x", 5)
    assert "abc123" not in caught.value.message and "example.com" not in caught.value.message


@pytest.mark.parametrize("code", [400, 404, 422])
def test_a_provider_that_refuses_a_request_is_an_invalid_response_and_not_retried(monkeypatch, code):
    reply(monkeypatch, error=http_error(code))
    with pytest.raises(InvalidResponse):
        rate_fetch.get_json("https://api.example.com/x", 5)


def test_an_answer_that_is_not_json_or_is_too_large_is_an_invalid_response(monkeypatch):
    reply(monkeypatch, body=b"<html>not json</html>")
    with pytest.raises(InvalidResponse):
        rate_fetch.get_json("https://api.example.com/x", 5)
    reply(monkeypatch, body=b" " * (rate_fetch.MAX_BODY_BYTES + 10))
    with pytest.raises(InvalidResponse):
        rate_fetch.get_json("https://api.example.com/x", 5)


def test_numbers_in_an_answer_stay_as_their_own_text(monkeypatch):
    reply(monkeypatch, body=b'[{"rate": 0.0063614, "n": 12, "big": 1.10}]')
    assert rate_fetch.get_json("https://api.example.com/x", 5) == [{"rate": "0.0063614", "n": "12", "big": "1.10"}]


# -- the command line --

def test_the_command_line_fetches_now_and_says_so(tmp_path, monkeypatch, capsys, provider):
    from northstar.web.app import create_app
    from northstar import db
    path = tmp_path / "cli.db"
    create_app(path)
    with db.connect(path) as conn:
        sp.set_property(op(conn), "system.currency", "USD")
        conn.execute("UPDATE currencies SET is_enabled = 1, rates_start = '2026-06-01' WHERE code = 'EUR'")
    monkeypatch.setenv("NORTHSTAR_DB", str(path))
    provider({"EUR": "2000-01-01"})
    monkeypatch.setattr(scheduler.clock, "now", lambda: datetime(2026, 6, 3, 9, 0, tzinfo=UTC))
    assert rates.main(["fetch"]) == 0
    assert "Rates fetched." in capsys.readouterr().out
    with db.connect(path) as conn:
        assert max(stored(conn, "EUR")) == "2026-06-03" and runs(conn, JOB)[0]["started_by"] == "manual"


def test_the_command_line_is_refused_while_a_fetch_is_running_and_reports_a_failure(tmp_path, monkeypatch, capsys, provider):
    from northstar.web.app import create_app
    from northstar import db
    path = tmp_path / "cli.db"
    create_app(path)
    monkeypatch.setenv("NORTHSTAR_DB", str(path))
    monkeypatch.setattr(scheduler.clock, "now", lambda: datetime(2026, 6, 3, 9, 0, tzinfo=UTC))
    with db.connect(path) as conn:
        scheduler.seed(conn, jobs.REGISTRY)
        held = scheduler.claim(conn, JOB, "2026-06-03", "scheduled", datetime(2026, 6, 3, 9, 0, tzinfo=UTC))
    assert rates.main(["fetch"]) == 1
    assert "already running" in capsys.readouterr().err
    with db.connect(path) as conn:
        scheduler.finish(conn, JOB, held[0], held[1], "succeeded", "Done.", datetime(2026, 6, 3, 9, 1, tzinfo=UTC))
        sp.set_property(op(conn), "system.currency", "USD")
        conn.execute("UPDATE currencies SET is_enabled = 1, rates_start = '2026-06-01' WHERE code = 'EUR'")
    provider({"EUR": "2000-01-01"}, bad={"EUR": lambda q: {"nope": 1}})
    assert rates.main(["fetch"]) == 1
    assert "could not be used for EUR" in capsys.readouterr().out


def test_the_command_line_says_when_there_is_no_database(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NORTHSTAR_DB", str(tmp_path / "missing.db"))
    assert rates.main(["fetch"]) == 1
    assert "There is no database" in capsys.readouterr().err


# -- what the currency page says --

def test_the_page_status_says_when_it_runs_where_and_what_the_last_run_did(conn, provider):
    assert rate_fetch.status(conn) == {"time": "18:00", "zone": "UTC", "last_run": None}
    sp.set_property(op(conn), "system.timezone", "America/Chicago")
    enable(conn, "EUR")
    provider({"EUR": "2000-01-01"})
    go(conn, at=datetime(2026, 6, 3, 23, 30, tzinfo=UTC))          # 18:30 in Chicago
    assert rate_fetch.status(conn) == {"time": "18:00", "zone": "America/Chicago",
                                       "last_run": {"date": "2026-06-03", "time": "18:30", "outcome": "succeeded", "detail": "Completed."}}
    sp.set_property(op(conn), "currency.rate.fetch_time", "")
    assert rate_fetch.status(conn)["time"] is None


def test_the_currency_page_carries_the_fetch_status_only_where_rates_can_be_added(client, provider):
    from northstar import db
    with db.connect(client.app.state.db_path) as conn:
        enable(conn, "EUR")
    page = client.get("/api/currencies/EUR").json()
    assert page["fetch"] == {"time": "18:00", "zone": "UTC", "last_run": None}
    assert client.get("/api/currencies/USD").json()["fetch"] is None
    assert client.get("/api/currencies/GBP").json()["fetch"] is None            # not enabled, no accounts


def test_the_page_lists_a_provider_rate_with_the_source_provider(client, provider):
    from northstar import db
    with db.connect(client.app.state.db_path) as conn:
        enable(conn, "EUR", "2026-06-03")
        rates.add_rate(op(conn), "EUR", "2026-06-02", "1.1000", TODAY)
    body = client.get("/api/currencies/EUR").json()
    assert [r["source"] for r in body["rates"]] == ["manual"]
