"""Generate MCP client config JSON for this installation."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def project_root() -> Path:
    """Return the repository root (parent of src/)."""
    return Path(__file__).resolve().parents[2]


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


def build_config(root: Path, python: Path) -> dict:
    """Build a client-agnostic mcpServers snippet (no credentials)."""
    return {
        "mcpServers": {
            "mysql": {
                "command": str(python),
                "args": ["-m", "mcp_mysql"],
                "cwd": str(root),
            }
        }
    }


def _collect_warnings(root: Path) -> list[str]:
    warnings: list[str] = []

    if not (root / ".env").exists():
        if (root / ".env.example").exists():
            warnings.append(
                "Missing .env — copy .env.example to .env and edit your MySQL credentials."
            )
        else:
            warnings.append(
                "Missing .env — create one with MYSQL_HOST, MYSQL_PORT, MYSQL_USER, "
                "MYSQL_PASSWORD, and MYSQL_DATABASE."
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


def main() -> None:
    root = project_root()
    python = resolve_python(root)
    config = build_config(root, python)

    for warning in _collect_warnings(root):
        print(f"Warning: {warning}", file=sys.stderr)

    print(
        "Paste this into your MCP client config "
        "(Cursor mcp.json, Claude Desktop, Gemini, etc.):\n"
    )
    print(json.dumps(config, indent=2))
    print(
        "\nCredentials stay in .env (not in this JSON). "
        "If you already have other servers, merge only the \"mysql\" entry."
    )


if __name__ == "__main__":
    main()
