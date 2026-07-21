"""MCP tools for MySQL operations (read-only)."""

from __future__ import annotations

import json
import re

from mcp_mysql import db

_READ_ONLY_START = re.compile(
    r"^\s*(SELECT|SHOW|DESCRIBE|DESC|EXPLAIN|WITH)\b",
    re.IGNORECASE | re.DOTALL,
)
_FORBIDDEN_SQL = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|REPLACE|GRANT|REVOKE|"
    r"CALL|EXEC|EXECUTE|MERGE|LOAD|INTO\s+OUTFILE|INTO\s+DUMPFILE)\b",
    re.IGNORECASE,
)
_TABLE_NAME = re.compile(r"^[A-Za-z0-9_]+$")
_COLUMN_PATTERN = re.compile(r"^[A-Za-z0-9_%]+$")


def _ok(payload: dict) -> str:
    return json.dumps(payload, indent=2, default=str)


def _err(message: str) -> str:
    return _ok({"error": message})


def _validate_table_name(table_name: str) -> str | None:
    if not _TABLE_NAME.fullmatch(table_name):
        return "Invalid table name. Use only letters, numbers, and underscores."
    return None


def _validate_read_only_query(query: str) -> str | None:
    stripped = query.strip()
    if not stripped:
        return "Query is empty."
    if ";" in stripped.rstrip(";"):
        return "Multiple statements are not allowed. Remove extra semicolons."
    if not _READ_ONLY_START.match(stripped):
        return (
            "Only read-only queries are allowed "
            "(SELECT, SHOW, DESCRIBE, EXPLAIN, WITH)."
        )
    if _FORBIDDEN_SQL.search(stripped):
        return "Query contains forbidden write/admin keywords."
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


def list_views() -> str:
    """List views in the current database."""
    rows = db.fetch_all(
        """
        SELECT TABLE_NAME AS view_name
        FROM INFORMATION_SCHEMA.VIEWS
        WHERE TABLE_SCHEMA = DATABASE()
        ORDER BY TABLE_NAME
        """
    )
    views = [row["view_name"] for row in rows]
    return _ok({"views": views, "count": len(views)})


def describe_table(table_name: str) -> str:
    """Return column definitions for a table."""
    err = _validate_table_name(table_name)
    if err:
        return _err(err)

    rows = db.fetch_all(f"DESCRIBE `{table_name}`")
    if not rows:
        return _err(f"Table '{table_name}' not found or has no columns.")
    return _ok({"table": table_name, "columns": rows})


def list_indexes(table_name: str) -> str:
    """List indexes for a table."""
    err = _validate_table_name(table_name)
    if err:
        return _err(err)

    rows = db.fetch_all(f"SHOW INDEX FROM `{table_name}`")
    return _ok({"table": table_name, "indexes": rows, "count": len(rows)})


def list_foreign_keys(table_name: str = "") -> str:
    """List foreign keys for one table, or all in the current database."""
    if table_name:
        err = _validate_table_name(table_name)
        if err:
            return _err(err)
        rows = db.fetch_all(
            """
            SELECT
                CONSTRAINT_NAME AS constraint_name,
                TABLE_NAME AS table_name,
                COLUMN_NAME AS column_name,
                REFERENCED_TABLE_NAME AS referenced_table,
                REFERENCED_COLUMN_NAME AS referenced_column
            FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = %s
              AND REFERENCED_TABLE_NAME IS NOT NULL
            ORDER BY CONSTRAINT_NAME, ORDINAL_POSITION
            """,
            (table_name,),
        )
    else:
        rows = db.fetch_all(
            """
            SELECT
                CONSTRAINT_NAME AS constraint_name,
                TABLE_NAME AS table_name,
                COLUMN_NAME AS column_name,
                REFERENCED_TABLE_NAME AS referenced_table,
                REFERENCED_COLUMN_NAME AS referenced_column
            FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA = DATABASE()
              AND REFERENCED_TABLE_NAME IS NOT NULL
            ORDER BY TABLE_NAME, CONSTRAINT_NAME, ORDINAL_POSITION
            """
        )
    return _ok(
        {
            "table": table_name or None,
            "foreign_keys": rows,
            "count": len(rows),
        }
    )


def find_column(column_name: str) -> str:
    """Find tables that contain a column (supports % wildcards)."""
    if not _COLUMN_PATTERN.fullmatch(column_name):
        return _err(
            "Invalid column pattern. Use letters, numbers, underscore, and %."
        )

    rows = db.fetch_all(
        """
        SELECT TABLE_NAME AS table_name, COLUMN_NAME AS column_name,
               DATA_TYPE AS data_type, IS_NULLABLE AS is_nullable
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND COLUMN_NAME LIKE %s
        ORDER BY TABLE_NAME, ORDINAL_POSITION
        """,
        (column_name,),
    )
    return _ok({"pattern": column_name, "matches": rows, "count": len(rows)})


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


def count_rows(table_name: str) -> str:
    """Count rows in a table."""
    err = _validate_table_name(table_name)
    if err:
        return _err(err)

    try:
        row = db.fetch_one(f"SELECT COUNT(*) AS row_count FROM `{table_name}`")
        return _ok({"table": table_name, **(row or {})})
    except Exception as exc:
        return _err(str(exc))


def execute_query(query: str, limit: int = 100) -> str:
    """
    Execute a read-only SQL query and return results as JSON.

    Only SELECT, SHOW, DESCRIBE, DESC, EXPLAIN, and WITH queries are allowed.
    """
    err = _validate_read_only_query(query)
    if err:
        return _err(err)
    if limit < 1 or limit > 1000:
        return _err("limit must be between 1 and 1000.")

    normalized = query.strip().rstrip(";")
    if re.match(r"^\s*(SELECT|WITH)\b", normalized, re.IGNORECASE) and not re.search(
        r"\bLIMIT\s+\d+", normalized, re.IGNORECASE
    ):
        normalized = f"{normalized} LIMIT {limit}"

    try:
        rows = db.fetch_all(normalized)
        return _ok({"row_count": len(rows), "rows": rows})
    except Exception as exc:
        return _err(str(exc))
