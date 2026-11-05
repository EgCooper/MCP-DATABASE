#  Implement tools for MySQL operations (read-only) in the MCP server.
"""MCP tools for MySQL operations (read-only)."""

from __future__ import annotations

from pydantic import ValidationError

from mcp_mysql import db, tickets
from mcp_mysql.access import ALLOWED_TABLE_COLUMNS, get_allowed_columns
from mcp_mysql.config import MySQLConfig
from mcp_mysql.errors import AccessDeniedError, ErrorCode
from mcp_mysql.responses import MAX_FIELD_CHARACTERS, encode_response, error_response, exception_response
from mcp_mysql.validation import (
    MAX_SAMPLE_ROWS, CompanySearchArguments, CompanyTicketsArguments,
    PeopleArguments, SearchTicketsArguments, ThreadArguments, TicketArguments, TicketFilters,
)


def _ok(payload: dict, *, is_sample: bool = False) -> str:
    return encode_response(payload, is_sample=is_sample)


def _err(code: ErrorCode, operation: str) -> str:
    return error_response(code, operation=operation)


def _require_columns(required: dict[str, tuple[str, ...]]) -> None:
    """Business queries must obey the same table and column policy as exploration."""
    for table, columns in required.items():
        if not set(columns).issubset(get_allowed_columns(table)):
            raise AccessDeniedError("Business query is outside the access policy")


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
        return exception_response(exc, operation="test_connection")


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
        return exception_response(exc, operation="list_tables")


def describe_table(table_name: str) -> str:
    """Return only permitted column definitions of an authorized table."""
    try:
        rows = _describe_allowed_columns(table_name)
        if not rows:
            return _err(ErrorCode.NO_PERMITTED_COLUMNS, "describe_table")
        return _ok({"table": table_name, "columns": rows})
    except Exception as exc:
        return exception_response(exc, operation="describe_table")


def sample_rows(table_name: str, limit: int = 10) -> str:
    """Sample only approved, existing columns of an authorized table."""
    if type(limit) is not int or limit < 1 or limit > MAX_SAMPLE_ROWS:
        return _err(ErrorCode.INVALID_ARGUMENTS, "sample_rows")

    try:
        metadata = _describe_allowed_columns(table_name)
        if not metadata:
            return _err(ErrorCode.NO_PERMITTED_COLUMNS, "sample_rows")
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
            {"table": table_name, "row_count": len(safe_rows), "rows": safe_rows}, is_sample=True,
        )
    except Exception as exc:
        return exception_response(exc, operation="sample_rows")


def find_companies(name: str, limit: int = 20, offset: int = 0) -> str:
    """Search the company catalog on the server, including entries beyond any sample."""
    try:
        arguments = CompanySearchArguments(name=name, limit=limit, offset=offset)
        _require_columns({"ost_list_items": ("id", "list_id", "value", "status")})
        catalog = MySQLConfig.from_env().company_list_id
        # Treat LIKE metacharacters as literal input, using a SQL-mode-independent escape.
        literal = arguments.name.replace("=", "==").replace("%", "=%").replace("_", "=_")
        rows = db.fetch_all(
            """
            SELECT id AS company_id, LEFT(value, %s) AS name, status
            FROM ost_list_items
            WHERE list_id = %s AND value LIKE %s ESCAPE '='
            ORDER BY (value = %s) DESC, value ASC, id ASC
            LIMIT %s OFFSET %s
            """,
            (MAX_FIELD_CHARACTERS + 1, catalog, f"%{literal}%", arguments.name, arguments.limit + 1, arguments.offset),
        )
        return _ok({
            "query": arguments.name, "company_list_id": catalog,
            **tickets.page_rows(rows, arguments.limit, arguments.offset),
        })
    except ValidationError:
        return _err(ErrorCode.INVALID_ARGUMENTS, "find_companies")
    except Exception as exc:
        return exception_response(exc, operation="find_companies")


def _business_call(operation: str, model, values: dict, function) -> str:
    try:
        arguments = model.model_validate(values)
        return _ok(function(arguments))
    except ValidationError:
        return _err(ErrorCode.INVALID_ARGUMENTS, operation)
    except Exception as exc:
        return exception_response(exc, operation=operation)


def list_company_tickets(
    company_id: int, limit: int = 10, offset: int = 0, order: str = "newest",
    staff_id: int | None = None, user_id: int | None = None, status: str | None = None,
    created_from: str | None = None, created_to: str | None = None, subject: str | None = None,
) -> str:
    """Search a company's tickets with bounded pagination and explicit filters."""
    return _business_call("list_company_tickets", CompanyTicketsArguments, locals(), tickets.company_tickets)


def search_tickets(
    company_id: int | None = None, staff_id: int | None = None, user_id: int | None = None,
    status: str | None = None, created_from: str | None = None, created_to: str | None = None,
    subject: str | None = None, limit: int = 20, offset: int = 0, order: str = "newest",
) -> str:
    """Search the full ticket set using validated filters, never a sample."""
    return _business_call("search_tickets", SearchTicketsArguments, locals(), tickets.search)


def count_tickets(
    company_id: int | None = None, staff_id: int | None = None, user_id: int | None = None,
    status: str | None = None, created_from: str | None = None, created_to: str | None = None,
    subject: str | None = None,
) -> str:
    """Count all matching tickets on the server, independently of page limits."""
    return _business_call("count_tickets", TicketFilters, locals(), tickets.count)


def get_ticket(ticket_id: int | None = None, number: str | None = None) -> str:
    """Get one ticket by its internal ID or public number (exactly one)."""
    return _business_call("get_ticket", TicketArguments, locals(), tickets.detail)


def get_ticket_thread(ticket_id: int, after_entry_id: int = 0, limit: int = 20) -> str:
    """Read a ticket's thread in ascending entry ID order, with a continuation cursor."""
    return _business_call("get_ticket_thread", ThreadArguments, locals(), tickets.thread)


def find_agents(name: str, limit: int = 20, offset: int = 0) -> str:
    """Resolve staff IDs by literal full-name substring, without authentication fields."""
    return _business_call("find_agents", PeopleArguments, locals(), lambda args: tickets.people(args, agents=True))


def find_users(name: str, limit: int = 20, offset: int = 0) -> str:
    """Resolve customer IDs by literal name substring."""
    return _business_call("find_users", PeopleArguments, locals(), lambda args: tickets.people(args, agents=False))
