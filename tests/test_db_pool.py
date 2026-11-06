"""Connection reuse keeps every read-only guarantee and never reuses a doubtful connection."""

from types import SimpleNamespace

import pytest
from mysql.connector.errors import DatabaseError, OperationalError

from mcp_mysql import db
from mcp_mysql.config import MySQLConfig, db_pool_size


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, params=()):
        if sql.startswith("START TRANSACTION") and self.conn.dead:
            raise OperationalError("server gone")
        if "boom" in sql:
            raise DatabaseError("query failed")
        self.conn.statements.append(sql)
        self.conn.last_query = sql

    def fetchmany(self, size):
        if "many" in self.conn.last_query:
            self.conn.unread_result = True
            return [{"id": i} for i in range(size)]
        return [{"id": self.conn.number}]

    def close(self):
        pass


class FakeConnection:
    def __init__(self, number, server_info):
        self.number = number
        self.server_info = server_info
        self.unread_result = False
        self.statements: list[str] = []
        self.last_query = ""
        self.rollbacks = 0
        self.closed = False
        self.dead = False

    def cursor(self, dictionary=False, buffered=None):
        return FakeCursor(self)

    def start_transaction(self, readonly=False):
        if self.dead:
            raise OperationalError("server gone")
        self.statements.append(f"start_transaction(readonly={readonly})")

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


@pytest.fixture
def server(monkeypatch):
    state = SimpleNamespace(connections=[], server_info="10.3.39-MariaDB")

    def connect(**options):
        conn = FakeConnection(len(state.connections) + 1, state.server_info)
        state.connections.append(conn)
        return conn

    monkeypatch.setattr(db.mysql.connector, "connect", connect)
    monkeypatch.setenv("MCP_DB_POOL_SIZE", "2")
    clock = SimpleNamespace(now=1000.0)
    monkeypatch.setattr(db.time, "monotonic", lambda: clock.now)
    state.clock = clock
    return state


def query(sql="SELECT id"):
    return db.fetch_all(sql)


def test_sequential_calls_reuse_one_protected_connection(server):
    assert query() == [{"id": 1}]
    assert query() == [{"id": 1}]
    assert len(server.connections) == 1
    conn = server.connections[0]
    # Session protections once per physical connection; a fresh read-only transaction per call.
    assert conn.statements.count("SET SESSION TRANSACTION READ ONLY") == 1
    assert conn.statements.count("START TRANSACTION READ ONLY") == 2
    assert conn.rollbacks == 2 and conn.closed is False
    assert db._pool.idle_count(MySQLConfig.from_env()) == 1


def test_mysql_servers_restart_the_transaction_with_the_connector_api(server):
    server.server_info = "8.0.36"
    query()
    query()
    conn = server.connections[0]
    assert conn.statements.count("start_transaction(readonly=True)") == 2


def test_a_connection_that_failed_is_never_reused(server):
    query()
    with pytest.raises(DatabaseError):
        query("SELECT boom")
    assert server.connections[0].closed is True
    query()
    assert len(server.connections) == 2


def test_unread_results_close_the_connection_instead_of_pooling_it(server):
    with pytest.raises(db.ResultLimitError):
        db.fetch_all("SELECT many", max_rows=2)
    assert server.connections[0].closed is True
    assert server.connections[0].rollbacks == 0  # never drain pending rows
    assert db._pool.idle_count(MySQLConfig.from_env()) == 0


def test_a_dead_pooled_connection_is_replaced_transparently(server):
    query()
    server.connections[0].dead = True
    assert query() == [{"id": 2}]
    assert server.connections[0].closed is True
    assert len(server.connections) == 2


def test_long_idle_connections_are_dropped_without_being_used(server):
    query()
    server.clock.now += db.POOL_MAX_IDLE_SECONDS
    query()
    first = server.connections[0]
    assert first.closed is True
    assert first.statements.count("START TRANSACTION READ ONLY") == 1
    assert len(server.connections) == 2


def test_connections_are_renewed_after_their_maximum_lifetime(server, monkeypatch):
    monkeypatch.setenv("MCP_DB_POOL_MAX_LIFETIME_SECONDS", "60")
    query()
    for _ in range(3):
        server.clock.now += 25
        query()
    assert len(server.connections) == 2
    assert server.connections[0].closed is True


def test_the_pool_never_keeps_more_than_its_size(server, monkeypatch):
    monkeypatch.setenv("MCP_DB_POOL_SIZE", "1")
    config = MySQLConfig.from_env()
    with db.db_cursor(config) as first, db.db_cursor(config) as second:
        first.execute("SELECT 1")
        first.fetchmany(2)
        second.execute("SELECT 1")
        second.fetchmany(2)
    assert db._pool.idle_count(config) == 1
    assert sum(conn.closed for conn in server.connections) == 1


def test_different_credentials_never_share_connections(server, monkeypatch):
    query()
    monkeypatch.setenv("MYSQL_USER", "other_reader")
    query()
    assert len(server.connections) == 2
    assert server.connections[0].closed is False


def test_disabled_pool_closes_every_connection(server, monkeypatch):
    monkeypatch.setenv("MCP_DB_POOL_SIZE", "0")
    query()
    query()
    assert len(server.connections) == 2
    assert all(conn.closed for conn in server.connections)


def test_clear_pool_closes_idle_connections(server):
    query()
    db.clear_pool()
    assert server.connections[0].closed is True
    assert db._pool.idle_count(MySQLConfig.from_env()) == 0


@pytest.mark.parametrize("value, expected", [("0", 0), ("3", 3), ("50", 8)])
def test_pool_size_is_bounded_by_the_connection_limit(monkeypatch, value, expected):
    monkeypatch.setenv("MCP_DB_POOL_SIZE", value)
    assert db_pool_size() == expected


@pytest.mark.parametrize("value", ["-1", "abc", "1.5"])
def test_invalid_pool_sizes_are_rejected(monkeypatch, value):
    monkeypatch.setenv("MCP_DB_POOL_SIZE", value)
    with pytest.raises(ValueError, match="MCP_DB_POOL_SIZE"):
        db_pool_size()
