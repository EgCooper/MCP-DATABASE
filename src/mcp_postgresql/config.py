"""PostgreSQL connection settings loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from psycopg.conninfo import make_conninfo

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
# No ${VAR} expansion: a password may contain "${".
load_dotenv(_PROJECT_ROOT / ".env", interpolate=False)
load_dotenv(interpolate=False)


@dataclass(frozen=True)
class PostgreSQLConfig:
    conninfo: str

    @classmethod
    def from_env(cls) -> "PostgreSQLConfig":
        explicit = (
            os.getenv("POSTGRES_DSN", "").strip()
            or os.getenv("POSTGRES_CONNECTION_STRING", "").strip()
            or os.getenv("DATABASE_URL", "").strip()
        )
        if explicit:
            return cls(conninfo=explicit)

        host = os.getenv("POSTGRES_HOST", "localhost")
        port = os.getenv("POSTGRES_PORT", "5432")
        user = os.getenv("POSTGRES_USER", "")
        password = os.getenv("POSTGRES_PASSWORD", "")
        database = os.getenv("POSTGRES_DATABASE", "") or os.getenv("POSTGRES_DB", "")
        sslmode = os.getenv("POSTGRES_SSLMODE", "").strip()

        if not user:
            raise ValueError("POSTGRES_USER is required (or set POSTGRES_DSN)")
        if not database:
            raise ValueError("POSTGRES_DATABASE is required (or set POSTGRES_DSN)")

        params = {
            "host": host,
            "port": port,
            "user": user,
            "password": password,
            "dbname": database,
        }
        if sslmode:
            params["sslmode"] = sslmode
        # make_conninfo quotes the values, so passwords with spaces or quotes work.
        return cls(conninfo=make_conninfo(**params))
