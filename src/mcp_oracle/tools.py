"""MCP tools for Oracle operations (read-only, multi-connection)."""

from __future__ import annotations

import json
import re

from mcp_oracle import db
from mcp_oracle import config as oracle_config

_READ_ONLY_START = re.compile(
    r"^\s*(SELECT|WITH)\b",
    re.IGNORECASE | re.DOTALL,
)
_FORBIDDEN_SQL = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|REPLACE|GRANT|REVOKE|"
    r"CALL|EXEC|EXECUTE|MERGE|BEGIN|DECLARE|DBMS_)\b",
    re.IGNORECASE,
)
_FETCH_LIMIT_PATTERN = re.compile(
    r"\bFETCH\s+(FIRST|NEXT)\s+\d+\s+ROWS?\s+ONLY\b",
    re.IGNORECASE,
)
_TABLE_NAME = re.compile(r"^[A-Za-z0-9_$#]+$")
_COLUMN_PATTERN = re.compile(r"^[A-Za-z0-9_$#%]+$")


def _ok(payload: dict) -> str:
    return json.dumps(payload, indent=2, default=str)


def _err(message: str) -> str:
    return _ok({"error": message})


def _resolve(connection: str) -> tuple[str | None, str | None]:
    """Return (resolved_name, error_message)."""
    try:
        return oracle_config.resolve_connection_name(connection), None
    except Exception as exc:
        return None, str(exc)


def _validate_table_name(table_name: str) -> str | None:
    if not _TABLE_NAME.fullmatch(table_name):
        return "Invalid table name. Use letters, numbers, underscore, $ or #."
    return None


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


def list_connections() -> str:
    """List configured Oracle connection profiles (no passwords)."""
    try:
        summaries = oracle_config.connection_summaries()
        default = oracle_config.get_default_connection_name()
        return _ok(
            {
                "connections": summaries,
                "default": default,
                "count": len(summaries),
            }
        )
    except Exception as exc:
        return _err(str(exc))


def test_connection(connection: str = "") -> str:
    """Verify connectivity to Oracle for a named profile (or default)."""
    name, err = _resolve(connection)
    if err:
        return _err(err)
    try:
        row = db.fetch_one(
            """
            SELECT
                1 AS ok,
                USER AS username,
                SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA') AS current_schema,
                SYS_CONTEXT('USERENV', 'DB_NAME') AS db_name
            FROM dual
            """,
            connection=name,
        )
        return _ok({"status": "connected", "connection": name, **(row or {})})
    except Exception as exc:
        return _ok({"status": "error", "connection": name, "error": str(exc)})


def list_tables(connection: str = "") -> str:
    """List tables visible to the connected Oracle user."""
    name, err = _resolve(connection)
    if err:
        return _err(err)
    rows = db.fetch_all(
        "SELECT table_name FROM user_tables ORDER BY table_name",
        connection=name,
    )
    if not rows:
        return _ok({"connection": name, "tables": [], "count": 0})
    tables = [row["table_name"] for row in rows]
    return _ok({"connection": name, "tables": tables, "count": len(tables)})


def list_views(connection: str = "") -> str:
    """List views in the current schema."""
    name, err = _resolve(connection)
    if err:
        return _err(err)
    rows = db.fetch_all(
        "SELECT view_name FROM user_views ORDER BY view_name",
        connection=name,
    )
    views = [row["view_name"] for row in rows]
    return _ok({"connection": name, "views": views, "count": len(views)})


def describe_table(table_name: str, connection: str = "") -> str:
    """Return column definitions for a table in the current schema."""
    name, err = _resolve(connection)
    if err:
        return _err(err)
    terr = _validate_table_name(table_name)
    if terr:
        return _err(terr)

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
        connection=name,
    )
    if not rows:
        return _err(f"Table '{table_name}' not found or has no columns.")
    return _ok(
        {
            "connection": name,
            "table": table_name.upper(),
            "columns": rows,
        }
    )


def list_indexes(table_name: str, connection: str = "") -> str:
    """List indexes for a table in the current schema."""
    name, err = _resolve(connection)
    if err:
        return _err(err)
    terr = _validate_table_name(table_name)
    if terr:
        return _err(terr)

    rows = db.fetch_all(
        """
        SELECT
            i.index_name,
            i.uniqueness,
            i.index_type,
            c.column_name,
            c.column_position
        FROM user_indexes i
        JOIN user_ind_columns c
          ON i.index_name = c.index_name
        WHERE i.table_name = :table_name
        ORDER BY i.index_name, c.column_position
        """,
        {"table_name": table_name.upper()},
        connection=name,
    )
    return _ok(
        {
            "connection": name,
            "table": table_name.upper(),
            "indexes": rows,
            "count": len(rows),
        }
    )


def list_foreign_keys(table_name: str = "", connection: str = "") -> str:
    """List foreign keys for one table, or all in the current schema."""
    name, err = _resolve(connection)
    if err:
        return _err(err)

    if table_name:
        terr = _validate_table_name(table_name)
        if terr:
            return _err(terr)
        rows = db.fetch_all(
            """
            SELECT
                c.constraint_name,
                c.table_name,
                cc.column_name,
                r.table_name AS referenced_table,
                rc.column_name AS referenced_column
            FROM user_constraints c
            JOIN user_cons_columns cc
              ON c.constraint_name = cc.constraint_name
            JOIN user_constraints r
              ON c.r_constraint_name = r.constraint_name
            JOIN user_cons_columns rc
              ON r.constraint_name = rc.constraint_name
             AND cc.position = rc.position
            WHERE c.constraint_type = 'R'
              AND c.table_name = :table_name
            ORDER BY c.constraint_name, cc.position
            """,
            {"table_name": table_name.upper()},
            connection=name,
        )
        display = table_name.upper()
    else:
        rows = db.fetch_all(
            """
            SELECT
                c.constraint_name,
                c.table_name,
                cc.column_name,
                r.table_name AS referenced_table,
                rc.column_name AS referenced_column
            FROM user_constraints c
            JOIN user_cons_columns cc
              ON c.constraint_name = cc.constraint_name
            JOIN user_constraints r
              ON c.r_constraint_name = r.constraint_name
            JOIN user_cons_columns rc
              ON r.constraint_name = rc.constraint_name
             AND cc.position = rc.position
            WHERE c.constraint_type = 'R'
            ORDER BY c.table_name, c.constraint_name, cc.position
            """,
            connection=name,
        )
        display = None
    return _ok(
        {
            "connection": name,
            "table": display,
            "foreign_keys": rows,
            "count": len(rows),
        }
    )


def find_column(column_name: str, connection: str = "") -> str:
    """Find tables that contain a column (supports % wildcards)."""
    name, err = _resolve(connection)
    if err:
        return _err(err)
    if not _COLUMN_PATTERN.fullmatch(column_name):
        return _err(
            "Invalid column pattern. Use letters, numbers, underscore, $, #, and %."
        )

    rows = db.fetch_all(
        """
        SELECT table_name, column_name, data_type, nullable
        FROM user_tab_columns
        WHERE column_name LIKE UPPER(:column_name)
        ORDER BY table_name, column_id
        """,
        {"column_name": column_name},
        connection=name,
    )
    return _ok(
        {
            "connection": name,
            "pattern": column_name,
            "matches": rows,
            "count": len(rows),
        }
    )


def sample_rows(table_name: str, limit: int = 10, connection: str = "") -> str:
    """Return sample rows from a table (read-only)."""
    name, err = _resolve(connection)
    if err:
        return _err(err)
    terr = _validate_table_name(table_name)
    if terr:
        return _err(terr)
    if limit < 1 or limit > 100:
        return _err("limit must be between 1 and 100.")

    try:
        rows = db.fetch_all(
            f'SELECT * FROM "{table_name.upper()}" '
            f"FETCH FIRST {int(limit)} ROWS ONLY",
            connection=name,
        )
        return _ok(
            {
                "connection": name,
                "table": table_name.upper(),
                "row_count": len(rows),
                "rows": rows,
            }
        )
    except Exception as exc:
        return _err(str(exc))


def count_rows(table_name: str, connection: str = "") -> str:
    """Count rows in a table."""
    name, err = _resolve(connection)
    if err:
        return _err(err)
    terr = _validate_table_name(table_name)
    if terr:
        return _err(terr)

    try:
        row = db.fetch_one(
            f'SELECT COUNT(*) AS row_count FROM "{table_name.upper()}"',
            connection=name,
        )
        return _ok(
            {"connection": name, "table": table_name.upper(), **(row or {})}
        )
    except Exception as exc:
        return _err(str(exc))


def execute_query(query: str, limit: int = 100, connection: str = "") -> str:
    """Execute a read-only SQL query and return results as JSON."""
    name, err = _resolve(connection)
    if err:
        return _err(err)
    qerr = _validate_read_only_query(query)
    if qerr:
        return _err(qerr)
    if limit < 1 or limit > 1000:
        return _err("limit must be between 1 and 1000.")

    normalized = query.strip().rstrip(";")
    if not _FETCH_LIMIT_PATTERN.search(normalized) and not re.search(
        r"\bROWNUM\b", normalized, re.IGNORECASE
    ):
        normalized = f"{normalized} FETCH FIRST {limit} ROWS ONLY"

    try:
        rows = db.fetch_all(normalized, connection=name)
        return _ok(
            {"connection": name, "row_count": len(rows), "rows": rows}
        )
    except Exception as exc:
        return _err(str(exc))
