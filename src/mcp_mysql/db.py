"""Read-only MySQL sessions with bounded reads and deterministic cleanup."""

import atexit
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from decimal import Decimal
import threading
import time
from typing import Any, Generator

import mysql.connector
from mysql.connector import MySQLConnection
from mysql.connector.constants import ClientFlag
from mysql.connector.cursor import MySQLCursorDict

from mcp_mysql.config import MySQLConfig, db_pool_max_lifetime_seconds, db_pool_size, max_db_connections
from mcp_mysql.errors import ConfigurationError, ResultLimitError

MAX_RESULT_ROWS = 1000
# Waiting longer than this for a free connection slot is reported as a timeout.
CONNECTION_SLOT_TIMEOUT_SECONDS = 30
# Idle pooled connections older than this are dropped instead of reused: network
# devices may silently cut idle TCP sessions long before the server's wait_timeout.
POOL_MAX_IDLE_SECONDS = 300

_slots_lock = threading.Lock()
_slots: threading.BoundedSemaphore | None = None


def _connection_slots() -> threading.BoundedSemaphore:
    global _slots
    with _slots_lock:
        if _slots is None:
            _slots = threading.BoundedSemaphore(max_db_connections())
        return _slots


def _close_connection(
    conn: MySQLConnection,
    cursor: Any = None,
    *,
    rollback: bool = False,
    original_error: BaseException | None = None,
) -> None:
    """Attempt all cleanup steps without replacing the operation's error.

    Connector/Python's rollback drains pending rows. Skip it in that case:
    disconnecting aborts the transaction without reading the remaining data.
    Automatic result consumption is disabled when the connection is created.
    """
    failures: list[BaseException] = []
    if rollback:
        try:
            if not conn.unread_result:
                conn.rollback()
        except BaseException as exc:
            failures.append(exc)
    if cursor is not None:
        try:
            cursor.close()
        except BaseException as exc:
            failures.append(exc)
    try:
        conn.close()
    except BaseException as exc:
        failures.append(exc)

    if failures:
        if original_error is not None:
            # Identify cleanup failures without including driver messages or secrets.
            kinds = ", ".join(type(exc).__name__ for exc in failures)
            original_error.add_note(f"Database cleanup also failed ({kinds}).")
        else:
            raise failures[0]


def get_connection(config: MySQLConfig | None = None) -> MySQLConnection:
    """Return a connection only after all read-only safeguards are enabled."""
    cfg = config or MySQLConfig.from_env()
    if not cfg.database:
        raise ConfigurationError("MYSQL_DATABASE is required")

    conn = mysql.connector.connect(
        **cfg.as_dict(),
        autocommit=False,
        buffered=False,
        consume_results=False,
        # The Python implementation closes unread results without draining them.
        use_pure=True,
        allow_local_infile=False,
        client_flags=[-ClientFlag.MULTI_STATEMENTS, -ClientFlag.LOCAL_FILES],
    )
    setup_cursor = None
    try:
        server_info = getattr(conn, "server_info", None)
        if server_info is None:
            server_info = conn.get_server_info()
        if not isinstance(server_info, str):
            raise ConfigurationError("Cannot determine the database server type")
        is_mariadb = "mariadb" in server_info.lower()
        setup_cursor = conn.cursor()
        setup_cursor.execute("SET SESSION TRANSACTION READ ONLY")
        if is_mariadb:
            setup_cursor.execute(
                "SET SESSION max_statement_time = %s", (Decimal(cfg.query_timeout_ms) / 1000,)
            )
            # MariaDB's 5.5.5 compatibility prefix fails the connector's MySQL version check.
            setup_cursor.execute("START TRANSACTION READ ONLY")
        else:
            setup_cursor.execute(
                "SET SESSION MAX_EXECUTION_TIME = %s", (cfg.query_timeout_ms,)
            )
        setup_cursor.close()
        setup_cursor = None
        if not is_mariadb:
            conn.start_transaction(readonly=True)
    except BaseException as exc:
        _close_connection(conn, setup_cursor, original_error=exc)
        raise
    return conn


def _is_mariadb(conn: MySQLConnection) -> bool:
    server_info = getattr(conn, "server_info", None)
    if server_info is None:
        server_info = conn.get_server_info()
    if not isinstance(server_info, str):
        raise ConfigurationError("Cannot determine the database server type")
    return "mariadb" in server_info.lower()


def _begin_read_only(conn: MySQLConnection, mariadb: bool) -> None:
    """Start a new read-only transaction on a reused, already protected connection."""
    if mariadb:
        cursor = conn.cursor()
        try:
            cursor.execute("START TRANSACTION READ ONLY")
        finally:
            cursor.close()
    else:
        conn.start_transaction(readonly=True)


@dataclass(eq=False)
class _Pooled:
    conn: MySQLConnection
    mariadb: bool
    created: float
    last_used: float


class _ConnectionPool:
    """Idle connections that already carry the session-level read-only protections.

    A connection only returns here after a call that finished without any error,
    with its results consumed and its transaction rolled back. Connections are
    keyed by their full configuration, so different credentials never share one.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._idle: dict[MySQLConfig, list[_Pooled]] = {}

    def take(self, config: MySQLConfig) -> _Pooled | None:
        with self._lock:
            idle = self._idle.get(config)
            return idle.pop() if idle else None

    def has_room(self, config: MySQLConfig, limit: int) -> bool:
        with self._lock:
            return len(self._idle.get(config, ())) < limit

    def put(self, config: MySQLConfig, item: _Pooled, limit: int) -> bool:
        with self._lock:
            idle = self._idle.setdefault(config, [])
            if len(idle) >= limit:
                return False
            idle.append(item)
            return True

    def idle_count(self, config: MySQLConfig) -> int:
        with self._lock:
            return len(self._idle.get(config, ()))

    def clear(self) -> None:
        with self._lock:
            items = [item for idle in self._idle.values() for item in idle]
            self._idle.clear()
        for item in items:
            _discard(item)


def _discard(item: _Pooled) -> None:
    try:
        item.conn.close()
    except Exception:
        pass


_pool = _ConnectionPool()
atexit.register(_pool.clear)


def clear_pool() -> None:
    """Close every idle pooled connection (tests, shutdown, configuration changes)."""
    _pool.clear()


def _checkout(config: MySQLConfig) -> _Pooled:
    """Reuse a recent pooled connection or open a new, fully protected one."""
    if db_pool_size():
        while (item := _pool.take(config)) is not None:
            now = time.monotonic()
            if (now - item.created >= db_pool_max_lifetime_seconds()
                    or now - item.last_used >= POOL_MAX_IDLE_SECONDS):
                _discard(item)
                continue
            try:
                # Also the health check: a dead connection fails here and is replaced.
                _begin_read_only(item.conn, item.mariadb)
            except Exception:
                _discard(item)
                continue
            return item
    conn = get_connection(config)
    try:
        mariadb = _is_mariadb(conn)
    except BaseException as exc:
        _close_connection(conn, original_error=exc)
        raise
    now = time.monotonic()
    return _Pooled(conn, mariadb, now, now)


def _checkin(config: MySQLConfig, item: _Pooled, cursor: Any) -> bool:
    """Pool the connection after a successful call. False means the caller must close it."""
    limit = db_pool_size()
    if (not limit or time.monotonic() - item.created >= db_pool_max_lifetime_seconds()
            or item.conn.unread_result or not _pool.has_room(config, limit)):
        return False
    try:
        if cursor is not None:
            cursor.close()
        # End the snapshot: the next call must see current data in a fresh transaction.
        item.conn.rollback()
    except Exception:
        return False
    item.last_used = time.monotonic()
    return _pool.put(config, item, limit)


@contextmanager
def db_cursor(
    config: MySQLConfig | None = None,
) -> Generator[MySQLCursorDict, None, None]:
    """Yield an unbuffered cursor in a read-only transaction; never commit."""
    cfg = config or MySQLConfig.from_env()
    item = _checkout(cfg)
    conn = item.conn
    cursor = None
    original_error = None
    try:
        cursor = conn.cursor(dictionary=True, buffered=False)
        yield cursor
        if conn.unread_result:
            raise RuntimeError("Query results must be fully consumed.")
    except BaseException as exc:
        original_error = exc
        raise
    finally:
        # Any failure, unread result or full pool closes the connection instead of reusing it.
        if original_error is not None or not _checkin(cfg, item, cursor):
            _close_connection(conn, cursor, rollback=True, original_error=original_error)


class _Session:
    """One lazily opened connection shared by the queries of one tool call."""

    def __init__(self, config: MySQLConfig | None, stack: ExitStack) -> None:
        self._config = config
        self._stack = stack
        self._cursor: MySQLCursorDict | None = None

    def cursor(self) -> MySQLCursorDict:
        if self._cursor is None:
            slots = _connection_slots()
            if not slots.acquire(timeout=CONNECTION_SLOT_TIMEOUT_SECONDS):
                raise TimeoutError("No database connection slot available.")
            self._stack.callback(slots.release)
            self._cursor = self._stack.enter_context(db_cursor(self._config))
        return self._cursor


_active_session: ContextVar[_Session | None] = ContextVar("mcp_mysql_session", default=None)


@contextmanager
def session(config: MySQLConfig | None = None) -> Generator[None, None, None]:
    """Run every fetch inside the block on one read-only connection and transaction.

    The connection opens on the first query, so blocks that fail validation or
    are served from cache never connect. Nested blocks reuse the outer session.
    """
    if _active_session.get() is not None:
        yield
        return
    with ExitStack() as stack:
        token = _active_session.set(_Session(config, stack))
        try:
            yield
        finally:
            _active_session.reset(token)


def fetch_all(
    query: str,
    params: tuple | dict | None = None,
    *,
    max_rows: int = MAX_RESULT_ROWS,
) -> list[dict[str, Any]]:
    """Return a bounded result or raise instead of silently truncating it."""
    if type(max_rows) is not int or not 1 <= max_rows <= MAX_RESULT_ROWS:
        raise ValueError(f"max_rows must be between 1 and {MAX_RESULT_ROWS}.")
    active = _active_session.get()
    if active is None:
        with session():
            return fetch_all(query, params, max_rows=max_rows)
    cursor = active.cursor()
    cursor.execute(query, params if params is not None else ())
    rows = cursor.fetchmany(max_rows + 1)
    if len(rows) > max_rows:
        raise ResultLimitError(f"Query exceeds the maximum of {max_rows} rows.")
    return list(rows)


def fetch_one(query: str, params: tuple | dict | None = None) -> dict[str, Any] | None:
    """Return zero or one row; reject results containing more than one row."""
    rows = fetch_all(query, params, max_rows=1)
    return rows[0] if rows else None
