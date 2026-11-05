"""MCP tools for read-only osTicket queries.

Each tool validates its arguments before any database work and runs all of its
queries on one read-only connection (see ``db.session``).
"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel, ValidationError

from mcp_mysql import db, tickets
from mcp_mysql.access import ALLOWED_TABLE_COLUMNS, get_allowed_columns
from mcp_mysql.errors import ErrorCode
from mcp_mysql.responses import MAX_FIELD_CHARACTERS, encode_response, error_response, exception_response
from mcp_mysql.validation import (
    MAX_SAMPLE_ROWS, AgentReportArguments, CatalogArguments, CompanySearchArguments, CompanyTicketsArguments,
    PeopleArguments, SearchTicketsArguments, ThreadArguments, TicketArguments, TicketFilters,
    TicketReportArguments, UserArguments, UserSearchArguments,
)


def _err(code: ErrorCode, operation: str) -> str:
    return error_response(code, operation=operation)


def _run(operation: str, model: type[BaseModel], values: dict, function: Callable) -> str:
    try:
        arguments = model.model_validate(values)
    except ValidationError:
        return _err(ErrorCode.INVALID_ARGUMENTS, operation)
    try:
        with db.session():
            return encode_response(function(arguments))
    except Exception as exc:
        return exception_response(exc, operation=operation)


# Exploration tools (administrators only; disabled unless MCP_ENABLE_EXPLORATION_TOOLS) ---------

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
    """Verify connectivity and report the database clock used to interpret dates."""
    try:
        row = db.fetch_one(
            "SELECT 1 AS ok, DATABASE() AS `database_name`, VERSION() AS `version`, "
            "NOW() AS `server_time`, @@session.time_zone AS `time_zone`, "
            "@@system_time_zone AS `system_time_zone`"
        )
        return encode_response({"status": "connected", **(row or {})})
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
        return encode_response({"tables": tables, "count": len(tables)})
    except Exception as exc:
        return exception_response(exc, operation="list_tables")


def describe_table(table_name: str) -> str:
    """Return only permitted column definitions of an authorized table."""
    try:
        rows = _describe_allowed_columns(table_name)
        if not rows:
            return _err(ErrorCode.NO_PERMITTED_COLUMNS, "describe_table")
        return encode_response({"table": table_name, "columns": rows})
    except Exception as exc:
        return exception_response(exc, operation="describe_table")


def sample_rows(table_name: str, limit: int = 10) -> str:
    """Sample only approved, existing columns of an authorized table."""
    if type(limit) is not int or limit < 1 or limit > MAX_SAMPLE_ROWS:
        return _err(ErrorCode.INVALID_ARGUMENTS, "sample_rows")

    try:
        with db.session():
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
        return encode_response(
            {"table": table_name, "row_count": len(safe_rows), "rows": safe_rows}, is_sample=True,
        )
    except Exception as exc:
        return exception_response(exc, operation="sample_rows")


# Support tools ------------------------------------------------------------------------------

def list_catalog(kind: str) -> str:
    """List statuses, departments, priorities, help topics, teams or SLAs with their IDs."""
    return _run("list_catalog", CatalogArguments, locals(), tickets.catalog)


def find_companies(name: str, limit: int = 20, offset: int = 0) -> str:
    """Search the company catalog on the server, including entries beyond any sample."""
    return _run("find_companies", CompanySearchArguments, locals(), tickets.companies)


def list_company_tickets(company_id: int, **filters) -> str:
    """Search a company's tickets with bounded pagination and explicit filters."""
    return _run("list_company_tickets", CompanyTicketsArguments, {"company_id": company_id, **filters},
                tickets.company_tickets)


def search_tickets(**filters) -> str:
    """Search the full ticket set using validated filters, never a sample."""
    return _run("search_tickets", SearchTicketsArguments, filters, tickets.search)


def count_tickets(**filters) -> str:
    """Count all matching tickets on the server, independently of page limits."""
    return _run("count_tickets", TicketFilters, filters, tickets.count)


def ticket_report(group_by: str, **filters) -> str:
    """Count matching tickets grouped by one dimension, optionally with recorded time."""
    return _run("ticket_report", TicketReportArguments, {"group_by": group_by, **filters}, tickets.report)


def get_ticket(ticket_id: int | None = None, number: str | None = None) -> str:
    """Get one ticket by its internal ID or public number (exactly one)."""
    return _run("get_ticket", TicketArguments, locals(), tickets.detail)


def get_ticket_thread(ticket_id: int, **options) -> str:
    """Read a ticket's thread as plain text, with a continuation cursor."""
    return _run("get_ticket_thread", ThreadArguments, {"ticket_id": ticket_id, **options}, tickets.thread)


def find_agents(name: str, limit: int = 20, offset: int = 0) -> str:
    """Resolve staff IDs by literal full-name substring, without authentication fields."""
    return _run("find_agents", PeopleArguments, locals(), tickets.agents)


def get_agent_report(staff_id: int, **options) -> str:
    """Workload, activity and recorded time of one agent."""
    return _run("get_agent_report", AgentReportArguments, {"staff_id": staff_id, **options}, tickets.agent_report)


def find_users(query: str, limit: int = 20, offset: int = 0) -> str:
    """Resolve customer IDs by literal substring of a name or email address."""
    return _run("find_users", UserSearchArguments, locals(), tickets.users)


def get_user(user_id: int) -> str:
    """Customer profile: emails, ticket totals, companies and latest ticket."""
    return _run("get_user", UserArguments, locals(), tickets.user_profile)
