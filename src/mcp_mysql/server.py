"""MCP MySQL server entrypoint."""

import argparse

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from mcp_mysql import tools

mcp = FastMCP(
    "mcp-mysql",
    instructions=(
        "Read-only MySQL MCP for production-safe exploration.\n"
        "\n"
        "Rules:\n"
        "- NEVER attempt writes (INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, "
        "CREATE, GRANT, etc.). They are blocked and the DB user is read-only.\n"
        "- Do not invent table or column names. Discover them with tools first.\n"
        "- Prefer small result sets. Use limits; avoid SELECT * on huge tables.\n"
        "- One statement only; no multi-statement SQL.\n"
        "- For support-ticket hours reports (horas, tiempos, horas extra, horas "
        "compensadas, agentes de apoyo), ALWAYS call report_hours. Never write "
        "your own query or use execute_query for that report.\n"
        "\n"
        "Recommended workflow:\n"
        "1) test_connection if unsure the server is reachable.\n"
        "2) list_tables / list_views / find_column to locate objects.\n"
        "3) describe_table, list_indexes, list_foreign_keys before joins.\n"
        "4) sample_rows or count_rows for a quick look.\n"
        "5) execute_query only for specific analytical SELECT/SHOW/DESCRIBE/"
        "EXPLAIN/WITH queries.\n"
        "\n"
        "When answering, cite the objects and filters you used. "
        "If a query fails, fix names/types from schema tools instead of guessing."
    ),
)


@mcp.tool()
def test_connection() -> str:
    """Test the MySQL connection and return database name and version."""
    return tools.test_connection()


@mcp.tool()
def list_tables() -> str:
    """List all tables in the configured MySQL database."""
    return tools.list_tables()


@mcp.tool()
def list_views() -> str:
    """List all views in the configured MySQL database."""
    return tools.list_views()


@mcp.tool()
def describe_table(table_name: str) -> str:
    """
    Describe the columns of a MySQL table.

    Args:
        table_name: Name of the table to inspect.
    """
    return tools.describe_table(table_name)


@mcp.tool()
def list_indexes(table_name: str) -> str:
    """
    List indexes for a MySQL table.

    Args:
        table_name: Name of the table.
    """
    return tools.list_indexes(table_name)


@mcp.tool()
def list_foreign_keys(table_name: str = "") -> str:
    """
    List foreign keys for one table, or all in the current database.

    Args:
        table_name: Optional table name. Empty = all foreign keys.
    """
    return tools.list_foreign_keys(table_name)


@mcp.tool()
def find_column(column_name: str) -> str:
    """
    Find tables that contain a column name (supports % wildcards).

    Args:
        column_name: Exact name or pattern, e.g. customer_id or %email%.
    """
    return tools.find_column(column_name)


@mcp.tool()
def sample_rows(table_name: str, limit: int = 10) -> str:
    """
    Return sample rows from a table.

    Args:
        table_name: Table name.
        limit: Max rows (1-100). Default 10.
    """
    return tools.sample_rows(table_name, limit)


@mcp.tool()
def count_rows(table_name: str) -> str:
    """
    Count rows in a table.

    Args:
        table_name: Table name.
    """
    return tools.count_rows(table_name)


@mcp.tool()
def execute_query(query: str, limit: int = 100) -> str:
    """
    Execute a read-only SQL query (SELECT, SHOW, DESCRIBE, EXPLAIN, WITH).

    Args:
        query: SQL query to run.
        limit: Max rows when the query has no LIMIT (1-1000).
    """
    return tools.execute_query(query, limit)


@mcp.tool()
def report_hours(desde: str, hasta: str) -> str:
    """
    Official support-ticket hours report (osTicket).

    ALWAYS use this tool when asked for ticket hours, times, overtime,
    compensated hours or support agents. It runs a fixed, validated query
    from resources/querys/hours.sql. Do NOT build your own query and do NOT
    use execute_query for this report.

    Args:
        desde: Start date (ticket creation), format YYYYMMDD, e.g. 20260101.
        hasta: End date (inclusive), format YYYYMMDD, e.g. 20260826.
    """
    return tools.report_hours(desde, hasta)


def main() -> None:
    parser = argparse.ArgumentParser(prog="mcp-mysql")
    parser.add_argument(
        "--transport", choices=["stdio", "streamable-http"], default="stdio"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--allowed-host",
        action="append",
        default=[],
        help="Extra Host header accepted over HTTP, e.g. host.docker.internal:*",
    )
    args = parser.parse_args()

    if args.transport == "streamable-http":
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        # DNS rebinding protection: only localhost and --allowed-host values.
        mcp.settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*", *args.allowed_host],
        )

    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
