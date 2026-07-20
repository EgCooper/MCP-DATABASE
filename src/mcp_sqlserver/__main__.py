"""Allow running the SQL Server server or setup helper.

Usage:
  python -m mcp_sqlserver                 # start MCP server (stdio)
  python -m mcp_sqlserver setup           # install sqlserver into ~/.cursor/mcp.json
  python -m mcp_sqlserver setup --print   # only print the JSON snippet
"""

from __future__ import annotations

import sys


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        from mcp_sqlserver.setup import main as setup_main

        setup_main(sys.argv[2:])
        return

    from mcp_sqlserver.server import main as server_main

    server_main()


if __name__ == "__main__":
    main()
