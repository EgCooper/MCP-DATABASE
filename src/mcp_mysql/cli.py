"""Command line entry point: run the server or one of its helper subcommands."""

import sys


def main(argv: list[str] | None = None) -> None:
    arguments = sys.argv[1:] if argv is None else list(argv)
    command = arguments[0] if arguments else None
    if command == "setup":
        from mcp_mysql import setup
        setup.main(arguments[1:])
    elif command == "grants":
        from mcp_mysql import grants
        grants.main(arguments[1:])
    else:
        from mcp_mysql import server
        server.main(arguments)
