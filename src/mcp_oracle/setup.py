"""Install / print MCP client config for the Oracle server."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# name of the MCP server    
SERVER_NAME = "oracle"

# function to return the project root
def project_root() -> Path:
    """Return the repository root (parent of src/)."""
    return Path(__file__).resolve().parents[2]

# function to resolve the Python interpreter
def resolve_python(root: Path) -> Path:
    """Prefer the project virtualenv interpreter when present."""
    candidates = (
        root / ".venv" / "Scripts" / "python.exe",
        root / ".venv" / "bin" / "python",
        root / "venv" / "Scripts" / "python.exe",
        root / "venv" / "bin" / "python",
    )
    for path in candidates:
        if path.exists():
            return path
    return Path(sys.executable)

# function to build the oracle MCP server entry
def oracle_server_entry(root: Path, python: Path) -> dict[str, Any]:
    """Build the oracle MCP server entry (no credentials)."""
    return {
        "command": str(python),
        "args": ["-m", "mcp_oracle"],
        "cwd": str(root),
    }

# function to build a standalone mcpServers snippet
def build_snippet(root: Path, python: Path) -> dict[str, Any]:
    """Build a standalone mcpServers snippet."""
    return {"mcpServers": {SERVER_NAME: oracle_server_entry(root, python)}}

# function to return the default config file path
def default_config_path(client: str) -> Path:
    """Resolve the default config file for a known MCP client."""
    home = Path.home()
    if client == "cursor":
        return home / ".cursor" / "mcp.json"
    if client == "claude":
        if sys.platform == "win32":
            appdata = os.environ.get("APPDATA")
            if not appdata:
                raise SystemExit(
                    "APPDATA is not set; cannot locate Claude Desktop config."
                )
            return Path(appdata) / "Claude" / "claude_desktop_config.json"
        if sys.platform == "darwin":
            return (
                home
                / "Library"
                / "Application Support"
                / "Claude"
                / "claude_desktop_config.json"
            )
        return home / ".config" / "Claude" / "claude_desktop_config.json"
    raise SystemExit(f"Unsupported client: {client}")

# function to load the config file
def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"mcpServers": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"Config root must be an object: {path}")
    servers = data.get("mcpServers")
    if servers is None:
        data["mcpServers"] = {}
    elif not isinstance(servers, dict):
        raise SystemExit(f'"mcpServers" must be an object in {path}')
    return data

# function to merge the oracle MCP server entry into the config
def merge_server(config: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    """Insert/replace the oracle server without touching other servers."""
    merged = dict(config)
    servers = dict(merged.get("mcpServers") or {})
    servers[SERVER_NAME] = entry
    merged["mcpServers"] = servers
    return merged

# function to write the config file
def write_config(path: Path, config: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

# function to collect warnings
def _collect_warnings(root: Path) -> list[str]:
    warnings: list[str] = []

    if not (root / ".env").exists():
        warnings.append(
            "Missing .env - copy .env.example to .env and set ORACLE_* credentials."
        )
    else:
        text = (root / ".env").read_text(encoding="utf-8", errors="ignore")
        has_oracle = any(
            line.strip().startswith(
                ("ORACLE_USER=", "ORACLE_DSN=", "ORACLE_SERVICE=")
            )
            for line in text.splitlines()
        )
        if not has_oracle:
            warnings.append(
                "No ORACLE_* variables found in .env - add Oracle credentials before connecting."
            )

    has_venv = any(
        (root / rel).exists()
        for rel in (
            ".venv/Scripts/python.exe",
            ".venv/bin/python",
            "venv/Scripts/python.exe",
            "venv/bin/python",
        )
    )
    if not has_venv:
        warnings.append(
            "No project virtualenv found — create .venv and run: pip install -e ."
        )

    return warnings

# function to parse the arguments
def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m mcp_oracle setup",
        description=(
            "Install the oracle MCP server into a client config, "
            "or print the JSON snippet."
        ),
    )
    parser.add_argument(
        "--client",
        choices=("cursor", "claude"),
        default="cursor",
        help="Target MCP client config (default: cursor).",
    )
    parser.add_argument(
        "--path",
        type=Path,
        help="Custom config file path (overrides --client).",
    )
    parser.add_argument(
        "--print",
        dest="print_only",
        action="store_true",
        help="Only print the JSON snippet; do not write any file.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the merged config that would be written, without saving.",
    )
    return parser.parse_args(argv)

# function to main function to run the MCP server
def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    root = project_root()
    python = resolve_python(root)
    entry = oracle_server_entry(root, python)

    for warning in _collect_warnings(root):
        print(f"Warning: {warning}", file=sys.stderr)

    if args.print_only:
        print(json.dumps(build_snippet(root, python), indent=2))
        print(
            "\nCredentials stay in .env. "
            "Use setup without --print to install automatically.",
            file=sys.stderr,
        )
        return

    target = args.path.expanduser() if args.path else default_config_path(args.client)
    had_file = target.exists()
    existing = load_config(target)
    merged = merge_server(existing, entry)
    changed = existing.get("mcpServers", {}).get(SERVER_NAME) != entry

    if args.dry_run:
        print(f"Would write: {target}\n")
        print(json.dumps(merged, indent=2))
        return

    write_config(target, merged)
    if not had_file:
        action = "Created"
    elif changed:
        action = "Updated"
    else:
        action = "Already up to date in"
    other = [name for name in merged["mcpServers"] if name != SERVER_NAME]
    print(f"{action} {SERVER_NAME} entry: {target}")
    if other:
        print(f"Preserved other servers: {', '.join(sorted(other))}")
    print("Reload/restart MCP in your client, then try test_connection.")
    print("Credentials stay in .env (not in the client JSON).")


if __name__ == "__main__":
    main()
