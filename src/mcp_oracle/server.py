"""MCP Oracle server entrypoint."""

from mcp.server.fastmcp import FastMCP

from mcp_oracle import tools

mcp = FastMCP(
    "mcp-oracle",
    instructions=(
        "Oracle database MCP server. Use the tools to inspect schema "
        "and run read-only SQL queries against the configured database."
    ),
)


@mcp.tool()
def test_connection() -> str:
    """Test the Oracle connection and return user, schema, and database name."""
    return tools.test_connection()


@mcp.tool()
def list_tables() -> str:
    """List all tables in the connected Oracle schema (USER_TABLES)."""
    return tools.list_tables()


@mcp.tool()
def describe_table(table_name: str) -> str:
    """
    Describe the columns of an Oracle table in the current schema.

    Args:
        table_name: Name of the table to inspect.
    """
    return tools.describe_table(table_name)


@mcp.tool()
def execute_query(query: str, limit: int = 100) -> str:
    """
    Execute a read-only SQL query (SELECT, WITH).

    Args:
        query: SQL query to run.
        limit: Max rows to return when the query has no FETCH FIRST / ROWNUM (1-1000).
    """
    return tools.execute_query(query, limit)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
