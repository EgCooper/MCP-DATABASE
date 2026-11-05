"""Validate the real MCP entry point and bound content with a simulated DB."""

import asyncio
from datetime import datetime
from decimal import Decimal
import json
from unittest.mock import Mock

import pytest
from mcp.types import CallToolRequest, CallToolRequestParams

from mcp_mysql import db, tools
from mcp_mysql.responses import MAX_FIELD_CHARACTERS, MAX_RESPONSE_BYTES, encode_response
from mcp_mysql.server import mcp


@pytest.fixture(autouse=True)
def no_live_database(monkeypatch):
    connect = Mock(side_effect=AssertionError("Tests must not connect to MySQL"))
    monkeypatch.setattr(db, "get_connection", connect)
    yield
    connect.assert_not_called()


@pytest.fixture
def fetch(monkeypatch):
    mocked = Mock()
    monkeypatch.setattr(db, "fetch_all", mocked)
    return mocked


def invalid_arguments(tool, arguments):
    result = asyncio.run(mcp.call_tool(tool, arguments))
    assert result.isError is True
    assert json.loads(result.content[0].text)["error"]["code"] == "INVALID_ARGUMENTS"
    return result.content[0].text


@pytest.mark.parametrize("limit", ["10", 10.0, 1.5, True, False, None, -1, 0, 101, [], {}])
def test_mcp_rejects_bad_limits_before_querying(fetch, limit):
    invalid_arguments("sample_rows", {"table_name": "ost_ticket", "limit": limit})
    fetch.assert_not_called()


@pytest.mark.parametrize("name", ["", "a" * 65, "a" * 100000, 123, True, None, [], {}, "ost_ticket\x00", "other.ost_ticket"])
@pytest.mark.parametrize("tool", ["describe_table", "sample_rows"])
def test_mcp_rejects_malformed_or_oversized_names(fetch, tool, name):
    invalid_arguments(tool, {"table_name": name})
    fetch.assert_not_called()


@pytest.mark.parametrize("tool, arguments", [
    ("test_connection", {"sql": "SELECT 1"}),
    ("list_tables", {"database": "other"}),
    ("describe_table", {"table_name": "ost_ticket", "columns": ["passwd"]}),
    ("sample_rows", {"table_name": "ost_ticket", "query": "SELECT 1"}),
    ("describe_table", {}),
    ("sample_rows", {}),
])
def test_mcp_rejects_unknown_and_missing_arguments(fetch, tool, arguments):
    invalid_arguments(tool, arguments)
    fetch.assert_not_called()


def test_validation_errors_do_not_echo_input_values(fetch):
    secret = "private-value-" * 10000
    encoded = invalid_arguments("list_tables", {"password": secret})
    assert secret not in encoded
    assert len(encoded) < 1000
    fetch.assert_not_called()


def test_published_schemas_match_strict_runtime_contract():
    definitions = asyncio.run(mcp.list_tools())
    assert all(tool.outputSchema is None for tool in definitions)
    schemas = {t.name: t.inputSchema for t in definitions}
    assert len(schemas) == 12
    assert all(schema["additionalProperties"] is False for schema in schemas.values())
    table = schemas["sample_rows"]["properties"]["table_name"]
    assert table["type"] == "string" and table["minLength"] == 1 and table["maxLength"] == 64
    limit = schemas["sample_rows"]["properties"]["limit"]
    assert limit["type"] == "integer" and limit["minimum"] == 1 and limit["maximum"] == 100
    assert len(schemas["get_ticket"]["oneOf"]) == 2


@pytest.mark.parametrize("limit", [1, 100])
def test_mcp_accepts_integer_boundaries(fetch, limit):
    fetch.side_effect = [[{"Field": "ticket_id", "Type": "int"}], [{"ticket_id": 1}]]
    asyncio.run(mcp.call_tool("sample_rows", {"table_name": "ost_ticket", "limit": limit}))
    assert fetch.call_count == 2
    assert fetch.call_args.args[1] == (limit,)


def test_sql_bounds_large_text_and_binary_fields_before_transfer(fetch):
    fetch.side_effect = [
        [
            {"Field": "id", "Type": "int(11) unsigned"},
            {"Field": "body", "Type": "longtext"},
            {"Field": "title", "Type": "varbinary(4096)"},
            {"Field": "created", "Type": "datetime"},
        ],
        [{"id": 1, "body": "a" * (MAX_FIELD_CHARACTERS + 1), "title": b"example"}],
    ]
    result = json.loads(tools.sample_rows("ost_thread_entry"))
    query, params = fetch.call_args.args
    assert "LEFT(`body`, %s) AS `body`" in query
    assert "LEFT(`title`, %s) AS `title`" in query
    assert "LEFT(`id`" not in query and "LEFT(`created`" not in query
    assert params == (MAX_FIELD_CHARACTERS + 1, MAX_FIELD_CHARACTERS + 1, 10)
    assert len(result["data"]["rows"][0]["body"]) == MAX_FIELD_CHARACTERS
    assert result["meta"]["truncated"] is True
    assert "data.rows[0].body" in result["meta"]["truncation"]["field_paths"]


def test_metadata_large_type_and_default_are_bounded_in_sql(fetch):
    fetch.return_value = [{"Field": "subject", "Type": "varchar(128)"}]
    tools.describe_table("ost_ticket__cdata")
    query, params = fetch.call_args.args
    assert "LEFT(COLUMN_TYPE, %s)" in query and "LEFT(COLUMN_DEFAULT, %s)" in query
    assert params[:2] == (MAX_FIELD_CHARACTERS + 1, MAX_FIELD_CHARACTERS + 1)


def test_small_results_preserve_data_inside_the_common_envelope():
    payload = {"table": "ost_ticket", "row_count": 1, "rows": [{"ticket_id": 1, "subject": "hello"}]}
    result = json.loads(encode_response(payload))
    assert result["data"] == payload
    assert result["ok"] is True and result["error"] is None
    assert result["meta"]["truncated"] is False and result["meta"]["truncation"] is None


@pytest.mark.parametrize("text", ["é", "😀", "\x00", '"\\\n'])
def test_unicode_and_escaping_are_included_in_the_response_budget(text):
    rows = [{"id": i, "body": text * MAX_FIELD_CHARACTERS} for i in range(100)]
    encoded = encode_response({"table": "ost_thread_entry", "row_count": 100, "rows": rows})
    assert len(encoded.encode("utf-8")) <= MAX_RESPONSE_BYTES
    result = json.loads(encoded)
    assert result["meta"]["truncated"] is True
    data = result["data"]
    assert data["row_count"] == len(data["rows"]) >= 1
    assert result["meta"]["truncation"]["omitted_rows"] == 100 - data["row_count"]
    assert result["meta"]["truncation"]["response_limited"] is True
    assert [row["id"] for row in data["rows"]] == list(range(data["row_count"]))


def test_single_oversized_row_gets_a_smaller_cell_budget_without_losing_identifiers():
    row = {f"field_{i}": "😀" * MAX_FIELD_CHARACTERS for i in range(22)}
    row["ticket_id"] = 42
    encoded = encode_response({"table": "ost_ticket__cdata", "row_count": 1, "rows": [row]})
    result = json.loads(encoded)
    assert len(encoded.encode("utf-8")) <= MAX_RESPONSE_BYTES
    assert result["data"]["table"] == "ost_ticket__cdata"
    assert result["data"]["rows"][0]["ticket_id"] == 42
    assert result["data"]["row_count"] == 1
    assert result["meta"]["truncated"] is True
    assert result["meta"]["truncation"]["response_limited"] is True
    assert len(result["data"]["rows"][0]["field_0"]) < MAX_FIELD_CHARACTERS


def test_truncation_details_stay_bounded_and_refer_only_to_returned_rows():
    rows = [{f"field_{i}": "x" * 10000 for i in range(10)} for _ in range(100)]
    result = json.loads(encode_response({"row_count": 100, "rows": rows}))
    details = result["meta"]["truncation"]
    assert len(details["field_paths"]) <= 32
    assert details["field_count"] == result["data"]["row_count"] * 10
    for path in details["field_paths"]:
        assert int(path.split("[", 1)[1].split("]", 1)[0]) < result["data"]["row_count"]


def test_normalization_handles_mysql_values_and_binary_without_invalid_json():
    payload = {"rows": [{
        "date": datetime(2026, 11, 5, 12, 30), "hours": Decimal("1.5"),
        "binary": b"x" * 100000, "null": None, "finite": 1.5, "not_finite": float("inf"),
    }], "row_count": 1}
    result = json.loads(encode_response(payload))
    row = result["data"]["rows"][0]
    assert row["date"] == "2026-11-05 12:30:00" and row["hours"] == "1.5"
    assert row["null"] is None and row["finite"] == 1.5
    assert row["not_finite"] == "inf"
    assert len(row["binary"]) <= MAX_FIELD_CHARACTERS
    assert "data.rows[0].binary" in result["meta"]["truncation"]["field_paths"]


def test_large_driver_errors_are_replaced_instead_of_clipped(fetch):
    fetch.side_effect = RuntimeError("x" * 100000)
    encoded = tools.list_tables()
    result = json.loads(encoded)
    assert len(encoded.encode("utf-8")) <= MAX_RESPONSE_BYTES
    assert result["error"]["code"] == "INTERNAL_ERROR"
    assert "x" * 100 not in encoded
    assert result["meta"]["truncated"] is False


def test_truncated_metadata_is_explicit_and_valid_json(fetch):
    fetch.return_value = [{"Field": "subject", "Type": "enum(" + "x" * 10000 + ")"}]
    result = json.loads(tools.describe_table("ost_ticket__cdata"))
    assert result["meta"]["truncated"] is True
    assert result["meta"]["truncation"]["field_paths"] == ["data.columns[0].Type"]


def test_mcp_protocol_handler_returns_one_bounded_json_content_block(fetch):
    fetch.side_effect = [
        [{"Field": "id", "Type": "int"}, {"Field": "body", "Type": "longtext"}],
        [{"id": i, "body": "😀" * (MAX_FIELD_CHARACTERS + 1)} for i in range(100)],
    ]
    request = CallToolRequest(params=CallToolRequestParams(
        name="sample_rows", arguments={"table_name": "ost_thread_entry", "limit": 100},
    ))
    result = asyncio.run(mcp._mcp_server.request_handlers[CallToolRequest](request)).root
    assert result.isError is False
    assert result.structuredContent is None
    assert len(result.content) == 1
    assert len(result.content[0].text.encode("utf-8")) <= MAX_RESPONSE_BYTES
    content = json.loads(result.content[0].text)
    assert content["meta"]["truncated"] is True
    assert content["data"]["row_count"] == len(content["data"]["rows"])


def test_mcp_protocol_handler_rejects_unknown_arguments_before_db(fetch):
    request = CallToolRequest(params=CallToolRequestParams(
        name="sample_rows", arguments={"table_name": "ost_ticket", "database": "other"},
    ))
    result = asyncio.run(mcp._mcp_server.request_handlers[CallToolRequest](request)).root
    assert result.isError is True
    assert "Invalid arguments" in result.content[0].text
    fetch.assert_not_called()
