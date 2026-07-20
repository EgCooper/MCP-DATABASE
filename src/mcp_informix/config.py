"""Informix connection settings loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env")
load_dotenv()


@dataclass(frozen=True)
class InformixConfig:
    connection_string: str

    @classmethod
    def from_env(cls) -> "InformixConfig":
        explicit = os.getenv("INFORMIX_CONNECTION_STRING", "").strip()
        if explicit:
            return cls(connection_string=explicit)

        host = os.getenv("INFORMIX_HOST", "localhost")
        port = os.getenv("INFORMIX_PORT", "9088")
        server = os.getenv("INFORMIX_SERVER", "")  # INFORMIXSERVER / ol_xxx
        database = os.getenv("INFORMIX_DATABASE", "")
        user = os.getenv("INFORMIX_USER", "")
        password = os.getenv("INFORMIX_PASSWORD", "")
        protocol = os.getenv("INFORMIX_PROTOCOL", "onsoctcp")
        driver = os.getenv(
            "INFORMIX_DRIVER",
            "IBM INFORMIX ODBC DRIVER",
        )

        if not server:
            raise ValueError(
                "Set INFORMIX_SERVER (INFORMIXSERVER name) or INFORMIX_CONNECTION_STRING"
            )
        if not database:
            raise ValueError(
                "Set INFORMIX_DATABASE or INFORMIX_CONNECTION_STRING"
            )
        if not user:
            raise ValueError(
                "INFORMIX_USER is required (or use INFORMIX_CONNECTION_STRING)"
            )

        parts = [
            f"DRIVER={{{driver}}}",
            f"HOST={host}",
            f"SERVER={server}",
            f"SERVICE={port}",
            f"PROTOCOL={protocol}",
            f"DATABASE={database}",
            f"UID={user}",
            f"PWD={password}",
        ]
        return cls(connection_string=";".join(parts))
