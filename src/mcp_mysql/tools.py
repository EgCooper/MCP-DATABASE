"""MCP tools for MySQL operations."""

import json
import re

from mcp_mysql import db

# Only allow read-oriented statements by default.
_READ_ONLY_PATTERN = re.compile(
    r"^\s*(SELECT|SHOW|DESCRIBE|DESC|EXPLAIN|WITH)\b",
    re.IGNORECASE | re.DOTALL,
)

# tool to list all tables in the configured database
def list_tables() -> str:
    """List all tables in the configured database."""
    rows = db.fetch_all("SHOW TABLES")
    if not rows:
        return "No tables found."

    # SHOW TABLES returns a single dynamic column name.
    key = next(iter(rows[0].keys()))
    tables = [row[key] for row in rows]
    return json.dumps({"tables": tables, "count": len(tables)}, indent=2)

# tool to describe the columns of a MySQL table
def describe_table(table_name: str) -> str:
    """Return column definitions for a table."""
    if not re.fullmatch(r"[A-Za-z0-9_]+", table_name):
        return json.dumps({"error": "Invalid table name. Use only letters, numbers, and underscores."})

    rows = db.fetch_all(f"DESCRIBE `{table_name}`")
    if not rows:
        return json.dumps({"error": f"Table '{table_name}' not found or has no columns."})

    return json.dumps({"table": table_name, "columns": rows}, indent=2, default=str)

# tool to execute a read-only SQL query (SELECT, SHOW, DESCRIBE, EXPLAIN, WITH)
def execute_query(query: str, limit: int = 100) -> str:
    """
    Execute a read-only SQL query and return results as JSON.

    Only SELECT, SHOW, DESCRIBE, DESC, EXPLAIN, and WITH queries are allowed.
    """
    if not _READ_ONLY_PATTERN.match(query):
        return json.dumps(
            {
                "error": "Only read-only queries are allowed "
                "(SELECT, SHOW, DESCRIBE, EXPLAIN, WITH)."
            }
        )

    if limit < 1 or limit > 1000:
        return json.dumps({"error": "limit must be between 1 and 1000."})

    # Soft-cap result size for SELECT without an explicit LIMIT.
    normalized = query.strip().rstrip(";")
    if re.match(r"^\s*(SELECT|WITH)\b", normalized, re.IGNORECASE) and not re.search(
        r"\bLIMIT\s+\d+", normalized, re.IGNORECASE
    ):
        normalized = f"{normalized} LIMIT {limit}"

    try:
        rows = db.fetch_all(normalized)
        return json.dumps(
            {"row_count": len(rows), "rows": rows},
            indent=2,
            default=str,
        )
    except Exception as exc:
        return json.dumps({"error": str(exc)})

# tool to test the MySQL connection
def test_connection() -> str:
    """Verify connectivity to MySQL."""
    try:
        row = db.fetch_one(
            "SELECT 1 AS ok, DATABASE() AS `database_name`, VERSION() AS `version`"
        )
        return json.dumps({"status": "connected", **(row or {})}, indent=2, default=str)
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})
