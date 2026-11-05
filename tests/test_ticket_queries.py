"""Argument, policy, schema drift and continuation regressions for business tools."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mcp_mysql import access, db, tickets, tools
from mcp_mysql.responses import encode_response
from mcp_mysql.server import mcp


@pytest.fixture
def database(monkeypatch):
    connection = Mock(side_effect=AssertionError("Unit tests must not connect to MySQL"))
    monkeypatch.setattr(db, "get_connection", connection)
    fetch, one = Mock(return_value=[]), Mock(return_value={"total": 12345})
    monkeypatch.setattr(db, "fetch_all", fetch)
    monkeypatch.setattr(db, "fetch_one", one)
    schema = tickets.Schema({table: {c.casefold() for c in cols} for table, cols in access.ALLOWED_TABLE_COLUMNS.items()})
    loader = Mock(return_value=schema)
    monkeypatch.setattr(tickets, "_load_schema", loader)
    yield SimpleNamespace(fetch=fetch, one=one, schema=schema, loader=loader)
    connection.assert_not_called()


@pytest.mark.parametrize("name,arguments", [
    ("search_tickets", {"staff_id": True}),
    ("search_tickets", {"user_id": "12"}),
    ("search_tickets", {"company_id": 0}),
    ("search_tickets", {"status": "  "}),
    ("search_tickets", {"subject": "x\x00y"}),
    ("search_tickets", {"created_from": "2026-02-30"}),
    ("search_tickets", {"created_from": "2026-1-01"}),
    ("search_tickets", {"created_to": "9999-12-31"}),
    ("search_tickets", {"created_from": "2026-11-06", "created_to": "2026-11-05"}),
    ("search_tickets", {"created_to": "2026-11-05T12:00:00Z"}),
    ("search_tickets", {"order": "created DESC; DROP TABLE ost_ticket"}),
    ("search_tickets", {"offset": -1}),
    ("search_tickets", {"offset": 10001}),
    ("search_tickets", {"offset": True}),
    ("search_tickets", {"limit": 51}),
    ("search_tickets", {"where": "1=1"}),
    ("count_tickets", {"limit": 1}),
    ("count_tickets", {"created_from": "tomorrow"}),
    ("get_ticket", {}),
    ("get_ticket", {"ticket_id": 1, "number": "000001"}),
    ("get_ticket", {"number": 123}),
    ("get_ticket_thread", {"ticket_id": 1, "after_entry_id": -1}),
    ("get_ticket_thread", {"ticket_id": 1, "after_entry_id": "3"}),
    ("find_agents", {"name": "x"}),
    ("find_users", {"name": "xy", "offset": 10001}),
])
def test_invalid_arguments_fail_before_any_database_work(database, name, arguments):
    result = asyncio.run(mcp.call_tool(name, arguments))
    assert result.isError is True
    assert json.loads(result.content[0].text)["error"]["code"] == "INVALID_ARGUMENTS"
    database.loader.assert_not_called()
    database.fetch.assert_not_called()
    database.one.assert_not_called()


def test_filters_are_bound_together_and_to_date_includes_the_entire_day(database):
    result = json.loads(tools.search_tickets(
        staff_id=7, user_id=8, status=" Resuelto ", subject="_%= ' OR 1=1 --",
        created_from="2026-02-28", created_to="2026-02-28", offset=50, limit=1, order="oldest",
    ))
    assert result["ok"] is True
    query, params = database.fetch.call_args.args
    assert "ORDER BY t.created ASC, t.ticket_id ASC" in query
    assert params[-8:] == (7, 8, "Resuelto", "%=_=%== ' OR 1==1 --%", "2026-02-28", "2026-03-01", 2, 50)
    assert "1=1 --" not in query
    assert query.count("%s") == len(params)


def test_count_is_not_limited_by_the_sample_or_page_size(database):
    result = json.loads(tools.count_tickets(staff_id=7))
    assert result["data"] == {"total": 12345, "filters": {"staff_id": 7}}
    assert result["meta"]["is_sample"] is False
    query, params = database.one.call_args.args
    assert "COUNT(*)" in query and "LIMIT" not in query
    assert "JOIN" not in query
    assert params == (7,)


def test_absent_optional_fields_are_null_and_do_not_break_other_filters(database):
    database.schema.columns["ost_ticket__cdata"].remove("solucion")
    database.schema.columns.pop("ost_staff")
    result = json.loads(tools.search_tickets(staff_id=7))
    assert result["ok"] is True
    assert {"solution", "assigned_agent"}.issubset(result["data"]["unavailable_fields"])
    query = database.fetch.call_args.args[0]
    assert "NULL AS `solution`" in query and "NULL AS assigned_agent" in query
    assert "c.`solucion`" not in query and "JOIN `ost_staff`" not in query


def test_missing_cached_ticket_row_does_not_exclude_ticket_from_general_search(database):
    json.loads(tools.search_tickets())
    query = database.fetch.call_args.args[0]
    assert "LEFT JOIN `ost_ticket__cdata`" in query


def test_missing_filter_field_is_an_error_and_is_never_silently_ignored(database):
    database.schema.columns["ost_ticket__cdata"].remove("listaempresa")
    result = json.loads(tools.search_tickets(company_id=218))
    assert result["error"]["code"] == "SCHEMA_UNAVAILABLE"
    database.fetch.assert_not_called()
    database.one.assert_not_called()


def test_required_filter_must_still_be_permitted_by_policy(database, monkeypatch):
    restricted = dict(access.ALLOWED_TABLE_COLUMNS)
    restricted["ost_ticket"] = ("ticket_id", "created")
    monkeypatch.setattr(access, "ALLOWED_TABLE_COLUMNS", restricted)
    result = json.loads(tools.search_tickets(staff_id=7))
    assert result["error"]["code"] == "ACCESS_DENIED"
    database.fetch.assert_not_called()


@pytest.mark.parametrize("rows,code", [([], "NOT_FOUND"), ([{"ticket_id": 1}, {"ticket_id": 2}], "AMBIGUOUS_MATCH")])
def test_lookup_does_not_guess_when_number_is_missing_or_ambiguous(database, rows, code):
    database.fetch.return_value = rows
    result = json.loads(tools.get_ticket(number="000001"))
    assert result["error"]["code"] == code
    assert database.fetch.call_args.args[1][-1] == "000001"


def test_thread_is_restricted_to_the_requested_ticket_and_uses_an_entry_cursor(database):
    database.one.return_value = {"ticket_id": 90001}
    database.fetch.return_value = [{"entry_id": 201}, {"entry_id": 203}, {"entry_id": 205}]
    result = json.loads(tools.get_ticket_thread(90001, after_entry_id=200, limit=2))
    assert result["data"]["next_after_entry_id"] == 203
    assert result["data"]["has_more"] is True
    query, params = database.fetch.call_args.args
    assert "th.object_type = 'T'" in query and "th.object_id = %s" in query and "e.id > %s" in query
    assert params[-3:] == (90001, 200, 3)
    assert query.count("%s") == len(params)


@pytest.mark.parametrize("cursor", ["next_offset", "next_after_entry_id"])
def test_output_clipping_continues_from_the_last_returned_row(cursor):
    payload = {"rows": [{"entry_id": i + 200, "body": "😀" * 4000} for i in range(20)],
               "offset": 60, "has_more": False, cursor: None}
    result = json.loads(encode_response(payload))
    data = result["data"]
    assert result["meta"]["truncated"] is True
    assert 0 < data["row_count"] < 20 and data["has_more"] is True
    expected = 60 + data["row_count"] if cursor == "next_offset" else data["rows"][-1]["entry_id"]
    assert data[cursor] == expected


def test_pagination_never_advertises_an_offset_that_validation_would_reject(database):
    database.fetch.return_value = [{"ticket_id": i} for i in range(3)]
    data = json.loads(tools.search_tickets(offset=10000, limit=2))["data"]
    assert data["has_more"] is True and data["next_offset"] is None
    assert data["pagination_limit_reached"] is True


def test_clipping_can_restore_a_valid_continuation_before_the_offset_cap():
    payload = tickets.page_rows([{"body": "😀" * 4000} for _ in range(3)], limit=2, offset=9999)
    assert payload["pagination_limit_reached"] is True
    data = json.loads(encode_response(payload))["data"]
    assert data["row_count"] == 1 and data["next_offset"] == 10000
    assert data["pagination_limit_reached"] is False


def test_metadata_is_filtered_to_policy_and_parameterized(monkeypatch):
    fetch = Mock(return_value=[
        {"table_name": "ost_ticket__cdata", "column_name": "listaEmpresa"},
        {"table_name": "ost_staff", "column_name": "passwd"},
        {"table_name": "ost_api_key", "column_name": "key"},
    ])
    monkeypatch.setattr(db, "fetch_all", fetch)
    schema = tickets._load_schema()
    assert schema.has("ost_ticket__cdata", "listaEmpresa")
    assert not schema.has("ost_staff", "passwd") and not schema.has("ost_api_key", "key")
    query, params = fetch.call_args.args
    assert query.count("%s") == len(params)
    assert "passwd" not in params and "ost_api_key" not in params
