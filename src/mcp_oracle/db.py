"""Oracle connection helpers."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Generator

import oracledb

from mcp_oracle.config import OracleConfig


def get_connection(config: OracleConfig | None = None) -> oracledb.Connection:
    """Open a new Oracle connection (thin mode by default)."""
    cfg = config or OracleConfig.from_env()
    if not cfg.user:
        raise ValueError("ORACLE_USER is required")
    return oracledb.connect(**cfg.as_connect_kwargs())


def _rows_as_dicts(cursor: oracledb.Cursor) -> list[dict[str, Any]]:
    if cursor.description is None:
        return []
    columns = [col[0].lower() for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


@contextmanager
def db_cursor(
    config: OracleConfig | None = None,
) -> Generator[oracledb.Cursor, None, None]:
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


def fetch_all(query: str, params: dict | tuple | None = None) -> list[dict[str, Any]]:
    """Execute a query and return all rows as dictionaries."""
    with db_cursor() as cursor:
        cursor.execute(query, params or {})
        return _rows_as_dicts(cursor)


def fetch_one(query: str, params: dict | tuple | None = None) -> dict[str, Any] | None:
    """Execute a query and return a single row."""
    rows = fetch_all(query, params)
    return rows[0] if rows else None
