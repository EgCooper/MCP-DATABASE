#  Implement tools for MySQL operations (read-only) in the MCP server.
"""MCP tools for MySQL operations (read-only)."""

from __future__ import annotations

import json

from mcp_mysql import db
from mcp_mysql.access import ALLOWED_TABLE_COLUMNS, get_allowed_columns


def _ok(payload: dict) -> str:
    return json.dumps(payload, indent=2, default=str)


def _err(message: str) -> str:
    return _ok({"error": message})


def _describe_allowed_columns(table_name: str) -> list[dict]:
    """Return only approved columns that exist in the configured database."""
    allowed = get_allowed_columns(table_name)
    placeholders = ", ".join("%s" for _ in allowed)
    rows = db.fetch_all(
        f"""
        SELECT COLUMN_NAME AS `Field`, COLUMN_TYPE AS `Type`,
               IS_NULLABLE AS `Null`, COLUMN_KEY AS `Key`,
               COLUMN_DEFAULT AS `Default`, EXTRA AS `Extra`
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND COLUMN_NAME IN ({placeholders})
        ORDER BY ORDINAL_POSITION
        """,
        (table_name, *allowed),
    )
    return [row for row in rows if row.get("Field") in allowed]


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
    """List existing base tables explicitly allowed by the access policy."""
    allowed = tuple(sorted(ALLOWED_TABLE_COLUMNS))
    placeholders = ", ".join("%s" for _ in allowed)
    try:
        rows = db.fetch_all(
            f"""
            SELECT TABLE_NAME AS table_name
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_TYPE = 'BASE TABLE'
              AND TABLE_NAME IN ({placeholders})
            ORDER BY TABLE_NAME
            """,
            allowed,
        )
        tables = sorted({row["table_name"] for row in rows if row.get("table_name") in allowed})
        return _ok({"tables": tables, "count": len(tables)})
    except Exception as exc:
        return _err(str(exc))


def describe_table(table_name: str) -> str:
    """Return only permitted column definitions of an authorized table."""
    try:
        rows = _describe_allowed_columns(table_name)
        if not rows:
            return _err("No permitted columns are available for this table.")
        return _ok({"table": table_name, "columns": rows})
    except Exception as exc:
        return _err(str(exc))


def sample_rows(table_name: str, limit: int = 10) -> str:
    """Sample only approved, existing columns of an authorized table."""
    if type(limit) is not int or limit < 1 or limit > 100:
        return _err("limit must be between 1 and 100.")

    try:
        metadata = _describe_allowed_columns(table_name)
        if not metadata:
            return _err("No permitted columns are available for this table.")
        columns = [row["Field"] for row in metadata]
        projection = ", ".join(f"`{column}`" for column in columns)
        rows = db.fetch_all(
            f"SELECT {projection} FROM `{table_name}` LIMIT %s", (limit,)
        )
        safe_rows = [
            {column: row[column] for column in columns if column in row}
            for row in rows[:limit]
        ]
        return _ok(
            {"table": table_name, "row_count": len(safe_rows), "rows": safe_rows}
        )
    except Exception as exc:
        return _err(str(exc))
