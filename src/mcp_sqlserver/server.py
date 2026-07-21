"""MCP SQL Server entrypoint."""

from mcp.server.fastmcp import FastMCP

from mcp_sqlserver import tools

mcp = FastMCP(
    # name of the MCP server
    "mcp-sqlserver",
    # instructions for the MCP server
    instructions=(
        "SQL Server database MCP server. Use the tools to inspect schema "
        "and run read-only SQL queries against the configured database."
    ),
)

# tool to test the SQL Server connection
@mcp.tool()
def test_connection() -> str:
    """Test the SQL Server connection and return database name and version."""
    return tools.test_connection()

# tool to list all base tables in the configured SQL Server database
@mcp.tool()
def list_tables() -> str:
    """List all base tables in the configured SQL Server database."""
    return tools.list_tables()


# tool to describe the columns of a SQL Server table
@mcp.tool()
def describe_table(table_name: str) -> str:
    """
    Describe the columns of a SQL Server table.

    Args:
        table_name: Table name as Table or Schema.Table (default schema dbo).
    """
    return tools.describe_table(table_name)


# tool to execute a read-only SQL query (SELECT, WITH)
@mcp.tool()
def execute_query(query: str, limit: int = 100) -> str:
    """
    Execute a read-only SQL query (SELECT, WITH).

    Args:
        query: SQL query to run.
        limit: Max rows for SELECT without TOP/FETCH/OFFSET (1-1000).
    """
    return tools.execute_query(query, limit)


# main function to run the MCP server
def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
