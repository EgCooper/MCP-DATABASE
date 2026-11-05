#  Implement tools for MySQL operations (read-only) in the MCP server.
"""MCP tools for MySQL operations (read-only)."""

from __future__ import annotations

import json
import re

from mcp_mysql import db

_TABLE_NAME = re.compile(r"^[A-Za-z0-9_]+$")


def _ok(payload: dict) -> str:
    return json.dumps(payload, indent=2, default=str)


def _err(message: str) -> str:
    return _ok({"error": message})


def _validate_table_name(table_name: str) -> str | None:
    if not _TABLE_NAME.fullmatch(table_name):
        return "Invalid table name. Use only letters, numbers, and underscores."
    return None


def test_connection() -> str:
    """Verify connectivity to MySQL."""
    try:
        row = db.fetch_one(
            "SELECT 1 AS ok, DATABASE() AS `database_name`, VERSION() AS `version`"
        )
        return _ok({"status": "connected", **(row or {})})
    except Exception as exc:
        return _ok({"status": "error", "error": str(exc)})


def list_tables() -> str:
    """List all tables in the configured database."""
    rows = db.fetch_all("SHOW TABLES")
    if not rows:
        return "No tables found."
    key = next(iter(rows[0].keys()))
    tables = [row[key] for row in rows]
    return _ok({"tables": tables, "count": len(tables)})


def describe_table(table_name: str) -> str:
    """Return column definitions for a table."""
    err = _validate_table_name(table_name)
    if err:
        return _err(err)

    rows = db.fetch_all(f"DESCRIBE `{table_name}`")
    if not rows:
        return _err(f"Table '{table_name}' not found or has no columns.")
    return _ok({"table": table_name, "columns": rows})


def sample_rows(table_name: str, limit: int = 10) -> str:
    """Return sample rows from a table (read-only)."""
    err = _validate_table_name(table_name)
    if err:
        return _err(err)
    if limit < 1 or limit > 100:
        return _err("limit must be between 1 and 100.")

    try:
        rows = db.fetch_all(f"SELECT * FROM `{table_name}` LIMIT {int(limit)}")
        return _ok(
            {"table": table_name, "row_count": len(rows), "rows": rows}
        )
    except Exception as exc:
        return _err(str(exc))
