"""MCP tools for SQL Server operations."""

from __future__ import annotations

import json
import re

from mcp_sqlserver import db

_READ_ONLY_PATTERN = re.compile(
    r"^\s*(SELECT|WITH)\b",
    re.IGNORECASE | re.DOTALL,
)

_HAS_ROW_LIMIT = re.compile(
    r"\bTOP\s+\d+\b|\bFETCH\s+(FIRST|NEXT)\s+\d+\s+ROWS?\s+ONLY\b|\bOFFSET\s+\d+\s+ROWS\b",
    re.IGNORECASE,
)


def list_tables() -> str:
    """List base tables in the current database."""
    rows = db.fetch_all(
        """
        SELECT TABLE_SCHEMA AS table_schema, TABLE_NAME AS table_name
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_TYPE = 'BASE TABLE'
        ORDER BY TABLE_SCHEMA, TABLE_NAME
        """
    )
    if not rows:
        return "No tables found."

    tables = [
        f"{row['table_schema']}.{row['table_name']}"
        if row.get("table_schema")
        else row["table_name"]
        for row in rows
    ]
    return json.dumps({"tables": tables, "count": len(tables)}, indent=2)


def describe_table(table_name: str) -> str:
    """Return column definitions for a table (schema.table or table)."""
    if not re.fullmatch(r"[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)?", table_name):
        return json.dumps(
            {
                "error": "Invalid table name. Use Table or Schema.Table "
                "(letters, numbers, underscore)."
            }
        )

    if "." in table_name:
        schema, name = table_name.split(".", 1)
    else:
        schema, name = "dbo", table_name

    rows = db.fetch_all(
        """
        SELECT
            COLUMN_NAME AS column_name,
            DATA_TYPE AS data_type,
            CHARACTER_MAXIMUM_LENGTH AS max_length,
            NUMERIC_PRECISION AS numeric_precision,
            NUMERIC_SCALE AS numeric_scale,
            IS_NULLABLE AS is_nullable,
            COLUMN_DEFAULT AS column_default
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
        ORDER BY ORDINAL_POSITION
        """,
        (schema, name),
    )
    if not rows:
        return json.dumps(
            {
                "error": f"Table '{schema}.{name}' not found or has no columns."
            }
        )

    return json.dumps(
        {"table": f"{schema}.{name}", "columns": rows},
        indent=2,
        default=str,
    )


def execute_query(query: str, limit: int = 100) -> str:
    """
    Execute a read-only SQL query and return results as JSON.

    Only SELECT and WITH queries are allowed.
    """
    if not _READ_ONLY_PATTERN.match(query):
        return json.dumps(
            {"error": "Only read-only queries are allowed (SELECT, WITH)."}
        )

    if limit < 1 or limit > 1000:
        return json.dumps({"error": "limit must be between 1 and 1000."})

    normalized = query.strip().rstrip(";")
    if re.match(r"^\s*SELECT\b", normalized, re.IGNORECASE) and not _HAS_ROW_LIMIT.search(
        normalized
    ):
        normalized = re.sub(
            r"(?is)^(\s*SELECT\s+)(DISTINCT\s+)?",
            rf"\1\2TOP {limit} ",
            normalized,
            count=1,
        )

    try:
        rows = db.fetch_all(normalized)
        return json.dumps(
            {"row_count": len(rows), "rows": rows},
            indent=2,
            default=str,
        )
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def test_connection() -> str:
    """Verify connectivity to SQL Server."""
    try:
        row = db.fetch_one(
            """
            SELECT
                1 AS ok,
                DB_NAME() AS database_name,
                SUSER_SNAME() AS login_name,
                @@VERSION AS version
            """
        )
        payload = dict(row or {})
        # Truncate long @@VERSION for readability
        version = payload.get("version")
        if isinstance(version, str) and len(version) > 200:
            payload["version"] = version.split("\n")[0].strip()
        return json.dumps(
            {"status": "connected", **payload},
            indent=2,
            default=str,
        )
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})
