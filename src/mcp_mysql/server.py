# Create the mcp server and publish the tools also configure the transport security settings.
"""MCP MySQL server entrypoint."""

import argparse
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import Tool as MCPTool
from pydantic import ValidationError

from mcp_mysql import tools
from mcp_mysql.validation import SampleLimit, TableName, TOOL_ARGUMENT_MODELS


class _ValidatedMCP(FastMCP):
    """Validate raw arguments before FastMCP can coerce or discard them."""

    async def list_tools(self) -> list[MCPTool]:
        definitions = await super().list_tools()
        for definition in definitions:
            definition.inputSchema = TOOL_ARGUMENT_MODELS[definition.name].model_json_schema()
        return definitions

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if type(name) is not str or len(name) > 64 or name not in TOOL_ARGUMENT_MODELS:
            raise ToolError("Unknown tool.")
        try:
            TOOL_ARGUMENT_MODELS[name].model_validate(arguments)
        except ValidationError:
            # Do not echo potentially huge or sensitive argument values in validation errors.
            raise ToolError("Invalid arguments. Use the tool's input schema.") from None
        return await super().call_tool(name, arguments)


mcp = _ValidatedMCP(
    "mcp-mysql",
    instructions=(
        "MySQL MCP for exploring the configured database with fixed queries.\n"
        "\n"
        "Rules:\n"
        "- Use only the available tools; arbitrary SQL is not supported.\n"
        "- Table and column access is restricted by the server's policy.\n"
        "- Entidad means the ticket's company: listaEmpresa in ost_ticket__cdata, "
        "resolved with ost_list_items.\n"
        "- Discover table names with list_tables before inspecting them.\n"
        "- Inspect columns with describe_table before requesting sample rows.\n"
        "- Keep samples small; sample_rows accepts limits from 1 to 100.\n"
        "- If truncated is true, explain that content is incomplete. "
        "Check truncation for shortened fields or omitted rows.\n"
        "\n"
        "Recommended workflow:\n"
        "1) test_connection to verify connectivity.\n"
        "2) list_tables to discover available tables.\n"
        "3) describe_table to inspect a table's columns.\n"
        "4) sample_rows for a small sample of its data.\n"
        "\n"
        "When answering, identify the table and sample size used. "
        "Do not present samples as complete results."
    ),
)


@mcp.tool(structured_output=False)
def test_connection() -> str:
    """Test the MySQL connection and return database name and version."""
    return tools.test_connection()


@mcp.tool(structured_output=False)
def list_tables() -> str:
    """List existing tables permitted by the server's access policy."""
    return tools.list_tables()


@mcp.tool(structured_output=False)
def describe_table(table_name: TableName) -> str:
    """
    Describe only permitted columns of an authorized MySQL table.

    Args:
        table_name: Name of the table to inspect.
    """
    return tools.describe_table(table_name)


@mcp.tool(structured_output=False)
def sample_rows(table_name: TableName, limit: SampleLimit = 10) -> str:
    """
    Return sample rows containing only permitted columns of an authorized table.

    Args:
        table_name: Table name.
        limit: Max rows (1-100). Default 10.
    """
    return tools.sample_rows(table_name, limit)


def main() -> None:
    parser = argparse.ArgumentParser(prog="mcp-mysql")
    parser.add_argument(
        "--transport", choices=["stdio", "streamable-http"], default="streamable-http",
        help="Transport to use (default: streamable-http)."
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
