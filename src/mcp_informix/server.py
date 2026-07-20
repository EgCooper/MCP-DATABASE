"""MCP Informix server entrypoint."""

from mcp.server.fastmcp import FastMCP

from mcp_informix import tools

mcp = FastMCP(
    "mcp-informix",
    instructions=(
        "Informix database MCP server. Use the tools to inspect schema "
        "and run read-only SQL queries against the configured database."
    ),
)


@mcp.tool()
def test_connection() -> str:
    """Test the Informix connection and return database name and version."""
    return tools.test_connection()


@mcp.tool()
def list_tables() -> str:
    """List user tables in the configured Informix database."""
    return tools.list_tables()


@mcp.tool()
def describe_table(table_name: str) -> str:
    """
    Describe the columns of an Informix table.

    Args:
        table_name: Table name as Table or Owner.Table.
    """
    return tools.describe_table(table_name)


@mcp.tool()
def execute_query(query: str, limit: int = 100) -> str:
    """
    Execute a read-only SQL query (SELECT, WITH).

    Args:
        query: SQL query to run.
        limit: Max rows for SELECT without FIRST/LIMIT/SKIP (1-1000).
    """
    return tools.execute_query(query, limit)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
