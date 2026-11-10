"""Isolate every test from the developer's .env and from cached schema and pool state."""

import os
from uuid import uuid4

import mysql.connector
import pytest

from mcp_mysql import db, tickets
from mcp_mysql.config import MySQLConfig
from mysql_fixture import TABLES, _seed, _grant_policy_columns


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


# Shared SQL fixtures: only explicit disposable loopback servers, never .env.

@pytest.fixture(scope="module")
def isolated_database():
    port = int(os.environ["MCP_TEST_MYSQL_PORT"])
    token = uuid4().hex[:12]
    schema, reader = f"mcp_query_test_{token}", f"reader_{token}"
    account = f"'{reader}'@'%'"
    admin = mysql.connector.connect(host="127.0.0.1", port=port, user="root", password="", use_pure=True)
    cursor = admin.cursor()
    try:
        cursor.execute(f"CREATE DATABASE `{schema}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        cursor.execute(f"USE `{schema}`")
        for table, columns in TABLES.items():
            cursor.execute(f"CREATE TABLE `{table}` ({columns})")
        _seed(cursor)
        admin.commit()
        cursor.execute(f"CREATE USER {account} IDENTIFIED BY 'test-only'")
        _grant_policy_columns(cursor, schema, account)
        ca = os.environ.get("MCP_TEST_MYSQL_CA")
        yield MySQLConfig(host="127.0.0.1", port=port, user=reader, password="test-only", database=schema,
                          ssl_ca=ca, ssl_verify_identity=bool(ca))
    finally:
        cursor.execute(f"DROP DATABASE IF EXISTS `{schema}`")
        cursor.execute(f"DROP USER IF EXISTS {account}")
        cursor.close()
        admin.close()


@pytest.fixture
def live(isolated_database, monkeypatch):
    monkeypatch.setattr(MySQLConfig, "from_env", lambda: isolated_database)
    tickets.clear_schema_cache()
