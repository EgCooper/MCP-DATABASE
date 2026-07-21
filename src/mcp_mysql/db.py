"""MySQL connection helpers."""

from contextlib import contextmanager
from typing import Any, Generator

import mysql.connector
from mysql.connector import MySQLConnection
from mysql.connector.cursor import MySQLCursorDict

from mcp_mysql.config import MySQLConfig

# function to get a new MySQL connection
def get_connection(config: MySQLConfig | None = None) -> MySQLConnection:
    """Open a new MySQL connection."""
    cfg = config or MySQLConfig.from_env()
    if not cfg.database:
        raise ValueError("MYSQL_DATABASE is required")

    return mysql.connector.connect(**cfg.as_dict())

# function to yield a dict cursor and close the connection when done
@contextmanager
def db_cursor(
    config: MySQLConfig | None = None,
) -> Generator[MySQLCursorDict, None, None]:
    """Yield a dict cursor and close the connection when done."""
    conn = get_connection(config)
    cursor = conn.cursor(dictionary=True)
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
def fetch_all(query: str, params: tuple | dict | None = None) -> list[dict[str, Any]]:
    """Execute a query and return all rows as dictionaries."""
    with db_cursor() as cursor:
        cursor.execute(query, params or ())
        rows = cursor.fetchall()
        return list(rows) if rows else []

# function to execute a query and return a single row
def fetch_one(query: str, params: tuple | dict | None = None) -> dict[str, Any] | None:
    """Execute a query and return a single row."""
    with db_cursor() as cursor:
        cursor.execute(query, params or ())
        return cursor.fetchone()
