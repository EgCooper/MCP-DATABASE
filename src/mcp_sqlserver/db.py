"""SQL Server connection helpers (pyodbc)."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Generator

import pyodbc

from mcp_sqlserver.config import SQLServerConfig

# function to get a new SQL Server connection
def get_connection(config: SQLServerConfig | None = None) -> pyodbc.Connection:
    """Open a new SQL Server connection."""
    cfg = config or SQLServerConfig.from_env()
    return pyodbc.connect(cfg.connection_string)

# function to convert SQL Server cursor to a list of dictionaries
def _rows_as_dicts(cursor: pyodbc.Cursor) -> list[dict[str, Any]]:
    if cursor.description is None:
        return []
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]

# function to yield a cursor and close the connection when done
@contextmanager
def db_cursor(
    config: SQLServerConfig | None = None,
) -> Generator[pyodbc.Cursor, None, None]:
    """Yield a cursor and close the connection when done."""
    conn = get_connection(config)
    cursor = conn.cursor()
    try:
        yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()

# function to execute a query and return all rows as dictionaries
def fetch_all(query: str, params: tuple | list | None = None) -> list[dict[str, Any]]:
    """Execute a query and return all rows as dictionaries."""
    with db_cursor() as cursor:
        cursor.execute(query, params or [])
        return _rows_as_dicts(cursor)

# function to execute a query and return a single row
def fetch_one(query: str, params: tuple | list | None = None) -> dict[str, Any] | None:
    """Execute a query and return a single row."""
    rows = fetch_all(query, params)
    return rows[0] if rows else None
