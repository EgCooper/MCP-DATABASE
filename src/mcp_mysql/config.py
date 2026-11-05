# read all MySQL connection settings from environment variables, with defaults
"""MySQL connection settings loaded from environment variables."""

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


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        raise ConfigurationError(f"{name} must be a positive integer.") from None
    if value < 1:
        raise ConfigurationError(f"{name} must be a positive integer.")
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

    def __post_init__(self) -> None:
        for name in ("connection_timeout", "read_timeout", "write_timeout", "query_timeout_ms", "company_list_id"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ConfigurationError(f"{name} must be a positive integer.")
        if self.query_timeout_ms > 4294967295:
            raise ConfigurationError("query_timeout_ms must not exceed 4294967295.")

    @classmethod
    def from_env(cls) -> "MySQLConfig":
        return cls(
            host=os.getenv("MYSQL_HOST", "localhost"),
            port=_positive_int("MYSQL_PORT", 3306),
            user=os.getenv("MYSQL_USER", "root"),
            password=os.getenv("MYSQL_PASSWORD", ""),
            database=os.getenv("MYSQL_DATABASE", ""),
            connection_timeout=_positive_int("MYSQL_CONNECT_TIMEOUT", 10),
            read_timeout=_positive_int("MYSQL_READ_TIMEOUT", 30),
            write_timeout=_positive_int("MYSQL_WRITE_TIMEOUT", 30),
            query_timeout_ms=_positive_int("MYSQL_QUERY_TIMEOUT_MS", 15000),
            company_list_id=_positive_int("OSTICKET_COMPANY_LIST_ID", 3),
        )

    def as_dict(self) -> dict:
        return {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password,
            "database": self.database,
            "connection_timeout": self.connection_timeout,
            "read_timeout": self.read_timeout,
            "write_timeout": self.write_timeout,
        }
