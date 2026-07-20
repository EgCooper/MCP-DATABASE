"""MCP SQL Server entrypoint."""

from mcp.server.fastmcp import FastMCP

from mcp_sqlserver import tools

mcp = FastMCP(
    "mcp-sqlserver",
    instructions=(
        "SQL Server database MCP server. Use the tools to inspect schema "
        "and run read-only SQL queries against the configured database."
    ),
)


@mcp.tool()
def test_connection() -> str:
    """Test the SQL Server connection and return database name and version."""
    return tools.test_connection()


@mcp.tool()
def list_tables() -> str:
    """List all base tables in the configured SQL Server database."""
    return tools.list_tables()


@mcp.tool()
def describe_table(table_name: str) -> str:
    """
    Describe the columns of a SQL Server table.

    Args:
        table_name: Table name as Table or Schema.Table (default schema dbo).
    """
    return tools.describe_table(table_name)


@mcp.tool()
def execute_query(query: str, limit: int = 100) -> str:
    """
    Execute a read-only SQL query (SELECT, WITH).

    Args:
        query: SQL query to run.
        limit: Max rows for SELECT without TOP/FETCH/OFFSET (1-1000).
    """
    return tools.execute_query(query, limit)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
