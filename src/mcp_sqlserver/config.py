"""SQL Server connection settings loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env")
load_dotenv()


@dataclass(frozen=True)
class SQLServerConfig:
    connection_string: str

    @classmethod
    def from_env(cls) -> "SQLServerConfig":
        explicit = os.getenv("SQLSERVER_CONNECTION_STRING", "").strip()
        if explicit:
            return cls(connection_string=explicit)

        host = os.getenv("SQLSERVER_HOST", "localhost")
        port = os.getenv("SQLSERVER_PORT", "1433")
        database = os.getenv("SQLSERVER_DATABASE", "")
        user = os.getenv("SQLSERVER_USER", "")
        password = os.getenv("SQLSERVER_PASSWORD", "")
        driver = os.getenv(
            "SQLSERVER_DRIVER",
            "ODBC Driver 18 for SQL Server",
        )
        trust = os.getenv("SQLSERVER_TRUST_SERVER_CERTIFICATE", "yes")

        if not database:
            raise ValueError(
                "Set SQLSERVER_DATABASE or SQLSERVER_CONNECTION_STRING"
            )
        if not user:
            raise ValueError("SQLSERVER_USER is required (or use SQLSERVER_CONNECTION_STRING)")

        # SERVER=host,port for non-default ports
        server = host if port in ("", "1433") else f"{host},{port}"
        parts = [
            f"DRIVER={{{driver}}}",
            f"SERVER={server}",
            f"DATABASE={database}",
            f"UID={user}",
            f"PWD={password}",
            f"TrustServerCertificate={trust}",
        ]
        return cls(connection_string=";".join(parts))
