"""MCP tools for SQL Server operations (read-only)."""

from __future__ import annotations

import json
import re

from mcp_sqlserver import db

_READ_ONLY_START = re.compile(
    r"^\s*(SELECT|WITH)\b",
    re.IGNORECASE | re.DOTALL,
)
_FORBIDDEN_SQL = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|REPLACE|GRANT|REVOKE|"
    r"EXEC|EXECUTE|MERGE|XP_|SP_CONFIGURE|OPENROWSET|OPENDATASOURCE|BULK)\b",
    re.IGNORECASE,
)
_HAS_ROW_LIMIT = re.compile(
    r"\bTOP\s+\d+\b|\bFETCH\s+(FIRST|NEXT)\s+\d+\s+ROWS?\s+ONLY\b|\bOFFSET\s+\d+\s+ROWS\b",
    re.IGNORECASE,
)
_TABLE_NAME = re.compile(r"^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)?$")
_COLUMN_PATTERN = re.compile(r"^[A-Za-z0-9_%]+$")


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
        schema, name = "dbo", table_name
    return schema, name


def _validate_read_only_query(query: str) -> str | None:
    stripped = query.strip()
    if not stripped:
        return "Query is empty."
    if ";" in stripped.rstrip(";"):
        return "Multiple statements are not allowed. Remove extra semicolons."
    if not _READ_ONLY_START.match(stripped):
        return "Only read-only queries are allowed (SELECT, WITH)."
    if _FORBIDDEN_SQL.search(stripped):
        return "Query contains forbidden write/admin keywords."
    return None


def _quote_ident(name: str) -> str:
    return "[" + name.replace("]", "]]") + "]"


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
        version = payload.get("version")
        if isinstance(version, str) and len(version) > 200:
            payload["version"] = version.split("\n")[0].strip()
        return _ok({"status": "connected", **payload})
    except Exception as exc:
        return _ok({"status": "error", "error": str(exc)})


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
    tables = [f"{row['table_schema']}.{row['table_name']}" for row in rows]
    return _ok({"tables": tables, "count": len(tables)})


def list_views() -> str:
    """List views in the current database."""
    rows = db.fetch_all(
        """
        SELECT TABLE_SCHEMA AS view_schema, TABLE_NAME AS view_name
        FROM INFORMATION_SCHEMA.VIEWS
        ORDER BY TABLE_SCHEMA, TABLE_NAME
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
            i.name AS index_name,
            i.is_unique,
            i.is_primary_key,
            c.name AS column_name,
            ic.key_ordinal
        FROM sys.indexes i
        JOIN sys.index_columns ic
          ON i.object_id = ic.object_id AND i.index_id = ic.index_id
        JOIN sys.columns c
          ON ic.object_id = c.object_id AND ic.column_id = c.column_id
        JOIN sys.tables t ON i.object_id = t.object_id
        JOIN sys.schemas s ON t.schema_id = s.schema_id
        WHERE s.name = ? AND t.name = ?
        ORDER BY i.name, ic.key_ordinal
        """,
        (schema, name),
    )
    return _ok(
        {"table": f"{schema}.{name}", "indexes": rows, "count": len(rows)}
    )


def list_foreign_keys(table_name: str = "") -> str:
    """List foreign keys for one table, or all in the current database."""
    if table_name:
        parsed = _split_table(table_name)
        if isinstance(parsed, str):
            return _err(parsed)
        schema, name = parsed
        rows = db.fetch_all(
            """
            SELECT
                fk.name AS constraint_name,
                sch.name AS table_schema,
                tab.name AS table_name,
                col.name AS column_name,
                rsch.name AS referenced_schema,
                rtab.name AS referenced_table,
                rcol.name AS referenced_column
            FROM sys.foreign_keys fk
            JOIN sys.foreign_key_columns fkc
              ON fk.object_id = fkc.constraint_object_id
            JOIN sys.tables tab ON fkc.parent_object_id = tab.object_id
            JOIN sys.schemas sch ON tab.schema_id = sch.schema_id
            JOIN sys.columns col
              ON fkc.parent_object_id = col.object_id
             AND fkc.parent_column_id = col.column_id
            JOIN sys.tables rtab ON fkc.referenced_object_id = rtab.object_id
            JOIN sys.schemas rsch ON rtab.schema_id = rsch.schema_id
            JOIN sys.columns rcol
              ON fkc.referenced_object_id = rcol.object_id
             AND fkc.referenced_column_id = rcol.column_id
            WHERE sch.name = ? AND tab.name = ?
            ORDER BY fk.name, fkc.constraint_column_id
            """,
            (schema, name),
        )
        display = f"{schema}.{name}"
    else:
        rows = db.fetch_all(
            """
            SELECT
                fk.name AS constraint_name,
                sch.name AS table_schema,
                tab.name AS table_name,
                col.name AS column_name,
                rsch.name AS referenced_schema,
                rtab.name AS referenced_table,
                rcol.name AS referenced_column
            FROM sys.foreign_keys fk
            JOIN sys.foreign_key_columns fkc
              ON fk.object_id = fkc.constraint_object_id
            JOIN sys.tables tab ON fkc.parent_object_id = tab.object_id
            JOIN sys.schemas sch ON tab.schema_id = sch.schema_id
            JOIN sys.columns col
              ON fkc.parent_object_id = col.object_id
             AND fkc.parent_column_id = col.column_id
            JOIN sys.tables rtab ON fkc.referenced_object_id = rtab.object_id
            JOIN sys.schemas rsch ON rtab.schema_id = rsch.schema_id
            JOIN sys.columns rcol
              ON fkc.referenced_object_id = rcol.object_id
             AND fkc.referenced_column_id = rcol.column_id
            ORDER BY sch.name, tab.name, fk.name, fkc.constraint_column_id
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
            TABLE_SCHEMA AS table_schema,
            TABLE_NAME AS table_name,
            COLUMN_NAME AS column_name,
            DATA_TYPE AS data_type,
            IS_NULLABLE AS is_nullable
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE COLUMN_NAME LIKE ?
        ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION
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

    qualified = f"{_quote_ident(schema)}.{_quote_ident(name)}"
    try:
        rows = db.fetch_all(
            f"SELECT TOP {int(limit)} * FROM {qualified}"
        )
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
        return _ok({"row_count": len(rows), "rows": rows})
    except Exception as exc:
        return _err(str(exc))
