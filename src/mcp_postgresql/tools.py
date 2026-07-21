"""MCP tools for PostgreSQL operations (read-only)."""

from __future__ import annotations

import json
import re

from mcp_postgresql import db

_READ_ONLY_START = re.compile(
    r"^\s*(SELECT|WITH|SHOW|EXPLAIN)\b",
    re.IGNORECASE | re.DOTALL,
)
_FORBIDDEN_SQL = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|REPLACE|GRANT|REVOKE|"
    r"CALL|EXECUTE|MERGE|COPY|VACUUM|REINDEX|CLUSTER|LISTEN|NOTIFY)\b",
    re.IGNORECASE,
)
_TABLE_NAME = re.compile(r"^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)?$")
_COLUMN_PATTERN = re.compile(r"^[A-Za-z0-9_%]+$")
_IDENT = re.compile(r"^[A-Za-z0-9_]+$")


def _ok(payload: dict) -> str:
    return json.dumps(payload, indent=2, default=str)


def _err(message: str) -> str:
    return _ok({"error": message})


def _split_table(table_name: str) -> tuple[str, str] | str:
    if not _TABLE_NAME.fullmatch(table_name):
        return (
            "Invalid table name. Use Table or Schema.Table "
            "(letters, numbers, underscore)."
        )
    if "." in table_name:
        schema, name = table_name.split(".", 1)
    else:
        schema, name = "public", table_name
    return schema, name


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _validate_read_only_query(query: str) -> str | None:
    stripped = query.strip()
    if not stripped:
        return "Query is empty."
    if ";" in stripped.rstrip(";"):
        return "Multiple statements are not allowed. Remove extra semicolons."
    if not _READ_ONLY_START.match(stripped):
        return "Only read-only queries are allowed (SELECT, WITH, SHOW, EXPLAIN)."
    if _FORBIDDEN_SQL.search(stripped):
        return "Query contains forbidden write/admin keywords."
    return None


def test_connection() -> str:
    """Verify connectivity to PostgreSQL."""
    try:
        row = db.fetch_one(
            """
            SELECT
                1 AS ok,
                current_database() AS database_name,
                current_user AS username,
                version() AS version
            """
        )
        payload = dict(row or {})
        version = payload.get("version")
        if isinstance(version, str) and len(version) > 200:
            payload["version"] = version.split(",")[0].strip()
        return _ok({"status": "connected", **payload})
    except Exception as exc:
        return _ok({"status": "error", "error": str(exc)})


def list_tables() -> str:
    """List base tables in the current database (non-system schemas)."""
    rows = db.fetch_all(
        """
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_type = 'BASE TABLE'
          AND table_schema NOT IN ('pg_catalog', 'information_schema')
        ORDER BY table_schema, table_name
        """
    )
    if not rows:
        return "No tables found."
    tables = [f"{row['table_schema']}.{row['table_name']}" for row in rows]
    return _ok({"tables": tables, "count": len(tables)})


def list_views() -> str:
    """List views in the current database (non-system schemas)."""
    rows = db.fetch_all(
        """
        SELECT table_schema AS view_schema, table_name AS view_name
        FROM information_schema.views
        WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
        ORDER BY table_schema, table_name
        """
    )
    views = [f"{row['view_schema']}.{row['view_name']}" for row in rows]
    return _ok({"views": views, "count": len(views)})


def describe_table(table_name: str) -> str:
    """Return column definitions for a table (schema.table or table)."""
    parsed = _split_table(table_name)
    if isinstance(parsed, str):
        return _err(parsed)
    schema, name = parsed

    rows = db.fetch_all(
        """
        SELECT
            column_name,
            data_type,
            character_maximum_length AS max_length,
            numeric_precision,
            numeric_scale,
            is_nullable,
            column_default
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
        """,
        (schema, name),
    )
    if not rows:
        return _err(f"Table '{schema}.{name}' not found or has no columns.")
    return _ok({"table": f"{schema}.{name}", "columns": rows})


def list_indexes(table_name: str) -> str:
    """List indexes for a table."""
    parsed = _split_table(table_name)
    if isinstance(parsed, str):
        return _err(parsed)
    schema, name = parsed

    rows = db.fetch_all(
        """
        SELECT
            schemaname AS table_schema,
            tablename AS table_name,
            indexname AS index_name,
            indexdef AS index_definition
        FROM pg_indexes
        WHERE schemaname = %s AND tablename = %s
        ORDER BY indexname
        """,
        (schema, name),
    )
    return _ok(
        {"table": f"{schema}.{name}", "indexes": rows, "count": len(rows)}
    )


def list_foreign_keys(table_name: str = "") -> str:
    """List foreign keys for one table, or all in non-system schemas."""
    if table_name:
        parsed = _split_table(table_name)
        if isinstance(parsed, str):
            return _err(parsed)
        schema, name = parsed
        rows = db.fetch_all(
            """
            SELECT
                tc.constraint_name,
                tc.table_schema,
                tc.table_name,
                kcu.column_name,
                ccu.table_schema AS referenced_schema,
                ccu.table_name AS referenced_table,
                ccu.column_name AS referenced_column
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage AS ccu
              ON ccu.constraint_name = tc.constraint_name
             AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = %s
              AND tc.table_name = %s
            ORDER BY tc.constraint_name, kcu.ordinal_position
            """,
            (schema, name),
        )
        display = f"{schema}.{name}"
    else:
        rows = db.fetch_all(
            """
            SELECT
                tc.constraint_name,
                tc.table_schema,
                tc.table_name,
                kcu.column_name,
                ccu.table_schema AS referenced_schema,
                ccu.table_name AS referenced_table,
                ccu.column_name AS referenced_column
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage AS ccu
              ON ccu.constraint_name = tc.constraint_name
             AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema NOT IN ('pg_catalog', 'information_schema')
            ORDER BY tc.table_schema, tc.table_name, tc.constraint_name,
                     kcu.ordinal_position
            """
        )
        display = None
    return _ok(
        {"table": display, "foreign_keys": rows, "count": len(rows)}
    )


def find_column(column_name: str) -> str:
    """Find tables that contain a column (supports % wildcards)."""
    if not _COLUMN_PATTERN.fullmatch(column_name):
        return _err(
            "Invalid column pattern. Use letters, numbers, underscore, and %."
        )

    rows = db.fetch_all(
        """
        SELECT
            table_schema,
            table_name,
            column_name,
            data_type,
            is_nullable
        FROM information_schema.columns
        WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
          AND column_name LIKE %s
        ORDER BY table_schema, table_name, ordinal_position
        """,
        (column_name,),
    )
    return _ok({"pattern": column_name, "matches": rows, "count": len(rows)})


def sample_rows(table_name: str, limit: int = 10) -> str:
    """Return sample rows from a table (read-only)."""
    parsed = _split_table(table_name)
    if isinstance(parsed, str):
        return _err(parsed)
    schema, name = parsed
    if limit < 1 or limit > 100:
        return _err("limit must be between 1 and 100.")
    if not _IDENT.fullmatch(schema) or not _IDENT.fullmatch(name):
        return _err("Invalid schema/table identifiers.")

    qualified = f"{_quote_ident(schema)}.{_quote_ident(name)}"
    try:
        rows = db.fetch_all(f"SELECT * FROM {qualified} LIMIT {int(limit)}")
        return _ok(
            {
                "table": f"{schema}.{name}",
                "row_count": len(rows),
                "rows": rows,
            }
        )
    except Exception as exc:
        return _err(str(exc))


def count_rows(table_name: str) -> str:
    """Count rows in a table."""
    parsed = _split_table(table_name)
    if isinstance(parsed, str):
        return _err(parsed)
    schema, name = parsed
    if not _IDENT.fullmatch(schema) or not _IDENT.fullmatch(name):
        return _err("Invalid schema/table identifiers.")

    qualified = f"{_quote_ident(schema)}.{_quote_ident(name)}"
    try:
        row = db.fetch_one(f"SELECT COUNT(*) AS row_count FROM {qualified}")
        return _ok({"table": f"{schema}.{name}", **(row or {})})
    except Exception as exc:
        return _err(str(exc))


def execute_query(query: str, limit: int = 100) -> str:
    """Execute a read-only SQL query and return results as JSON."""
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
