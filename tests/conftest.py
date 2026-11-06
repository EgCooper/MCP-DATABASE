"""Isolate every test from the developer's .env and from cached schema and pool state."""

import pytest

from mcp_mysql import db, tickets


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    # .env is loaded at import time; override it so tests never depend on real credentials.
    for name, value in {
        "MYSQL_HOST": "example.invalid", "MYSQL_PORT": "3306", "MYSQL_USER": "readonly",
        "MYSQL_PASSWORD": "dummy", "MYSQL_DATABASE": "test", "OSTICKET_COMPANY_LIST_ID": "3",
        "MCP_ENABLE_EXPLORATION_TOOLS": "true",
        # One connection per call unless a test enables the pool explicitly.
        "MCP_DB_POOL_SIZE": "0",
    }.items():
        monkeypatch.setenv(name, value)
    for name in ("MYSQL_SSL_CA", "MYSQL_SSL_VERIFY_IDENTITY", "MCP_SCHEMA_CACHE_SECONDS", "MCP_AUTH_TOKEN",
                 "MCP_ALLOWED_HOSTS", "MCP_DB_POOL_MAX_LIFETIME_SECONDS", "MYSQL_CONNECT_TIMEOUT",
                 "MYSQL_READ_TIMEOUT", "MYSQL_WRITE_TIMEOUT", "MYSQL_QUERY_TIMEOUT_MS"):
        monkeypatch.delenv(name, raising=False)
    tickets.clear_schema_cache()
    db.clear_pool()
    yield
    tickets.clear_schema_cache()
    db.clear_pool()
