"""MCP Oracle server entrypoint."""

from mcp.server.fastmcp import FastMCP

from mcp_oracle import tools

mcp = FastMCP(
    # name of the MCP server
    "mcp-oracle",
    # instructions for the MCP server
    instructions=(
        "Oracle database MCP server. Use the tools to inspect schema "
        "and run read-only SQL queries against the configured database."
    ),
)

# tool to test the Oracle connection
@mcp.tool()
def test_connection() -> str:
    """Test the Oracle connection and return user, schema, and database name."""
    return tools.test_connection()


# tool to list all tables in the connected Oracle schema (USER_TABLES)
@mcp.tool()
def list_tables() -> str:
    """List all tables in the connected Oracle schema (USER_TABLES)."""
    return tools.list_tables()


# tool to describe the columns of an Oracle table in the current schema
@mcp.tool()
def describe_table(table_name: str) -> str:
    """
    Describe the columns of an Oracle table in the current schema.

    Args:
        table_name: Name of the table to inspect.
    """
    return tools.describe_table(table_name)


# tool to execute a read-only SQL query (SELECT, WITH)
@mcp.tool()
def execute_query(query: str, limit: int = 100) -> str:
    """
    Execute a read-only SQL query (SELECT, WITH).

    Args:
        query: SQL query to run.
        limit: Max rows to return when the query has no FETCH FIRST / ROWNUM (1-1000).
    """
    return tools.execute_query(query, limit)


# main function to run the MCP server
def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
