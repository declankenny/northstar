"""The report endpoints: who may ask, what each failure looks like on the wire, and that a broken report never sends a partial result.
Synthetic data only."""

import logging
from datetime import date

import pytest

from conftest import add_account, with_db
from northstar import clock
from northstar.networth import NoRate
from northstar.reports import loader
from northstar.reports.reportdef import ReportDef, ReportResult
from northstar.reports.sections import SectionDef
from reports_synthetic import register_all, unregister_all

TODAY = date(2026, 11, 11)


@pytest.fixture(autouse=True)
def reports(monkeypatch):
    register_all()
    monkeypatch.setattr(clock, "today", lambda: TODAY)
    yield
    unregister_all()


@pytest.fixture
def broken():
    """Reports that fail in each way a calculation can."""
    def make(key, calculate):
        loader.register(ReportDef(key, key.title(), "A broken report.", (), (SectionDef("s", "summary", "tiles", "S"),), calculate))

    def no_rate(ctx):
        raise NoRate("2026-01-01", ["EUR"])

    def explode(ctx):
        raise RuntimeError("balance 123456 of Secret Account")

    def wrong(ctx):
        return ReportResult({"s": {"items": [{"key": "a", "label": "A", "kind": "money", "value": 1.5}]}})

    for key, fn in (("probe_norate", no_rate), ("probe_explode", explode), ("probe_wrong", wrong)):
        make(key, fn)
    yield
    for key in ("probe_norate", "probe_explode", "probe_wrong"):
        loader._DEFINITIONS.pop(key, None)


def post(client, key, body):
    return client.post(f"/api/reports/{key}", json=body)


# -- who may ask --

def test_the_endpoints_need_a_signed_in_person(anon_client):
    assert anon_client.get("/api/reports").status_code == 401
    assert anon_client.get("/api/reports/synthetic_as_of").status_code == 401
    assert anon_client.post("/api/reports/synthetic_as_of", json={}).status_code == 401


def test_the_list_hides_admin_only_reports_from_a_member(client, member_client):
    assert [r["key"] for r in client.get("/api/reports").json()["reports"]] == ["synthetic_as_of", "synthetic_none", "synthetic_pair", "synthetic_range"]
    listed = member_client.get("/api/reports").json()["reports"]
    assert [r["key"] for r in listed] == ["synthetic_as_of", "synthetic_pair", "synthetic_range"]
    assert set(listed[0]) == {"key", "title", "description"}


def test_an_unknown_report_is_a_404_and_an_admin_only_one_is_a_403_for_a_member(client, member_client):
    assert client.get("/api/reports/nothing").status_code == 404
    assert post(client, "nothing", {}).status_code == 404
    assert member_client.get("/api/reports/synthetic_none").status_code == 403
    assert post(member_client, "synthetic_none", {"parameters": {}}).status_code == 403
    assert client.get("/api/reports/synthetic_none").status_code == 200


# -- describing --

def test_the_definition_carries_resolved_defaults_and_nothing_private(client):
    body = client.get("/api/reports/synthetic_pair").json()
    assert body["today"] == "2026-11-11"
    assert {p["key"]: p["default"] for p in body["parameters"]} == {"opening": "2025-11-11", "closing": "2026-11-11"}
    assert body["filters"] == {"enabled": False}
    assert body["sections"][0] == {"key": "detail", "kind": "rows", "view": "table", "title": "Detail", "sized": False, "columns": 12}
    assert not {"calculate", "population", "population_ids", "query", "sql"} & set(body)


def test_the_definition_carries_the_named_date_rules(client):
    body = client.get("/api/reports/synthetic_pair").json()
    assert {p["key"]: p["rules"] for p in body["parameters"]} == {
        "opening": [{"rule": "not_future"}], "closing": [{"rule": "not_future"}, {"rule": "after", "other": "opening"}]}
    body = client.get("/api/reports/synthetic_range").json()
    assert {p["key"]: p["rules"] for p in body["parameters"]}["end"] == [{"rule": "not_future"}, {"rule": "on_or_after", "other": "start"}]


def test_the_defaults_are_the_servers_not_the_browsers(client, monkeypatch):
    monkeypatch.setattr(clock, "today", lambda: date(2028, 2, 29))
    body = client.get("/api/reports/synthetic_pair").json()
    assert {p["key"]: p["default"] for p in body["parameters"]} == {"opening": "2027-02-28", "closing": "2028-02-29"}


# -- calculating --

def test_a_report_is_calculated_from_explicit_parameters(client):
    with with_db(client) as conn:
        add_account(conn, "Test one", 1, "Savings")
        add_account(conn, "Test two", 1, "Savings")
        conn.commit()
    response = post(client, "synthetic_pair", {"parameters": {"opening": "2026-01-01", "closing": "2026-06-30"}, "filters": []})
    assert response.status_code == 200
    body = response.json()
    assert body["parameters"] == {"opening": "2026-01-01", "closing": "2026-06-30"} and body["currency"]["code"] == "USD"
    assert len(body["sections"]["detail"]["rows"]) == 2 and body["notes"] == []


def test_an_omitted_parameter_is_a_422_that_says_which_and_the_server_does_not_default_it(client):
    response = post(client, "synthetic_pair", {"parameters": {"opening": "2026-01-01"}})
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_input" and response.json()["path"] == ["parameters", "closing"]
    assert "required" in response.json()["detail"]


def test_a_bad_value_is_a_422_with_a_path_and_a_message_to_show(client):
    body = post(client, "synthetic_pair", {"parameters": {"opening": "2026-06-30", "closing": "2026-01-01"}}).json()
    assert body["code"] == "invalid_input" and body["path"] == ["parameters", "closing"] and "after" in body["detail"]
    body = post(client, "synthetic_as_of", {"parameters": {"as_at": "2999-01-01"}}).json()
    assert body["path"] == ["parameters", "as_at"] and "future" in body["detail"]


@pytest.mark.parametrize("content", [b"[]", b'"text"', b"5", b"null", b"true", b"[1, 2]", b"{", b"not json"])
def test_a_body_that_is_not_a_json_object_is_the_report_error_contract_not_fastapis(client, content):
    response = client.post("/api/reports/synthetic_none", content=content, headers={"Content-Type": "application/json"})
    assert response.status_code == 422, content
    body = response.json()
    assert body["code"] == "invalid_input" and body["path"] == [] and isinstance(body["detail"], str)
    assert "loc" not in str(body) and "msg" not in body


def test_an_empty_body_is_an_empty_request_that_must_still_name_the_parameters(client):
    response = client.post("/api/reports/synthetic_none", content=b"", headers={"Content-Type": "application/json"})
    assert response.status_code == 422 and response.json()["code"] == "invalid_input" and response.json()["path"] == ["parameters"]


def test_an_unreadable_body_is_fastapis_own_answer_outside_reports(client):
    response = client.put("/api/lists/balances/page-size", content=b"{", headers={"Content-Type": "application/json"})
    assert response.status_code == 422 and "code" not in response.json()


def test_a_filter_is_a_422_until_filtering_exists(client):
    response = post(client, "synthetic_as_of", {"parameters": {"as_at": "2026-11-11"}, "filters": [{"field": "x", "operator": "is", "value": 1}]})
    assert response.status_code == 422 and response.json()["path"] == ["filters"] and response.json()["code"] == "invalid_input"


def test_a_missing_rate_is_unavailable_data_with_a_stable_code_and_reason(client, broken):
    response = post(client, "probe_norate", {"parameters": {}})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "unavailable_data" and body["reason"] == "missing_rates" and body["missing_rates"] == ["EUR"]
    assert "sections" not in body


def test_a_broken_report_is_a_500_with_no_result_and_no_detail_of_the_fault(client, broken, caplog):
    with caplog.at_level(logging.ERROR):
        response = post(client, "probe_explode", {"parameters": {}})
    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "calculation_error" and "sections" not in body
    assert "123456" not in response.text and "Secret" not in response.text and "RuntimeError" not in response.text
    assert any("probe_explode" in record.getMessage() for record in caplog.records)            # the diagnostic is in the log


def test_the_log_says_where_a_calculation_failed_and_never_what_it_said(client, broken, caplog):
    with caplog.at_level(logging.DEBUG):
        post(client, "probe_explode", {"parameters": {}})
    logged = caplog.text
    assert "123456" not in logged and "Secret Account" not in logged           # the exception's own message and traceback text
    assert not any(record.exc_info for record in caplog.records)             # no exception chain is attached to any record
    assert "probe_explode" in logged and "RuntimeError at" in logged and "explode" in logged     # where it happened is there


def test_a_wrong_result_is_the_same_safe_500(client, broken):
    response = post(client, "probe_wrong", {"parameters": {}})
    assert response.status_code == 500 and response.json()["code"] == "calculation_error" and "sections" not in response.json()


def test_the_three_failures_can_be_told_apart_by_code_alone(client, broken):
    codes = {post(client, "synthetic_as_of", {"parameters": {"as_at": "2999-01-01"}}).json()["code"],
             post(client, "probe_norate", {"parameters": {}}).json()["code"],
             post(client, "probe_explode", {"parameters": {}}).json()["code"]}
    assert codes == {"invalid_input", "unavailable_data", "calculation_error"}
