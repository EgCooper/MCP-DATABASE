"""MCP tools for Informix operations (read-only)."""

from __future__ import annotations

import json
import re

from mcp_informix import db

_READ_ONLY_START = re.compile(
    r"^\s*(SELECT|WITH)\b",
    re.IGNORECASE | re.DOTALL,
)
_FORBIDDEN_SQL = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|REPLACE|GRANT|REVOKE|"
    r"EXECUTE|MERGE|LOAD|BEGIN|UNLOCK|LOCK)\b",
    re.IGNORECASE,
)
_HAS_ROW_LIMIT = re.compile(
    r"\bFIRST\s+\d+\b|\bLIMIT\s+\d+\b|\bSKIP\s+\d+\b",
    re.IGNORECASE,
)
_TABLE_NAME = re.compile(r"^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)?$")
_COLUMN_PATTERN = re.compile(r"^[A-Za-z0-9_%]+$")
_IDENT = re.compile(r"^[A-Za-z0-9_]+$")


def _ok(payload: dict) -> str:
    return json.dumps(payload, indent=2, default=str)


def _err(message: str) -> str:
    return _ok({"error": message})


def _split_table(table_name: str) -> tuple[str | None, str] | str:
    if not _TABLE_NAME.fullmatch(table_name):
        return (
            "Invalid table name. Use Table or Owner.Table "
            "(letters, numbers, underscore)."
        )
    if "." in table_name:
        owner, name = table_name.split(".", 1)
        return owner, name
    return None, table_name


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


def _qualified(owner: str | None, name: str) -> str:
    if owner:
        return f"{owner}.{name}"
    return name


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
        return _ok({"status": "connected", **(row or {})})
    except Exception as exc:
        return _ok({"status": "error", "error": str(exc)})


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
    return _ok({"tables": tables, "count": len(tables)})


def list_views() -> str:
    """List views in the current Informix database."""
    rows = db.fetch_all(
        """
        SELECT tabname AS view_name, owner AS view_owner
        FROM systables
        WHERE tabtype = 'V' AND tabid >= 100
        ORDER BY tabname
        """
    )
    views = [
        f"{row['view_owner']}.{row['view_name']}".strip()
        if row.get("view_owner")
        else row["view_name"]
        for row in rows
    ]
    return _ok({"views": views, "count": len(views)})


def describe_table(table_name: str) -> str:
    """Return column definitions for a table (owner.table or table)."""
    parsed = _split_table(table_name)
    if isinstance(parsed, str):
        return _err(parsed)
    owner, name = parsed

    if owner:
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
            (name,),
        )

    display = _qualified(owner, name)
    if not rows:
        return _err(f"Table '{display}' not found or has no columns.")
    return _ok({"table": display, "columns": rows})


def list_indexes(table_name: str) -> str:
    """List indexes for a table."""
    parsed = _split_table(table_name)
    if isinstance(parsed, str):
        return _err(parsed)
    owner, name = parsed

    if owner:
        rows = db.fetch_all(
            """
            SELECT
                i.idxname AS index_name,
                i.idxtype AS index_type,
                t.tabname AS table_name,
                t.owner AS table_owner
            FROM systables t, sysindexes i
            WHERE t.tabid = i.tabid
              AND t.tabname = ?
              AND t.owner = ?
            ORDER BY i.idxname
            """,
            (name, owner),
        )
    else:
        rows = db.fetch_all(
            """
            SELECT
                i.idxname AS index_name,
                i.idxtype AS index_type,
                t.tabname AS table_name,
                t.owner AS table_owner
            FROM systables t, sysindexes i
            WHERE t.tabid = i.tabid
              AND t.tabname = ?
              AND t.tabtype = 'T'
            ORDER BY i.idxname
            """,
            (name,),
        )
    return _ok(
        {
            "table": _qualified(owner, name),
            "indexes": rows,
            "count": len(rows),
        }
    )


def list_foreign_keys(table_name: str = "") -> str:
    """List foreign keys for one table, or all user foreign keys."""
    if table_name:
        parsed = _split_table(table_name)
        if isinstance(parsed, str):
            return _err(parsed)
        owner, name = parsed
        if owner:
            rows = db.fetch_all(
                """
                SELECT
                    c.constrname AS constraint_name,
                    t.tabname AS table_name,
                    t.owner AS table_owner,
                    rt.tabname AS referenced_table,
                    rt.owner AS referenced_owner
                FROM systables t, sysconstraints c, sysreferences r, systables rt
                WHERE t.tabid = c.tabid
                  AND c.constrid = r.constrid
                  AND r.ptabid = rt.tabid
                  AND c.constrtype = 'R'
                  AND t.tabname = ?
                  AND t.owner = ?
                ORDER BY c.constrname
                """,
                (name, owner),
            )
        else:
            rows = db.fetch_all(
                """
                SELECT
                    c.constrname AS constraint_name,
                    t.tabname AS table_name,
                    t.owner AS table_owner,
                    rt.tabname AS referenced_table,
                    rt.owner AS referenced_owner
                FROM systables t, sysconstraints c, sysreferences r, systables rt
                WHERE t.tabid = c.tabid
                  AND c.constrid = r.constrid
                  AND r.ptabid = rt.tabid
                  AND c.constrtype = 'R'
                  AND t.tabname = ?
                ORDER BY c.constrname
                """,
                (name,),
            )
        display = _qualified(owner, name)
    else:
        rows = db.fetch_all(
            """
            SELECT
                c.constrname AS constraint_name,
                t.tabname AS table_name,
                t.owner AS table_owner,
                rt.tabname AS referenced_table,
                rt.owner AS referenced_owner
            FROM systables t, sysconstraints c, sysreferences r, systables rt
            WHERE t.tabid = c.tabid
              AND c.constrid = r.constrid
              AND r.ptabid = rt.tabid
              AND c.constrtype = 'R'
              AND t.tabid >= 100
            ORDER BY t.tabname, c.constrname
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
            t.tabname AS table_name,
            t.owner AS table_owner,
            c.colname AS column_name,
            c.coltype AS coltype,
            c.collength AS collength
        FROM systables t, syscolumns c
        WHERE t.tabid = c.tabid
          AND t.tabtype = 'T'
          AND t.tabid >= 100
          AND c.colname LIKE ?
        ORDER BY t.tabname, c.colno
        """,
        (column_name,),
    )
    return _ok({"pattern": column_name, "matches": rows, "count": len(rows)})


def sample_rows(table_name: str, limit: int = 10) -> str:
    """Return sample rows from a table (read-only)."""
    parsed = _split_table(table_name)
    if isinstance(parsed, str):
        return _err(parsed)
    owner, name = parsed
    if limit < 1 or limit > 100:
        return _err("limit must be between 1 and 100.")
    if owner and not _IDENT.fullmatch(owner):
        return _err("Invalid owner name.")
    if not _IDENT.fullmatch(name):
        return _err("Invalid table name.")

    qualified = _qualified(owner, name)
    try:
        rows = db.fetch_all(
            f"SELECT FIRST {int(limit)} * FROM {qualified}"
        )
        return _ok(
            {"table": qualified, "row_count": len(rows), "rows": rows}
        )
    except Exception as exc:
        return _err(str(exc))


def count_rows(table_name: str) -> str:
    """Count rows in a table."""
    parsed = _split_table(table_name)
    if isinstance(parsed, str):
        return _err(parsed)
    owner, name = parsed
    if owner and not _IDENT.fullmatch(owner):
        return _err("Invalid owner name.")
    if not _IDENT.fullmatch(name):
        return _err("Invalid table name.")

    qualified = _qualified(owner, name)
    try:
        row = db.fetch_one(f"SELECT COUNT(*) AS row_count FROM {qualified}")
        return _ok({"table": qualified, **(row or {})})
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
            rf"\1\2FIRST {limit} ",
            normalized,
            count=1,
        )

    try:
        rows = db.fetch_all(normalized)
        return _ok({"row_count": len(rows), "rows": rows})
    except Exception as exc:
        return _err(str(exc))
