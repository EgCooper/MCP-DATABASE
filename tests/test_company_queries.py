"""Company lookups search beyond samples using fixed, policy-checked SQL."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mcp_mysql import access, db, tickets, tools
from mcp_mysql.config import MySQLConfig
from mcp_mysql.responses import encode_response
from mcp_mysql.server import mcp


@pytest.fixture
def database(monkeypatch):
    config = MySQLConfig(host="example.invalid", port=3306, user="readonly", password="dummy", database="test")
    monkeypatch.setattr(MySQLConfig, "from_env", Mock(return_value=config))
    connection = Mock(side_effect=AssertionError("Tests must not connect to MySQL"))
    monkeypatch.setattr(db, "get_connection", connection)
    fetch = Mock(return_value=[])
    one = Mock(return_value={"company_id": 218, "name": "HOSPICIO"})
    monkeypatch.setattr(db, "fetch_all", fetch)
    monkeypatch.setattr(db, "fetch_one", one)
    schema = tickets.Schema({table: {c.casefold() for c in cols} for table, cols in access.ALLOWED_TABLE_COLUMNS.items()})
    monkeypatch.setattr(tickets, "_load_schema", Mock(return_value=schema))
    yield SimpleNamespace(fetch=fetch, one=one)
    connection.assert_not_called()


def test_search_finds_company_ids_beyond_the_first_hundred_rows(database):
    database.fetch.return_value = [{"company_id": 218, "name": "HOSPICIO", "status": 1}]
    result = json.loads(tools.find_companies(" HOSPICIO "))
    assert result["ok"] is True and result["meta"]["is_sample"] is False
    assert result["data"]["rows"][0]["company_id"] == 218
    query, params = database.fetch.call_args.args
    assert "WHERE list_id = %s" in query and "value LIKE %s ESCAPE '='" in query
    assert "ORDER BY (value = %s) DESC, value ASC, id ASC" in query
    assert "HOSPICIO" not in query
    assert params[1:] == (3, "%HOSPICIO%", "HOSPICIO", 21, 0)
    assert query.count("%s") == len(params)


def test_company_search_treats_wildcards_and_sql_as_literal_parameters(database):
    text = "_%= ' OR 1=1 --"
    assert json.loads(tools.find_companies(text))["ok"] is True
    query, params = database.fetch.call_args.args
    assert text not in query
    assert params[2] == "%=_=%== ' OR 1==1 --%"
    assert params[3] == text


def test_company_catalog_limit_reports_more_without_silently_hiding_matches(database):
    database.fetch.return_value = [
        {"company_id": 218, "name": "HOSPICIO"}, {"company_id": 219, "name": "HOSPICIO SEGUNDA SEDE"},
    ]
    data = json.loads(tools.find_companies("HOSPICIO", limit=1))["data"]
    assert data["has_more"] is True and data["row_count"] == 1
    assert data["rows"] == [{"company_id": 218, "name": "HOSPICIO"}]


def test_empty_search_is_a_successful_empty_result(database):
    result = json.loads(tools.find_companies("NO MATCH"))
    assert result["ok"] is True
    assert result["data"]["rows"] == [] and result["data"]["has_more"] is False


def test_latest_ticket_is_filtered_and_sorted_on_the_database(database):
    database.fetch.return_value = [{"ticket_id": 90001, "number": "ABC123", "subject": "Current ticket"}]
    result = json.loads(tools.list_company_tickets(218, limit=1))
    assert result["ok"] is True and result["meta"]["is_sample"] is False
    assert result["data"]["company"]["name"] == "HOSPICIO"
    assert result["data"]["order"] == "newest_first"
    assert result["data"]["rows"][0]["ticket_id"] == 90001
    lookup, lookup_params = database.one.call_args.args
    assert "WHERE list_id = %s AND id = %s" in lookup
    assert lookup_params[-2:] == (3, 218)
    query, params = database.fetch.call_args.args
    assert "TRIM(SUBSTRING_INDEX(c.listaEmpresa, ',', 1)) = %s" in query
    assert "ORDER BY t.created DESC, t.ticket_id DESC" in query
    assert params[-3:] == ("218", 2, 0)
    assert query.count("%s") == len(params)
    assert "SELECT *" not in query and "passwd" not in query
    assert "LEFT(c.`analisis`, %s)" in query and "LEFT(c.`solucion`, %s)" in query


def test_missing_company_does_not_fall_back_to_unfiltered_tickets(database):
    database.one.return_value = None
    result = json.loads(tools.list_company_tickets(999999))
    assert result["ok"] is False and result["error"]["code"] == "NOT_FOUND"
    database.fetch.assert_not_called()


def test_existing_company_without_tickets_is_a_successful_empty_result(database):
    data = json.loads(tools.list_company_tickets(218))["data"]
    assert data["rows"] == [] and data["has_more"] is False


def test_company_query_does_not_bypass_a_future_column_restriction(database, monkeypatch):
    restricted = dict(access.ALLOWED_TABLE_COLUMNS)
    restricted["ost_staff"] = ("staff_id",)
    monkeypatch.setattr(access, "ALLOWED_TABLE_COLUMNS", restricted)
    result = json.loads(tools.list_company_tickets(218))
    assert result["ok"] is True
    assert "assigned_agent" in result["data"]["unavailable_fields"]
    query = database.fetch.call_args.args[0]
    assert "NULL AS assigned_agent" in query
    assert "a.firstname" not in query and "a.lastname" not in query


@pytest.mark.parametrize("name", ["", " ", "x", "\n\n", "a" * 121, 123, True, None, [], "ab\x00cd"])
def test_invalid_company_searches_fail_before_database_access(database, name):
    result = json.loads(tools.find_companies(name))
    assert result["error"]["code"] == "INVALID_ARGUMENTS"
    database.fetch.assert_not_called()


@pytest.mark.parametrize("identifier", [0, -1, True, "218", 218.0, None, [], 2147483648])
def test_invalid_company_ids_fail_before_database_access(database, identifier):
    result = json.loads(tools.list_company_tickets(identifier))
    assert result["error"]["code"] == "INVALID_ARGUMENTS"
    database.one.assert_not_called()
    database.fetch.assert_not_called()


@pytest.mark.parametrize("limit", [0, 51, "10", 1.5, True, None])
def test_invalid_business_limits_are_rejected(database, limit):
    assert json.loads(tools.find_companies("HOSPICIO", limit))["error"]["code"] == "INVALID_ARGUMENTS"
    assert json.loads(tools.list_company_tickets(218, limit))["error"]["code"] == "INVALID_ARGUMENTS"
    database.one.assert_not_called()
    database.fetch.assert_not_called()


@pytest.mark.parametrize("name, arguments", [
    ("find_companies", {"name": "HOSPICIO", "where": "id > 100"}),
    ("list_company_tickets", {"company_id": 218, "order_by": "created"}),
    ("list_company_tickets", {"company_id": 218, "offset": 10001}),
    ("list_company_tickets", {"company_id": 218, "query": "SELECT * FROM ost_staff"}),
])
def test_new_tools_reject_arbitrary_sql_and_sort_parameters(database, name, arguments):
    result = asyncio.run(mcp.call_tool(name, arguments))
    assert result.isError is True
    assert json.loads(result.content[0].text)["error"]["code"] == "INVALID_ARGUMENTS"
    database.one.assert_not_called()
    database.fetch.assert_not_called()


def test_mcp_can_resolve_company_and_request_latest_ticket(database):
    database.fetch.side_effect = [
        [{"company_id": 218, "name": "HOSPICIO", "status": 1}],
        [{"ticket_id": 90001, "number": "ABC123"}],
    ]
    async def flow():
        found = await mcp.call_tool("find_companies", {"name": "HOSPICIO"})
        company = json.loads(found.content[0].text)["data"]["rows"][0]
        latest = await mcp.call_tool("list_company_tickets", {"company_id": company["company_id"], "limit": 1})
        assert found.isError is False and latest.isError is False
        assert json.loads(latest.content[0].text)["data"]["rows"][0]["ticket_id"] == 90001
    asyncio.run(flow())


def test_size_clipping_marks_more_results_even_if_database_returned_exact_limit():
    rows = [{"subject": "x" * 4000, "ticket_id": i} for i in range(50)]
    result = json.loads(encode_response({"rows": rows, "row_count": 50, "has_more": False}))
    assert result["meta"]["truncated"] is True
    assert result["data"]["has_more"] is True
