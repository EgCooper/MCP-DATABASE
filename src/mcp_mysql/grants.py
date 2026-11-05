"""Print column-level SELECT grants that mirror the access policy.

The MCP already restricts queries to these columns; granting the database account
only the same columns means a defect in the MCP still cannot read anything else.
"""

from __future__ import annotations

import argparse
import re

from mcp_mysql.access import ALLOWED_TABLE_COLUMNS, INTERNAL_TABLE_COLUMNS

_IDENTIFIER = re.compile(r"^[A-Za-z0-9_]{1,64}$")
_HOST = re.compile(r"^[A-Za-z0-9_.%:-]{1,255}$")


def _identifier(value: str, label: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise SystemExit(f"Invalid {label}: use letters, digits and underscores only.")
    return value


def build_grants(database: str, user: str, host: str) -> list[str]:
    database = _identifier(database, "database")
    user = _identifier(user, "user")
    if not _HOST.fullmatch(host):
        raise SystemExit("Invalid host: use a host name, an IP address or a % pattern.")
    account = f"'{user}'@'{host}'"
    statements = []
    for table, columns in sorted({**ALLOWED_TABLE_COLUMNS, **INTERNAL_TABLE_COLUMNS}.items()):
        listed = ", ".join(f"`{column}`" for column in columns)
        statements.append(f"GRANT SELECT ({listed}) ON `{database}`.`{table}` TO {account};")
    return statements


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m mcp_mysql grants",
        description="Print SQL that grants a read-only account exactly the columns this MCP uses.",
    )
    parser.add_argument("--database", required=True, help="osTicket database name.")
    parser.add_argument("--user", default="mcp_readonly", help="Database account (default: mcp_readonly).")
    parser.add_argument("--host", default="localhost", help="Account host (default: localhost).")
    args = parser.parse_args(argv)

    statements = build_grants(args.database, args.user, args.host)  # validates names first
    print("-- Review, then run as a database administrator. Never grant write privileges.")
    print(f"-- CREATE USER '{args.user}'@'{args.host}' IDENTIFIED BY '<strong password>';")
    for statement in statements:
        print(statement)
    print("-- Columns added to the access policy later need a new grant.")
