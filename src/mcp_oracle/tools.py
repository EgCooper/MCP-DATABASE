"""MCP tools for Oracle operations."""

from __future__ import annotations

import json
import re

from mcp_oracle import db

_READ_ONLY_PATTERN = re.compile(
    r"^\s*(SELECT|WITH)\b",
    re.IGNORECASE | re.DOTALL,
)

_FETCH_LIMIT_PATTERN = re.compile(
    r"\bFETCH\s+(FIRST|NEXT)\s+\d+\s+ROWS?\s+ONLY\b",
    re.IGNORECASE,
)


def list_tables() -> str:
    """List tables visible to the connected Oracle user."""
    rows = db.fetch_all(
        "SELECT table_name FROM user_tables ORDER BY table_name"
    )
    if not rows:
        return "No tables found."

    tables = [row["table_name"] for row in rows]
    return json.dumps({"tables": tables, "count": len(tables)}, indent=2)


def describe_table(table_name: str) -> str:
    """Return column definitions for a table in the current schema."""
    if not re.fullmatch(r"[A-Za-z0-9_$#]+", table_name):
        return json.dumps(
            {
                "error": "Invalid table name. Use letters, numbers, underscore, $ or #."
            }
        )

    rows = db.fetch_all(
        """
        SELECT
            column_name,
            data_type,
            data_length,
            data_precision,
            data_scale,
            nullable,
            data_default
        FROM user_tab_columns
        WHERE table_name = :table_name
        ORDER BY column_id
        """,
        {"table_name": table_name.upper()},
    )
    if not rows:
        return json.dumps(
            {"error": f"Table '{table_name}' not found or has no columns."}
        )

    return json.dumps(
        {"table": table_name.upper(), "columns": rows},
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
    if not _FETCH_LIMIT_PATTERN.search(normalized) and not re.search(
        r"\bROWNUM\b", normalized, re.IGNORECASE
    ):
        normalized = f"{normalized} FETCH FIRST {limit} ROWS ONLY"

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
    """Verify connectivity to Oracle."""
    try:
        row = db.fetch_one(
            """
            SELECT
                1 AS ok,
                USER AS username,
                SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA') AS current_schema,
                SYS_CONTEXT('USERENV', 'DB_NAME') AS db_name
            FROM dual
            """
        )
        return json.dumps(
            {"status": "connected", **(row or {})},
            indent=2,
            default=str,
        )
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})
