"""MCP tools for Informix operations."""

from __future__ import annotations

import json
import re

from mcp_informix import db

_READ_ONLY_PATTERN = re.compile(
    r"^\s*(SELECT|WITH)\b",
    re.IGNORECASE | re.DOTALL,
)

_HAS_ROW_LIMIT = re.compile(
    r"\bFIRST\s+\d+\b|\bLIMIT\s+\d+\b|\bSKIP\s+\d+\b",
    re.IGNORECASE,
)


def list_tables() -> str:
    """List user tables in the current Informix database."""
    rows = db.fetch_all(
        """
        SELECT tabname AS table_name, owner AS table_owner
        FROM systables
        WHERE tabtype = 'T' AND tabid >= 100
        ORDER BY tabname
        """
    )
    if not rows:
        return "No tables found."

    tables = [
        f"{row['table_owner']}.{row['table_name']}".strip()
        if row.get("table_owner")
        else row["table_name"]
        for row in rows
    ]
    return json.dumps({"tables": tables, "count": len(tables)}, indent=2)


def describe_table(table_name: str) -> str:
    """Return column definitions for a table (owner.table or table)."""
    if not re.fullmatch(r"[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)?", table_name):
        return json.dumps(
            {
                "error": "Invalid table name. Use Table or Owner.Table "
                "(letters, numbers, underscore)."
            }
        )

    if "." in table_name:
        owner, name = table_name.split(".", 1)
        rows = db.fetch_all(
            """
            SELECT
                c.colname AS column_name,
                c.coltype AS coltype,
                c.collength AS collength
            FROM systables t, syscolumns c
            WHERE t.tabid = c.tabid
              AND t.tabname = ?
              AND t.owner = ?
            ORDER BY c.colno
            """,
            (name, owner),
        )
        display = f"{owner}.{name}"
    else:
        rows = db.fetch_all(
            """
            SELECT
                c.colname AS column_name,
                c.coltype AS coltype,
                c.collength AS collength
            FROM systables t, syscolumns c
            WHERE t.tabid = c.tabid
              AND t.tabname = ?
              AND t.tabtype = 'T'
            ORDER BY c.colno
            """,
            (table_name,),
        )
        display = table_name

    if not rows:
        return json.dumps(
            {"error": f"Table '{display}' not found or has no columns."}
        )

    return json.dumps(
        {"table": display, "columns": rows},
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
            rf"\1\2FIRST {limit} ",
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
    """Verify connectivity to Informix."""
    try:
        row = db.fetch_one(
            """
            SELECT FIRST 1
                1 AS ok,
                DBINFO('dbname') AS database_name,
                USER AS username,
                DBINFO('version', 'full') AS version
            FROM systables
            WHERE tabid = 1
            """
        )
        return json.dumps(
            {"status": "connected", **(row or {})},
            indent=2,
            default=str,
        )
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})
