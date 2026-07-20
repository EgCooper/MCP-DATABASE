"""Allow running the server or setup helper.

Usage:
  python -m mcp_mysql                 # start MCP server (stdio)
  python -m mcp_mysql setup           # install mysql into ~/.cursor/mcp.json
  python -m mcp_mysql setup --print   # only print the JSON snippet
"""

from __future__ import annotations

import sys


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        from mcp_mysql.setup import main as setup_main

        setup_main(sys.argv[2:])
        return

    from mcp_mysql.server import main as server_main

    server_main()


if __name__ == "__main__":
    main()
