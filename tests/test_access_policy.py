"""Access boundary regressions. No test opens a real database connection."""

import asyncio
import json
from unittest.mock import Mock

import pytest

from mcp_mysql import db, tools
from mcp_mysql.access import ALLOWED_TABLE_COLUMNS
from mcp_mysql.responses import MAX_FIELD_CHARACTERS
from mcp_mysql.server import mcp


@pytest.fixture(autouse=True)
def no_live_database(monkeypatch):
    connection = Mock(side_effect=AssertionError("Tests must not connect to MySQL"))
    monkeypatch.setattr(db, "get_connection", connection)
    yield
    connection.assert_not_called()


@pytest.fixture
def fetch(monkeypatch):
    fetch = Mock()
    monkeypatch.setattr(db, "fetch_all", fetch)
    return fetch


def column(name):
    return {
        "Field": name, "Type": "int" if name.endswith("_id") else "varchar(128)", "Null": "YES",
        "Key": "", "Default": None, "Extra": "",
    }


SUPPORT_TOOLS = {
    "test_connection", "list_catalog", "find_companies", "list_company_tickets",
    "search_tickets", "count_tickets", "ticket_report", "get_ticket", "get_ticket_thread",
    "find_agents", "get_agent_report", "find_users", "get_user", "search_ticket_content", "read_ticket_text",
}
EXPLORATION = {"list_tables", "describe_table", "sample_rows"}


def test_mcp_exposes_exploration_and_controlled_company_queries():
    registered = asyncio.run(mcp.list_tools())
    assert {tool.name for tool in registered} == SUPPORT_TOOLS | EXPLORATION
    assert all(tool.annotations.readOnlyHint is True for tool in registered)


def test_exploration_tools_are_hidden_and_rejected_unless_enabled(monkeypatch, fetch):
    monkeypatch.delenv("MCP_ENABLE_EXPLORATION_TOOLS")
    registered = asyncio.run(mcp.list_tools())
    assert {tool.name for tool in registered} == SUPPORT_TOOLS
    for name in EXPLORATION:
        result = asyncio.run(mcp.call_tool(name, {"table_name": "ost_ticket"} if name != "list_tables" else {}))
        assert json.loads(result.content[0].text)["error"]["code"] == "UNKNOWN_TOOL"
    fetch.assert_not_called()


@pytest.mark.parametrize("table", ["ost_form_entry", "ost_form_entry_values", "ost_form_field"])
def test_internal_business_tables_are_never_explorable(fetch, table):
    for operation in (tools.describe_table, tools.sample_rows):
        assert json.loads(operation(table))["error"]["code"] == "ACCESS_DENIED"
    # Even if the database reports the table, the listing only keeps exploration tables.
    fetch.return_value = [{"table_name": table}, {"table_name": "ost_ticket"}]
    assert json.loads(tools.list_tables())["data"]["tables"] == ["ost_ticket"]
    assert table not in fetch.call_args.args[1]


def test_list_tables_filters_and_queries_only_authorized_base_tables(fetch):
    fetch.return_value = [
        {"table_name": "ost_ticket"}, {"table_name": "ost_staff"},
        {"table_name": "ost_api_key"}, {"table_name": "ost_new_secret_table"},
    ]
    result = json.loads(tools.list_tables())["data"]
    assert result == {"tables": ["ost_staff", "ost_ticket"], "count": 2}
    query, parameters = fetch.call_args.args
    assert "TABLE_SCHEMA = DATABASE()" in query
    assert "TABLE_TYPE = 'BASE TABLE'" in query
    assert "TABLE_NAME IN (" in query
    assert query.count("%s") == len(parameters)
    assert set(parameters) == set(ALLOWED_TABLE_COLUMNS)


def test_empty_database_returns_json_list(fetch):
    fetch.return_value = []
    assert json.loads(tools.list_tables())["data"] == {"tables": [], "count": 0}


@pytest.mark.parametrize("table", [
    "ost_api_key", "ost_config", "ost_email", "ost_email_account", "ost_session",
    "ost_user_account", "ost_plugin", "ost_plugin_instance", "ost_syslog",
    "ost_draft", "ost_lock", "ost_role", "ost_group", "ost_staff_dept_access",
    "ost__search", "ost_file", "ost_organization", "ost_new_secret_table",
    "other.ost_ticket", "OST_TICKET", " ost_ticket", "ost_ticket ",
    "`ost_ticket`", "ost_ticket; DROP TABLE ost_ticket", "ost_ticket` --",
    "ost_ticket\x00", "", None, [],
])
def test_unauthorized_tables_are_rejected_before_db_access(fetch, table):
    for operation in (tools.describe_table, tools.sample_rows):
        result = json.loads(operation(table))
        assert result["ok"] is False and result["data"] is None
        assert result["error"]["code"] == "ACCESS_DENIED"
    fetch.assert_not_called()


def test_staff_description_excludes_secret_and_new_columns(fetch):
    fetch.return_value = [
        column("staff_id"), column("firstname"), column("passwd"),
        column("permissions"), column("extra"), column("future_auth_token"),
    ]
    result = json.loads(tools.describe_table("ost_staff"))["data"]
    assert [c["Field"] for c in result["columns"]] == ["staff_id", "firstname"]
    query, parameters = fetch.call_args.args
    assert "TABLE_SCHEMA = DATABASE()" in query
    assert "TABLE_NAME = %s" in query
    assert "COLUMN_NAME IN (" in query
    assert parameters[2] == "ost_staff"
    assert query.count("%s") == len(parameters)
    assert not {"passwd", "permissions", "extra", "future_auth_token"} & set(parameters)


def test_staff_sample_selects_only_permitted_existing_columns(fetch):
    fetch.side_effect = [
        [column("staff_id"), column("firstname"), column("passwd")],
        [{"staff_id": 1, "firstname": "Agent", "passwd": "must not escape"}],
    ]
    result = json.loads(tools.sample_rows("ost_staff", 5))["data"]
    assert result == {
        "table": "ost_staff", "row_count": 1,
        "rows": [{"staff_id": 1, "firstname": "Agent"}],
    }
    query, parameters = fetch.call_args.args
    assert query == "SELECT `staff_id`, LEFT(`firstname`, %s) AS `firstname` FROM `ost_staff` LIMIT %s"
    assert parameters == (MAX_FIELD_CHARACTERS + 1, 5)


def test_custom_hours_and_company_survive_partial_schema(fetch):
    fetch.side_effect = [
        [column("ticket_id"), column("listaEmpresa"), column("timeExtra"), column("new_private_field")],
        [{"ticket_id": 12, "listaEmpresa": "3,Company", "timeExtra": "1.5"}],
    ]
    result = json.loads(tools.sample_rows("ost_ticket__cdata"))["data"]
    assert result["rows"] == [{"ticket_id": 12, "listaEmpresa": "3,Company", "timeExtra": "1.5"}]
    query, parameters = fetch.call_args.args
    assert "`listaEmpresa`" in query and "`timeExtra`" in query
    assert "new_private_field" not in query and "timeApoyo3" not in query
    assert parameters == (MAX_FIELD_CHARACTERS + 1, MAX_FIELD_CHARACTERS + 1, 10)


@pytest.mark.parametrize("metadata", [[], [column("passwd"), column("future_auth_token")]])
def test_no_available_columns_never_falls_back_to_select_star(fetch, metadata):
    fetch.return_value = metadata
    assert json.loads(tools.describe_table("ost_staff"))["error"]["code"] == "NO_PERMITTED_COLUMNS"
    assert json.loads(tools.sample_rows("ost_staff"))["error"]["code"] == "NO_PERMITTED_COLUMNS"
    assert fetch.call_count == 2
    assert all("FROM INFORMATION_SCHEMA.COLUMNS" in call.args[0] for call in fetch.call_args_list)


@pytest.mark.parametrize("limit", [0, -1, 101, 10000, "10", "1; DROP TABLE ost_ticket", 1.5, True, None])
def test_invalid_limits_never_access_database(fetch, limit):
    assert json.loads(tools.sample_rows("ost_ticket", limit))["error"]["code"] == "INVALID_ARGUMENTS"
    fetch.assert_not_called()


@pytest.mark.parametrize("limit", [1, 100])
def test_sample_limits_are_bound_parameters(fetch, limit):
    fetch.side_effect = [[column("ticket_id")], [{"ticket_id": i} for i in range(limit + 1)]]
    result = json.loads(tools.sample_rows("ost_ticket", limit))["data"]
    assert result["row_count"] == limit
    assert len(result["rows"]) == limit
    query, parameters = fetch.call_args.args
    assert "SELECT *" not in query
    assert query.endswith("LIMIT %s")
    assert parameters == (limit,)


def test_mcp_direct_call_cannot_bypass_table_policy(fetch):
    result = asyncio.run(mcp.call_tool("sample_rows", {"table_name": "ost_api_key"}))
    assert result.isError is True
    assert "Table is not available through this MCP." in str(result)
    fetch.assert_not_called()


@pytest.mark.parametrize("name", ["execute_query", "count_rows", "list_views"])
def test_removed_mcp_tools_cannot_be_called(fetch, name):
    result = asyncio.run(mcp.call_tool(name, {}))
    assert result.isError is True
    assert json.loads(result.content[0].text)["error"]["code"] == "UNKNOWN_TOOL"
    fetch.assert_not_called()
