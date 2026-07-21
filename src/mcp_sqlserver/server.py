"""MCP SQL Server entrypoint."""

from mcp.server.fastmcp import FastMCP

from mcp_sqlserver import tools

mcp = FastMCP(
    "mcp-sqlserver",
    instructions=(
        "Read-only SQL Server MCP for production-safe exploration.\n"
        "\n"
        "Rules:\n"
        "- NEVER attempt writes (INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, "
        "CREATE, GRANT, EXEC, MERGE, etc.). They are blocked and the DB user is "
        "read-only.\n"
        "- Do not invent table or column names. Discover them with tools first.\n"
        "- Prefer small result sets. Use limits; avoid SELECT * on huge tables.\n"
        "- One statement only; no multi-statement SQL.\n"
        "- Use Schema.Table when needed (default schema is often dbo).\n"
        "\n"
        "Recommended workflow:\n"
        "1) test_connection if unsure the server is reachable.\n"
        "2) list_tables / list_views / find_column to locate objects.\n"
        "3) describe_table, list_indexes, list_foreign_keys before joins.\n"
        "4) sample_rows or count_rows for a quick look.\n"
        "5) execute_query only for specific analytical SELECT/WITH queries "
        "(row limits use TOP when needed).\n"
        "\n"
        "When answering, cite the objects and filters you used. "
        "If a query fails, fix names/types from schema tools instead of guessing."
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
def list_views() -> str:
    """List all views in the configured SQL Server database."""
    return tools.list_views()


@mcp.tool()
def describe_table(table_name: str) -> str:
    """
    Describe the columns of a SQL Server table.

    Args:
        table_name: Table name as Table or Schema.Table (default schema dbo).
    """
    return tools.describe_table(table_name)


@mcp.tool()
def list_indexes(table_name: str) -> str:
    """
    List indexes for a SQL Server table.

    Args:
        table_name: Table or Schema.Table.
    """
    return tools.list_indexes(table_name)


@mcp.tool()
def list_foreign_keys(table_name: str = "") -> str:
    """
    List foreign keys for one table, or all in the current database.

    Args:
        table_name: Optional Table or Schema.Table. Empty = all foreign keys.
    """
    return tools.list_foreign_keys(table_name)


@mcp.tool()
def find_column(column_name: str) -> str:
    """
    Find tables that contain a column name (supports % wildcards).

    Args:
        column_name: Exact name or pattern, e.g. CustomerId or %email%.
    """
    return tools.find_column(column_name)


@mcp.tool()
def sample_rows(table_name: str, limit: int = 10) -> str:
    """
    Return sample rows from a table.

    Args:
        table_name: Table or Schema.Table.
        limit: Max rows (1-100). Default 10.
    """
    return tools.sample_rows(table_name, limit)


@mcp.tool()
def count_rows(table_name: str) -> str:
    """
    Count rows in a table.

    Args:
        table_name: Table or Schema.Table.
    """
    return tools.count_rows(table_name)


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
