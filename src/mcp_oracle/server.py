"""MCP Oracle server entrypoint."""

import argparse

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from mcp_oracle import tools

mcp = FastMCP(
    "mcp-oracle",
    instructions=(
        "Read-only Oracle MCP for production-safe exploration.\n"
        "\n"
        "Multiple connections:\n"
        "- Call list_connections to see available profiles and the default.\n"
        "- Pass connection=\"name\" on every tool when targeting a non-default DB.\n"
        "- Always state which connection you used in your answer.\n"
        "\n"
        "Rules:\n"
        "- NEVER attempt writes (INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, "
        "CREATE, GRANT, MERGE, etc.). They are blocked and the DB user is read-only.\n"
        "- Do not invent table or column names. Discover them with tools first.\n"
        "- Prefer small result sets. Use limits; avoid SELECT * on huge tables.\n"
        "- One statement only; no multi-statement SQL.\n"
        "- Identifiers are typically UPPERCASE in Oracle catalogs.\n"
        "\n"
        "Recommended workflow:\n"
        "1) list_connections (and test_connection) if unsure.\n"
        "2) list_tables / list_views / find_column with the chosen connection.\n"
        "3) describe_table, list_indexes, list_foreign_keys before joins.\n"
        "4) sample_rows or count_rows for a quick look.\n"
        "5) execute_query only for specific analytical SELECT/WITH queries "
        "(row limits use FETCH FIRST when needed).\n"
        "\n"
        "When answering, cite the connection, objects, and filters you used. "
        "If a query fails, fix names/types from schema tools instead of guessing."
    ),
)


@mcp.tool()
def list_connections() -> str:
    """List configured Oracle connection profiles and the default (no passwords)."""
    return tools.list_connections()


@mcp.tool()
def test_connection(connection: str = "") -> str:
    """
    Test an Oracle connection profile and return user, schema, and database name.

    Args:
        connection: Profile name from list_connections. Empty = default.
    """
    return tools.test_connection(connection)


@mcp.tool()
def list_tables(connection: str = "") -> str:
    """
    List all tables in the Oracle schema for a connection profile.

    Args:
        connection: Profile name. Empty = default.
    """
    return tools.list_tables(connection)


@mcp.tool()
def list_views(connection: str = "") -> str:
    """
    List views in the Oracle schema for a connection profile.

    Args:
        connection: Profile name. Empty = default.
    """
    return tools.list_views(connection)


@mcp.tool()
def describe_table(table_name: str, connection: str = "") -> str:
    """
    Describe the columns of an Oracle table.

    Args:
        table_name: Name of the table to inspect.
        connection: Profile name. Empty = default.
    """
    return tools.describe_table(table_name, connection)


@mcp.tool()
def list_indexes(table_name: str, connection: str = "") -> str:
    """
    List indexes for an Oracle table.

    Args:
        table_name: Name of the table.
        connection: Profile name. Empty = default.
    """
    return tools.list_indexes(table_name, connection)


@mcp.tool()
def list_foreign_keys(table_name: str = "", connection: str = "") -> str:
    """
    List foreign keys for one table, or all in the schema.

    Args:
        table_name: Optional table name. Empty = all foreign keys.
        connection: Profile name. Empty = default.
    """
    return tools.list_foreign_keys(table_name, connection)


@mcp.tool()
def find_column(column_name: str, connection: str = "") -> str:
    """
    Find tables that contain a column name (supports % wildcards).

    Args:
        column_name: Exact name or pattern, e.g. CUSTOMER_ID or %EMAIL%.
        connection: Profile name. Empty = default.
    """
    return tools.find_column(column_name, connection)


@mcp.tool()
def sample_rows(table_name: str, limit: int = 10, connection: str = "") -> str:
    """
    Return sample rows from a table.

    Args:
        table_name: Table name.
        limit: Max rows (1-100). Default 10.
        connection: Profile name. Empty = default.
    """
    return tools.sample_rows(table_name, limit, connection)


@mcp.tool()
def count_rows(table_name: str, connection: str = "") -> str:
    """
    Count rows in a table.

    Args:
        table_name: Table name.
        connection: Profile name. Empty = default.
    """
    return tools.count_rows(table_name, connection)


@mcp.tool()
def execute_query(query: str, limit: int = 100, connection: str = "") -> str:
    """
    Execute a read-only SQL query (SELECT, WITH).

    Args:
        query: SQL query to run.
        limit: Max rows when the query has no FETCH FIRST / ROWNUM (1-1000).
        connection: Profile name. Empty = default.
    """
    return tools.execute_query(query, limit, connection)


def main() -> None:
    parser = argparse.ArgumentParser(prog="mcp-oracle")
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
