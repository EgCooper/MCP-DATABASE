"""PostgreSQL connection helpers (psycopg3)."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Generator

import psycopg
from psycopg.rows import dict_row

from mcp_postgresql.config import PostgreSQLConfig


def get_connection(config: PostgreSQLConfig | None = None) -> psycopg.Connection:
    """Open a new PostgreSQL connection."""
    cfg = config or PostgreSQLConfig.from_env()
    return psycopg.connect(cfg.conninfo, row_factory=dict_row)


@contextmanager
def db_cursor(
    config: PostgreSQLConfig | None = None,
) -> Generator[psycopg.Cursor, None, None]:
    """Yield a dict cursor and close the connection when done."""
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


def fetch_all(query: str, params: tuple | dict | None = None) -> list[dict[str, Any]]:
    """Execute a query and return all rows as dictionaries."""
    with db_cursor() as cursor:
        cursor.execute(query, params or ())
        rows = cursor.fetchall()
        return [dict(row) for row in rows] if rows else []


def fetch_one(query: str, params: tuple | dict | None = None) -> dict[str, Any] | None:
    """Execute a query and return a single row."""
    with db_cursor() as cursor:
        cursor.execute(query, params or ())
        row = cursor.fetchone()
        return dict(row) if row else None
