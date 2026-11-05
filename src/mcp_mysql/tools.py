#  Implement tools for MySQL operations (read-only) in the MCP server.
"""MCP tools for MySQL operations (read-only)."""

from __future__ import annotations

from mcp_mysql import db
from mcp_mysql.access import ALLOWED_TABLE_COLUMNS, get_allowed_columns
from mcp_mysql.responses import MAX_FIELD_CHARACTERS, encode_response
from mcp_mysql.validation import MAX_SAMPLE_ROWS


def _ok(payload: dict) -> str:
    return encode_response(payload)


def _err(message: str) -> str:
    return _ok({"error": message})


def _describe_allowed_columns(table_name: str) -> list[dict]:
    """Return only approved columns that exist in the configured database."""
    allowed = get_allowed_columns(table_name)
    placeholders = ", ".join("%s" for _ in allowed)
    rows = db.fetch_all(
        f"""
        SELECT COLUMN_NAME AS `Field`, LEFT(COLUMN_TYPE, %s) AS `Type`,
               IS_NULLABLE AS `Null`, COLUMN_KEY AS `Key`,
               LEFT(COLUMN_DEFAULT, %s) AS `Default`, EXTRA AS `Extra`
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND COLUMN_NAME IN ({placeholders})
        ORDER BY ORDINAL_POSITION
        """,
        (MAX_FIELD_CHARACTERS + 1, MAX_FIELD_CHARACTERS + 1, table_name, *allowed),
    )
    return [row for row in rows if row.get("Field") in allowed]


def _sample_projection(metadata: list[dict]) -> tuple[str, tuple]:
    """Bound text/binary data in MySQL before sending it to the application."""
    scalar_types = {
        "tinyint", "smallint", "mediumint", "int", "integer", "bigint",
        "decimal", "numeric", "float", "double", "real", "bit", "bool", "boolean",
        "date", "datetime", "timestamp", "time", "year",
    }
    expressions = []
    parameters = []
    for column in metadata:
        name = column["Field"]
        kind = column.get("Type", "").lower().split("(", 1)[0].split(" ", 1)[0]
        if kind in scalar_types:
            expressions.append(f"`{name}`")
        else:
            expressions.append(f"LEFT(`{name}`, %s) AS `{name}`")
            # The extra character lets the response formatter detect a shortened value.
            parameters.append(MAX_FIELD_CHARACTERS + 1)
    return ", ".join(expressions), tuple(parameters)


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
    if type(limit) is not int or limit < 1 or limit > MAX_SAMPLE_ROWS:
        return _err("limit must be between 1 and 100.")

    try:
        metadata = _describe_allowed_columns(table_name)
        if not metadata:
            return _err("No permitted columns are available for this table.")
        columns = [row["Field"] for row in metadata]
        projection, parameters = _sample_projection(metadata)
        rows = db.fetch_all(
            f"SELECT {projection} FROM `{table_name}` LIMIT %s", (*parameters, limit)
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
