"""Oracle connection settings: single legacy profile or named multi-profiles."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env")
load_dotenv()

_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
LEGACY_NAME = "default"


@dataclass(frozen=True)
class OracleConfig:
    name: str
    user: str
    password: str
    dsn: str

    def as_connect_kwargs(self) -> dict:
        return {
            "user": self.user,
            "password": self.password,
            "dsn": self.dsn,
        }

    @classmethod
    def from_env(cls, connection: str | None = None) -> "OracleConfig":
        """Back-compat: resolve default or named profile."""
        return get_config(connection)


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def _build_dsn(
    *,
    dsn: str,
    host: str,
    port: str,
    sid_or_service: str,
) -> str:
    if dsn.strip():
        return dsn.strip()
    if not sid_or_service.strip():
        raise ValueError(
            "Set DSN or HOST + PORT + SID/SERVICE for this Oracle profile"
        )
    return f"{host}:{port}/{sid_or_service.strip()}"


def _load_prefixed_profile(name: str) -> OracleConfig:
    """Load ORACLE_{NAME}_USER / _PASSWORD / _DSN / ..."""
    prefix = f"ORACLE_{name.upper()}_"
    user = _env(f"{prefix}USER")
    password = _env(f"{prefix}PASSWORD")
    dsn = _build_dsn(
        dsn=_env(f"{prefix}DSN"),
        host=_env(f"{prefix}HOST", "localhost"),
        port=_env(f"{prefix}PORT", "1521"),
        sid_or_service=_env(f"{prefix}SID") or _env(f"{prefix}SERVICE"),
    )
    if not user:
        raise ValueError(f"Missing {prefix}USER for connection '{name}'")
    return OracleConfig(name=name, user=user, password=password, dsn=dsn)


def _load_legacy_profile() -> OracleConfig:
    """Load classic ORACLE_USER / ORACLE_PASSWORD / ORACLE_DSN (single DB)."""
    user = _env("ORACLE_USER")
    password = _env("ORACLE_PASSWORD")
    dsn = _build_dsn(
        dsn=_env("ORACLE_DSN"),
        host=_env("ORACLE_HOST", "localhost"),
        port=_env("ORACLE_PORT", "1521"),
        sid_or_service=_env("ORACLE_SID") or _env("ORACLE_SERVICE"),
    )
    if not user:
        raise ValueError(
            "Set ORACLE_USER (legacy) or ORACLE_CONNECTIONS with "
            "ORACLE_<NAME>_USER profiles"
        )
    return OracleConfig(name=LEGACY_NAME, user=user, password=password, dsn=dsn)


def list_connection_names() -> list[str]:
    """Return configured connection profile names (order preserved)."""
    raw = _env("ORACLE_CONNECTIONS").strip()
    if raw:
        names = [part.strip() for part in raw.split(",") if part.strip()]
        for name in names:
            if not _NAME_RE.fullmatch(name):
                raise ValueError(
                    f"Invalid connection name '{name}'. "
                    "Use letters, numbers, underscore; start with a letter."
                )
        if not names:
            raise ValueError("ORACLE_CONNECTIONS is empty")
        return names

    if _env("ORACLE_USER") or _env("ORACLE_DSN"):
        return [LEGACY_NAME]
    return []


def get_default_connection_name() -> str:
    """Return default profile name."""
    names = list_connection_names()
    if not names:
        raise ValueError(
            "No Oracle connections configured. Set ORACLE_CONNECTIONS "
            "or legacy ORACLE_USER / ORACLE_DSN."
        )
    configured = _env("ORACLE_DEFAULT").strip()
    if configured:
        if configured not in names:
            raise ValueError(
                f"ORACLE_DEFAULT='{configured}' is not in "
                f"ORACLE_CONNECTIONS={names}"
            )
        return configured
    return names[0]


def resolve_connection_name(connection: str | None = None) -> str:
    """Resolve empty/None to default; validate named profiles."""
    names = list_connection_names()
    if not names:
        raise ValueError(
            "No Oracle connections configured. Set ORACLE_CONNECTIONS "
            "or legacy ORACLE_USER / ORACLE_DSN."
        )
    name = (connection or "").strip()
    if not name:
        return get_default_connection_name()
    if name not in names:
        raise ValueError(
            f"Unknown connection '{name}'. Available: {', '.join(names)}"
        )
    return name


def get_config(connection: str | None = None) -> OracleConfig:
    """Load OracleConfig for a profile (or default / legacy)."""
    name = resolve_connection_name(connection)
    if not _env("ORACLE_CONNECTIONS").strip():
        return _load_legacy_profile()
    return _load_prefixed_profile(name)


def connection_summaries() -> list[dict]:
    """Metadata for list_connections (no passwords)."""
    default = get_default_connection_name()
    summaries: list[dict] = []
    for name in list_connection_names():
        cfg = get_config(name)
        summaries.append(
            {
                "name": name,
                "user": cfg.user,
                "dsn": cfg.dsn,
                "is_default": name == default,
            }
        )
    return summaries
