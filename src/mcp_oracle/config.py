"""Oracle connection settings loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env")
load_dotenv()


@dataclass(frozen=True)
class OracleConfig:
    user: str
    password: str
    dsn: str

    @classmethod
    def from_env(cls) -> "OracleConfig":
        user = os.getenv("ORACLE_USER", "")
        password = os.getenv("ORACLE_PASSWORD", "")
        dsn = os.getenv("ORACLE_DSN", "").strip()

        if not dsn:
            host = os.getenv("ORACLE_HOST", "localhost")
            port = os.getenv("ORACLE_PORT", "1521")
            service = os.getenv("ORACLE_SERVICE", "")
            if not service:
                raise ValueError(
                    "Set ORACLE_DSN or ORACLE_HOST + ORACLE_PORT + ORACLE_SERVICE"
                )
            dsn = f"{host}:{port}/{service}"

        return cls(user=user, password=password, dsn=dsn)

    def as_connect_kwargs(self) -> dict:
        return {
            "user": self.user,
            "password": self.password,
            "dsn": self.dsn,
        }
