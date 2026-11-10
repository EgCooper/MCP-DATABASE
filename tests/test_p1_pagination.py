"""Regression coverage for report and nested customer pagination."""

import json

import pytest

from mcp_mysql import tickets, tools
from mcp_mysql.responses import MAX_RESPONSE_BYTES, encode_response
from test_support_tools import database, data


def test_report_pages_beyond_one_hundred_groups(database):
    rows = [{"group_key": i, "label": f"Company {i}", "tickets": 1} for i in range(125)]
    database.on("GROUP BY group_key", lambda params: rows[params[-1]:params[-1] + params[-2]])
    database.on("COUNT(*) AS total", [{"total": 125}])
    first = data(tools.ticket_report("company", limit=100))
    second = data(tools.ticket_report("company", limit=100, offset=first["next_offset"]))
    assert first["next_offset"] == 100 and first["has_more"]
    assert second["next_offset"] is None and not second["has_more"]
    assert [g["key"] for page in (first, second) for g in page["groups"]] == list(range(125))
    assert first["total_tickets"] == second["total_tickets"] == 125
    assert first["filters"] == second["filters"] == {}


def test_response_byte_limit_adjusts_report_continuation():
    groups = [{"key": i, "label": "😀" * 4000, "tickets": 1} for i in range(100)]
    encoded = encode_response({"groups": groups, "group_count": 100, "offset": 17,
                               "next_offset": None, "has_more": False, "pagination_limit_reached": False})
    result = json.loads(encoded)
    page = result["data"]
    assert len(encoded.encode()) <= MAX_RESPONSE_BYTES and result["meta"]["truncated"]
    assert 0 < page["group_count"] < 100
    assert page["next_offset"] == 17 + page["group_count"] and page["has_more"]
    assert [g["key"] for g in page["groups"]] == list(range(page["group_count"]))


def test_report_pagination_cap_is_explicit(database):
    database.on("GROUP BY group_key", [{"group_key": i, "tickets": 1} for i in range(3)])
    database.on("COUNT(*) AS total", [{"total": 20000}])
    page = data(tools.ticket_report("user", limit=2, offset=10000))
    assert page["has_more"] and page["pagination_limit_reached"] and page["next_offset"] is None


def profile(database):
    database.on("FROM ost_user u WHERE u.id = %s", [{"user_id": 8, "name": "Cliente", "default_email_id": 1}])
    database.on("COUNT(*) AS total", [{"total": 0}])


def test_profile_independent_pages_recover_all_emails_and_company_groups(database):
    profile(database)
    emails = [{"id": i, "address": f"u{i}@example.test"} for i in range(1, 24)]
    # A null company group must still advance the offset.
    companies = [{"group_key": None, "tickets": 2}] + [
        {"group_key": i, "label": f"C{i}", "tickets": 1} for i in range(1, 13)]
    database.on("FROM ost_user_email WHERE user_id", lambda params: emails[params[-1]:params[-1] + 21])
    database.on("GROUP BY group_key", lambda params: (
        companies[params[-1]:params[-1] + params[-2]] if params[-2] == 11 else []))
    first = data(tools.get_user(8))["rows"][0]
    assert len(first["emails"]) == 20 and len(first["companies"]) == 9
    assert first["emails"][0]["is_default"] is True
    second = data(tools.get_user(8, emails_offset=first["emails_pagination"]["next_offset"],
                                 companies_offset=first["companies_pagination"]["next_offset"]))["rows"][0]
    assert [e["address"] for p in (first, second) for e in p["emails"]] == [e["address"] for e in emails]
    assert [c["company_id"] for p in (first, second) for c in p["companies"]] == list(range(1, 13))
    assert not second["emails_pagination"]["has_more"] and not second["companies_pagination"]["has_more"]
    assert second["emails_pagination"]["next_offset"] is None


@pytest.mark.parametrize("missing_table", ["ost_user_email", "ost_list_items", "ost_thread", "ost_thread_collaborator"])
def test_profile_reports_unavailable_sections(database, missing_table):
    profile(database)
    database.schema.columns.pop(missing_table)
    result = data(tools.get_user(8))
    user = result["rows"][0]
    field = {"ost_user_email": "emails", "ost_list_items": "companies",
             "ost_thread": "tickets.as_collaborator", "ost_thread_collaborator": "tickets.as_collaborator"}[missing_table]
    assert field in result["unavailable_fields"]
    if field in ("emails", "companies"):
        assert user[field] is None and user[f"{field}_pagination"] is None
    else:
        assert user["tickets"]["as_collaborator"] is None


def test_profile_missing_optional_columns_does_not_invent_empty_values(database):
    profile(database)
    database.schema.columns["ost_user"].difference_update({"default_email_id", "status", "created", "updated"})
    database.schema.columns["ost_ticket_status"].remove("state")
    database.on("FROM ost_user_email WHERE user_id", [{"id": 1, "address": "u@example.test"}])
    result = data(tools.get_user(8))
    user = result["rows"][0]
    assert {"status", "created", "updated", "emails.is_default", "tickets.by_state"} <= set(result["unavailable_fields"])
    assert user["emails"][0]["is_default"] is None
    assert user["tickets"]["by_state"] is None and user["tickets"]["as_requester"] == 0


def test_profile_empty_available_sections_are_distinct_from_unavailable(database):
    profile(database)
    result = data(tools.get_user(8))
    user = result["rows"][0]
    assert user["emails"] == user["companies"] == []
    assert not user["emails_pagination"]["has_more"] and not user["companies_pagination"]["has_more"]
    assert "emails" not in result["unavailable_fields"] and "companies" not in result["unavailable_fields"]


@pytest.mark.parametrize("offset", [-1, 10001, True, "1", 1.5])
@pytest.mark.parametrize("tool,kwargs,field", [
    (tools.ticket_report, {"group_by": "company"}, "offset"),
    (tools.get_user, {"user_id": 8}, "emails_offset"),
    (tools.get_user, {"user_id": 8}, "companies_offset"),
])
def test_pagination_arguments_are_strict_before_database_access(database, offset, tool, kwargs, field):
    assert json.loads(tool(**kwargs, **{field: offset}))["error"]["code"] == "INVALID_ARGUMENTS"
    assert database.calls == []
