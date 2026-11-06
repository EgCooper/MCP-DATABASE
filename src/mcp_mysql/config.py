"""MySQL connection and service settings loaded from environment variables."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from mcp_mysql.errors import ConfigurationError

# Prefer the project .env even if the process cwd differs.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
# No ${VAR} expansion: a password may contain "${".
load_dotenv(_PROJECT_ROOT / ".env", interpolate=False)
load_dotenv(interpolate=False)

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off", ""}


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        raise ConfigurationError(f"{name} must be a positive integer.") from None
    if value < 1:
        raise ConfigurationError(f"{name} must be a positive integer.")
    return value


def _flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ConfigurationError(f"{name} must be true or false.")


def _required(name: str) -> str:
    value = os.getenv(name, "")
    if not value.strip():
        raise ConfigurationError(f"{name} is required.")
    return value


@dataclass(frozen=True)
class MySQLConfig:
    host: str
    port: int
    user: str
    password: str = field(repr=False)
    database: str
    connection_timeout: int = 10
    read_timeout: int = 30
    write_timeout: int = 30
    query_timeout_ms: int = 15000
    company_list_id: int = 3
    ssl_ca: str | None = None
    ssl_verify_identity: bool = False

    def __post_init__(self) -> None:
        for name in ("connection_timeout", "read_timeout", "write_timeout", "query_timeout_ms", "company_list_id"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ConfigurationError(f"{name} must be a positive integer.")
        if self.query_timeout_ms > 4294967295:
            raise ConfigurationError("query_timeout_ms must not exceed 4294967295.")
        if self.ssl_verify_identity and not self.ssl_ca:
            raise ConfigurationError("MYSQL_SSL_VERIFY_IDENTITY requires MYSQL_SSL_CA.")

    @classmethod
    def from_env(cls) -> "MySQLConfig":
        return cls(
            host=os.getenv("MYSQL_HOST", "localhost"),
            port=_positive_int("MYSQL_PORT", 3306),
            # No default account: never fall back to a privileged user such as root.
            user=_required("MYSQL_USER"),
            password=os.getenv("MYSQL_PASSWORD", ""),
            database=os.getenv("MYSQL_DATABASE", ""),
            connection_timeout=_positive_int("MYSQL_CONNECT_TIMEOUT", 10),
            read_timeout=_positive_int("MYSQL_READ_TIMEOUT", 30),
            write_timeout=_positive_int("MYSQL_WRITE_TIMEOUT", 30),
            query_timeout_ms=_positive_int("MYSQL_QUERY_TIMEOUT_MS", 15000),
            company_list_id=_positive_int("OSTICKET_COMPANY_LIST_ID", 3),
            ssl_ca=os.getenv("MYSQL_SSL_CA") or None,
            ssl_verify_identity=_flag("MYSQL_SSL_VERIFY_IDENTITY"),
        )

    def as_dict(self) -> dict:
        options = {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password,
            "database": self.database,
            "connection_timeout": self.connection_timeout,
            "read_timeout": self.read_timeout,
            "write_timeout": self.write_timeout,
        }
        if self.ssl_ca:
            # A CA file turns on certificate verification; identity checks the host name too.
            options.update(ssl_ca=self.ssl_ca, ssl_verify_cert=True,
                           ssl_verify_identity=self.ssl_verify_identity)
        return options


def exploration_tools_enabled() -> bool:
    """Schema exploration tools are for administrators; support agents do not need them."""
    return _flag("MCP_ENABLE_EXPLORATION_TOOLS")


def schema_cache_seconds() -> int:
    return _positive_int("MCP_SCHEMA_CACHE_SECONDS", 300)


def max_db_connections() -> int:
    return _positive_int("MCP_MAX_DB_CONNECTIONS", 8)


MIN_AUTH_TOKEN_LENGTH = 32


def mcp_auth_token() -> str | None:
    """Shared secret HTTP clients must send as ``Authorization: Bearer <token>``."""
    value = os.getenv("MCP_AUTH_TOKEN", "").strip()
    if not value:
        return None
    if len(value) < MIN_AUTH_TOKEN_LENGTH or any(ord(char) <= 32 or ord(char) >= 127 for char in value):
        raise ConfigurationError(
            f"MCP_AUTH_TOKEN must be at least {MIN_AUTH_TOKEN_LENGTH} printable ASCII characters without spaces."
        )
    return value


def mcp_allowed_hosts() -> list[str]:
    """Extra Host headers accepted over HTTP, comma separated (e.g. the container name)."""
    return [host.strip() for host in os.getenv("MCP_ALLOWED_HOSTS", "").split(",") if host.strip()]
