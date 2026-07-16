"""MCP MySQL server entrypoint."""

from mcp.server.fastmcp import FastMCP

from mcp_mysql import tools

mcp = FastMCP(
    "mcp-mysql",
    instructions=(
        "MySQL database MCP server. Use the tools to inspect schema "
        "and run read-only SQL queries against the configured database."
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
def describe_table(table_name: str) -> str:
    """
    Describe the columns of a MySQL table.

    Args:
        table_name: Name of the table to inspect.
    """
    return tools.describe_table(table_name)


@mcp.tool()
def execute_query(query: str, limit: int = 100) -> str:
    """
    Execute a read-only SQL query (SELECT, SHOW, DESCRIBE, EXPLAIN, WITH).

    Args:
        query: SQL query to run.
        limit: Max rows to return when the query has no LIMIT (1-1000).
    """
    return tools.execute_query(query, limit)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
