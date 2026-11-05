"""Public response contracts and error secrecy at Python and MCP boundaries."""

import asyncio
import json
import logging
import re
from unittest.mock import Mock

import pytest
from mcp.types import CallToolRequest, CallToolRequestParams
from mysql.connector.errors import (
    ConnectionTimeoutError, DatabaseError, InterfaceError, ReadTimeoutError, WriteTimeoutError,
)

from mcp_mysql import db, tools
from mcp_mysql.errors import ConfigurationError, ErrorCode, ResultLimitError
from mcp_mysql.responses import MAX_RESPONSE_BYTES, encode_response, error_response
from mcp_mysql.server import mcp

SECRET = "mysql://private_user:private_password@private_host/private_database SELECT secret /private/path"


@pytest.fixture(autouse=True)
def no_live_database(monkeypatch):
    connect = Mock(side_effect=AssertionError("Tests must not connect to MySQL"))
    monkeypatch.setattr(db, "get_connection", connect)
    yield
    connect.assert_not_called()


def contract(encoded, *, ok):
    assert len(encoded.encode("utf-8")) <= MAX_RESPONSE_BYTES
    payload = json.loads(encoded)
    assert set(payload) == {"ok", "data", "error", "meta"}
    assert payload["ok"] is ok
    assert set(payload["meta"]) == {"request_id", "is_sample", "truncated", "truncation"}
    assert re.fullmatch(r"[0-9a-f]{32}", payload["meta"]["request_id"])
    assert type(payload["meta"]["is_sample"]) is bool
    assert type(payload["meta"]["truncated"]) is bool
    if ok:
        assert isinstance(payload["data"], dict) and payload["error"] is None
    else:
        assert payload["data"] is None
        assert set(payload["error"]) == {"code", "message", "retryable"}
        assert type(payload["error"]["retryable"]) is bool
    return payload


def protocol_call(name, arguments):
    request = CallToolRequest(params=CallToolRequestParams(name=name, arguments=arguments))
    return asyncio.run(mcp._mcp_server.request_handlers[CallToolRequest](request)).root


@pytest.mark.parametrize("name, arguments", [
    ("test_connection", {}), ("list_tables", {}),
    ("describe_table", {"table_name": "ost_ticket"}),
    ("sample_rows", {"table_name": "ost_ticket"}),
])
def test_four_tools_share_success_contract_and_mark_samples(monkeypatch, name, arguments):
    monkeypatch.setattr(db, "fetch_one", Mock(return_value={"ok": 1, "database_name": "test", "version": "8.0"}))
    fetch = Mock()
    if name == "list_tables":
        fetch.return_value = [{"table_name": "ost_ticket"}]
    elif name == "describe_table":
        fetch.return_value = [{"Field": "ticket_id", "Type": "int"}]
    else:
        fetch.side_effect = [[{"Field": "ticket_id", "Type": "int"}], [{"ticket_id": 1}]]
    monkeypatch.setattr(db, "fetch_all", fetch)
    direct = contract(getattr(tools, name)(**arguments), ok=True)
    assert direct["meta"]["is_sample"] is (name == "sample_rows")
    if name == "sample_rows":
        fetch.side_effect = [[{"Field": "ticket_id", "Type": "int"}], [{"ticket_id": 1}]]
    result = protocol_call(name, arguments)
    assert result.isError is False and result.structuredContent is None
    assert len(result.content) == 1
    wire = contract(result.content[0].text, ok=True)
    assert wire["data"] == direct["data"]


@pytest.mark.parametrize("failure, code, retryable", [
    (DatabaseError(SECRET, errno=1045), "DATABASE_AUTHENTICATION_FAILED", False),
    (DatabaseError(SECRET, errno=1698), "DATABASE_AUTHENTICATION_FAILED", False),
    (DatabaseError(SECRET, errno=1044), "DATABASE_PERMISSION_DENIED", False),
    (DatabaseError(SECRET, errno=1142), "DATABASE_PERMISSION_DENIED", False),
    (DatabaseError(SECRET, errno=1143), "DATABASE_PERMISSION_DENIED", False),
    (DatabaseError(SECRET, errno=1227), "DATABASE_PERMISSION_DENIED", False),
    (DatabaseError(SECRET, errno=1792), "DATABASE_PERMISSION_DENIED", False),
    (InterfaceError(SECRET, errno=2002), "DATABASE_UNAVAILABLE", True),
    (InterfaceError(SECRET, errno=2003), "DATABASE_UNAVAILABLE", True),
    (DatabaseError(SECRET, errno=2006), "DATABASE_UNAVAILABLE", True),
    (DatabaseError(SECRET, errno=2013), "DATABASE_UNAVAILABLE", True),
    (DatabaseError(SECRET, errno=2055), "DATABASE_UNAVAILABLE", True),
    (DatabaseError(SECRET, errno=3024), "QUERY_TIMEOUT", True),
    (DatabaseError(SECRET, errno=1969), "QUERY_TIMEOUT", True),
    (DatabaseError(SECRET, errno=1317), "QUERY_TIMEOUT", True),
    (DatabaseError(SECRET, errno=1193), "DATABASE_PROTECTION_UNAVAILABLE", False),
    (DatabaseError(SECRET, errno=1235), "DATABASE_PROTECTION_UNAVAILABLE", False),
    (DatabaseError(SECRET, errno=1064), "DATABASE_QUERY_FAILED", False),
    (ConnectionTimeoutError(SECRET), "DATABASE_TIMEOUT", True),
    (ReadTimeoutError(SECRET), "DATABASE_TIMEOUT", True),
    (WriteTimeoutError(SECRET), "DATABASE_TIMEOUT", True),
    (TimeoutError(SECRET), "DATABASE_TIMEOUT", True),
    (ConnectionRefusedError(SECRET), "DATABASE_UNAVAILABLE", True),
    (ConfigurationError(SECRET), "CONFIGURATION_ERROR", False),
    (ResultLimitError(SECRET), "RESULT_LIMIT_EXCEEDED", False),
    (RuntimeError(SECRET), "INTERNAL_ERROR", False),
    (ValueError(SECRET), "INTERNAL_ERROR", False),
])
def test_errors_are_classified_without_exposing_messages_or_causes(monkeypatch, caplog, failure, code, retryable):
    failure.add_note(SECRET)
    failure.__cause__ = RuntimeError(SECRET)
    monkeypatch.setattr(db, "fetch_all", Mock(side_effect=failure))
    with caplog.at_level(logging.WARNING):
        result = protocol_call("list_tables", {})
    assert result.isError is True
    payload = contract(result.content[0].text, ok=False)
    assert payload["error"]["code"] == code
    assert payload["error"]["retryable"] is retryable
    assert payload["meta"]["request_id"] in caplog.text
    assert code in caplog.text
    for marker in ("private_user", "private_password", "private_host", "private_database", "SELECT secret", "/private/path"):
        assert marker not in result.model_dump_json()
        assert marker not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.parametrize("name, arguments", [
    ("test_connection", {}), ("list_tables", {}),
    ("describe_table", {"table_name": "ost_staff"}),
    ("sample_rows", {"table_name": "ost_ticket"}),
])
def test_all_tool_error_paths_use_the_same_safe_contract(monkeypatch, name, arguments):
    monkeypatch.setattr(db, "fetch_all", Mock(side_effect=RuntimeError(SECRET)))
    monkeypatch.setattr(db, "fetch_one", Mock(side_effect=RuntimeError(SECRET)))
    payload = contract(getattr(tools, name)(**arguments), ok=False)
    assert payload["error"]["code"] == "INTERNAL_ERROR"
    assert SECRET not in json.dumps(payload)


@pytest.mark.parametrize("name, arguments, expected", [
    ("list_tables", {"password": SECRET}, "INVALID_ARGUMENTS"),
    ("sample_rows", {"table_name": "ost_ticket", "limit": True}, "INVALID_ARGUMENTS"),
    ("describe_table", {"table_name": "ost_ticket", "query": SECRET}, "INVALID_ARGUMENTS"),
    ("describe_table", {"table_name": "ost_api_key"}, "ACCESS_DENIED"),
    ("sample_rows", {"table_name": "ost_session"}, "ACCESS_DENIED"),
    ("removed_tool", {}, "UNKNOWN_TOOL"),
])
def test_validation_policy_and_unknown_tools_return_json_errors(monkeypatch, caplog, name, arguments, expected):
    fetch = Mock()
    monkeypatch.setattr(db, "fetch_all", fetch)
    result = protocol_call(name, arguments)
    assert result.isError is True and len(result.content) == 1
    payload = contract(result.content[0].text, ok=False)
    assert payload["error"]["code"] == expected
    assert SECRET not in result.model_dump_json() and SECRET not in caplog.text
    fetch.assert_not_called()


def test_unexpected_wrapper_failure_never_reaches_sdk_logging(monkeypatch, caplog):
    monkeypatch.setattr(tools, "list_tables", Mock(side_effect=RuntimeError(SECRET)))
    result = protocol_call("list_tables", {})
    payload = contract(result.content[0].text, ok=False)
    assert result.isError is True and payload["error"]["code"] == "INTERNAL_ERROR"
    assert SECRET not in result.model_dump_json() and SECRET not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_unexpected_exception_is_never_stringified(monkeypatch):
    class UnprintableError(Exception):
        def __str__(self):
            pytest.fail("The raw exception must not be formatted")

    monkeypatch.setattr(db, "fetch_all", Mock(side_effect=UnprintableError()))
    assert contract(tools.list_tables(), ok=False)["error"]["code"] == "INTERNAL_ERROR"


@pytest.mark.parametrize("bad_response", [SECRET, json.dumps({
    "ok": False, "data": None,
    "error": {"code": "INTERNAL_ERROR", "message": SECRET, "retryable": False},
    "meta": {},
})])
def test_invalid_handler_results_are_replaced_without_leaking_content(monkeypatch, caplog, bad_response):
    monkeypatch.setattr(tools, "list_tables", Mock(return_value=bad_response))
    result = protocol_call("list_tables", {})
    assert result.isError is True
    assert contract(result.content[0].text, ok=False)["error"]["code"] == "INTERNAL_ERROR"
    assert SECRET not in result.model_dump_json() and SECRET not in caplog.text


def test_output_overflow_uses_the_same_error_envelope():
    # Oversized keys cannot be shortened without changing the meaning of the response.
    encoded = encode_response({"x" * MAX_RESPONSE_BYTES: "value"})
    payload = contract(encoded, ok=False)
    assert payload["error"]["code"] == "OUTPUT_LIMIT_EXCEEDED"
    assert payload["meta"]["truncated"] is True


def test_each_response_has_an_independent_reference():
    first = contract(error_response(ErrorCode.INTERNAL_ERROR), ok=False)
    second = contract(error_response(ErrorCode.INTERNAL_ERROR), ok=False)
    assert first["meta"]["request_id"] != second["meta"]["request_id"]
