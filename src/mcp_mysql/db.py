"""Read-only MySQL sessions with bounded reads and deterministic cleanup."""

from contextlib import contextmanager
from decimal import Decimal
from typing import Any, Generator

import mysql.connector
from mysql.connector import MySQLConnection
from mysql.connector.constants import ClientFlag
from mysql.connector.cursor import MySQLCursorDict

from mcp_mysql.config import MySQLConfig
from mcp_mysql.errors import ConfigurationError, ResultLimitError

MAX_RESULT_ROWS = 1000


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


@contextmanager
def db_cursor(
    config: MySQLConfig | None = None,
) -> Generator[MySQLCursorDict, None, None]:
    """Yield an unbuffered cursor in a read-only transaction; never commit."""
    conn = get_connection(config)
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
        _close_connection(conn, cursor, rollback=True, original_error=original_error)


def fetch_all(
    query: str,
    params: tuple | dict | None = None,
    *,
    max_rows: int = MAX_RESULT_ROWS,
) -> list[dict[str, Any]]:
    """Return a bounded result or raise instead of silently truncating it."""
    if type(max_rows) is not int or not 1 <= max_rows <= MAX_RESULT_ROWS:
        raise ValueError(f"max_rows must be between 1 and {MAX_RESULT_ROWS}.")
    with db_cursor() as cursor:
        cursor.execute(query, params if params is not None else ())
        rows = cursor.fetchmany(max_rows + 1)
        if len(rows) > max_rows:
            raise ResultLimitError(f"Query exceeds the maximum of {max_rows} rows.")
        return list(rows)


def fetch_one(query: str, params: tuple | dict | None = None) -> dict[str, Any] | None:
    """Return zero or one row; reject results containing more than one row."""
    rows = fetch_all(query, params, max_rows=1)
    return rows[0] if rows else None
