"""Access boundary regressions. No test opens a real database connection."""

import asyncio
import json
from unittest.mock import Mock

import pytest

from mcp_mysql import db, tools
from mcp_mysql.access import ALLOWED_TABLE_COLUMNS
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
        "Field": name, "Type": "varchar(128)", "Null": "YES",
        "Key": "", "Default": None, "Extra": "",
    }


def test_mcp_exposes_only_four_tools():
    registered = asyncio.run(mcp.list_tools())
    assert {tool.name for tool in registered} == {
        "test_connection", "list_tables", "describe_table", "sample_rows",
    }


def test_list_tables_filters_and_queries_only_authorized_base_tables(fetch):
    fetch.return_value = [
        {"table_name": "ost_ticket"}, {"table_name": "ost_staff"},
        {"table_name": "ost_api_key"}, {"table_name": "ost_new_secret_table"},
    ]
    result = json.loads(tools.list_tables())
    assert result == {"tables": ["ost_staff", "ost_ticket"], "count": 2}
    query, parameters = fetch.call_args.args
    assert "TABLE_SCHEMA = DATABASE()" in query
    assert "TABLE_TYPE = 'BASE TABLE'" in query
    assert "TABLE_NAME IN (" in query
    assert query.count("%s") == len(parameters)
    assert set(parameters) == set(ALLOWED_TABLE_COLUMNS)


def test_empty_database_returns_json_list(fetch):
    fetch.return_value = []
    assert json.loads(tools.list_tables()) == {"tables": [], "count": 0}


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
        assert result == {"error": "Table is not available through this MCP."}
    fetch.assert_not_called()


def test_staff_description_excludes_secret_and_new_columns(fetch):
    fetch.return_value = [
        column("staff_id"), column("firstname"), column("passwd"),
        column("permissions"), column("extra"), column("future_auth_token"),
    ]
    result = json.loads(tools.describe_table("ost_staff"))
    assert [c["Field"] for c in result["columns"]] == ["staff_id", "firstname"]
    query, parameters = fetch.call_args.args
    assert "TABLE_SCHEMA = DATABASE()" in query
    assert "TABLE_NAME = %s" in query
    assert "COLUMN_NAME IN (" in query
    assert parameters[0] == "ost_staff"
    assert query.count("%s") == len(parameters)
    assert not {"passwd", "permissions", "extra", "future_auth_token"} & set(parameters)


def test_staff_sample_selects_only_permitted_existing_columns(fetch):
    fetch.side_effect = [
        [column("staff_id"), column("firstname"), column("passwd")],
        [{"staff_id": 1, "firstname": "Agent", "passwd": "must not escape"}],
    ]
    result = json.loads(tools.sample_rows("ost_staff", 5))
    assert result == {
        "table": "ost_staff", "row_count": 1,
        "rows": [{"staff_id": 1, "firstname": "Agent"}],
    }
    query, parameters = fetch.call_args.args
    assert query == "SELECT `staff_id`, `firstname` FROM `ost_staff` LIMIT %s"
    assert parameters == (5,)


def test_custom_hours_and_company_survive_partial_schema(fetch):
    fetch.side_effect = [
        [column("ticket_id"), column("listaEmpresa"), column("timeExtra"), column("new_private_field")],
        [{"ticket_id": 12, "listaEmpresa": "3,Company", "timeExtra": "1.5"}],
    ]
    result = json.loads(tools.sample_rows("ost_ticket__cdata"))
    assert result["rows"] == [{"ticket_id": 12, "listaEmpresa": "3,Company", "timeExtra": "1.5"}]
    query, parameters = fetch.call_args.args
    assert "`listaEmpresa`" in query and "`timeExtra`" in query
    assert "new_private_field" not in query and "timeApoyo3" not in query
    assert parameters == (10,)


@pytest.mark.parametrize("metadata", [[], [column("passwd"), column("future_auth_token")]])
def test_no_available_columns_never_falls_back_to_select_star(fetch, metadata):
    fetch.return_value = metadata
    assert "error" in json.loads(tools.describe_table("ost_staff"))
    assert "error" in json.loads(tools.sample_rows("ost_staff"))
    assert fetch.call_count == 2
    assert all("FROM INFORMATION_SCHEMA.COLUMNS" in call.args[0] for call in fetch.call_args_list)


@pytest.mark.parametrize("limit", [0, -1, 101, 10000, "10", "1; DROP TABLE ost_ticket", 1.5, True, None])
def test_invalid_limits_never_access_database(fetch, limit):
    assert "error" in json.loads(tools.sample_rows("ost_ticket", limit))
    fetch.assert_not_called()


@pytest.mark.parametrize("limit", [1, 100])
def test_sample_limits_are_bound_parameters(fetch, limit):
    fetch.side_effect = [[column("ticket_id")], [{"ticket_id": i} for i in range(limit + 1)]]
    result = json.loads(tools.sample_rows("ost_ticket", limit))
    assert result["row_count"] == limit
    assert len(result["rows"]) == limit
    query, parameters = fetch.call_args.args
    assert "SELECT *" not in query
    assert query.endswith("LIMIT %s")
    assert parameters == (limit,)


def test_mcp_direct_call_cannot_bypass_table_policy(fetch):
    result = asyncio.run(mcp.call_tool("sample_rows", {"table_name": "ost_api_key"}))
    assert "Table is not available through this MCP." in str(result)
    fetch.assert_not_called()


@pytest.mark.parametrize("name", ["execute_query", "count_rows", "list_views"])
def test_removed_mcp_tools_cannot_be_called(fetch, name):
    with pytest.raises(Exception, match="Unknown tool"):
        asyncio.run(mcp.call_tool(name, {}))
    fetch.assert_not_called()
