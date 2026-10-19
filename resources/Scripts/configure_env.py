"""Ask for database credentials, write them to .env and test each connection.

The setup scripts run this with the project's venv after installing it:
    python resources/Scripts/configure_env.py mysql oracle
It only asks when run from a terminal; otherwise it exits without changes.
"""

from __future__ import annotations

import getpass
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

ROOT_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT_DIR / ".env"
TEST_TIMEOUT_SECONDS = 25

_KEY_LINE = re.compile(r"^\s*(#\s*)?([A-Za-z_][A-Za-z0-9_]*)\s*=")
_PLAIN_VALUE = re.compile(r"[A-Za-z0-9_.,:/@+-]*")
_PROFILE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    default: str = ""
    secret: bool = False
    required: bool = True
    numeric: bool = False


@dataclass(frozen=True)
class Engine:
    name: str
    prefix: str
    label: str
    fields: tuple[Field, ...]
    # Settings that take priority over the individual fields (full DSN or connection string).
    overrides: tuple[str, ...] = ()
    odbc_keyword: str = ""


_USER = Field("USER", "Usuario (de solo lectura)")
_PASSWORD = Field("PASSWORD", "Contraseña", secret=True, required=False)

ENGINES = {
    "mysql": Engine(
        "mysql", "MYSQL_", "MySQL / osTicket",
        (
            Field("HOST", "Host o IP del servidor"),
            Field("PORT", "Puerto", "3306", numeric=True),
            Field("DATABASE", "Base de datos"),
            _USER,
            _PASSWORD,
        ),
    ),
    "postgresql": Engine(
        "postgresql", "POSTGRES_", "PostgreSQL",
        (
            Field("HOST", "Host o IP del servidor"),
            Field("PORT", "Puerto", "5432", numeric=True),
            Field("DATABASE", "Base de datos"),
            _USER,
            _PASSWORD,
            Field("SSLMODE", "Modo SSL: disable, prefer o require (Enter = por defecto)", required=False),
        ),
        overrides=("POSTGRES_DSN", "POSTGRES_CONNECTION_STRING", "DATABASE_URL"),
    ),
    "sqlserver": Engine(
        "sqlserver", "SQLSERVER_", "SQL Server",
        (
            Field("HOST", "Host o IP del servidor"),
            Field("PORT", "Puerto", "1433", numeric=True),
            Field("DATABASE", "Base de datos"),
            _USER,
            _PASSWORD,
            Field("DRIVER", "Driver ODBC", "ODBC Driver 18 for SQL Server"),
        ),
        overrides=("SQLSERVER_CONNECTION_STRING",),
        odbc_keyword="SQL Server",
    ),
    "informix": Engine(
        "informix", "INFORMIX_", "Informix",
        (
            Field("HOST", "Host o IP del servidor"),
            Field("PORT", "Puerto", "9088", numeric=True),
            Field("SERVER", "Nombre del servidor Informix (INFORMIXSERVER, ej: ol_informix1410)"),
            Field("DATABASE", "Base de datos"),
            _USER,
            _PASSWORD,
            Field("DRIVER", "Driver ODBC", "IBM INFORMIX ODBC DRIVER"),
        ),
        overrides=("INFORMIX_CONNECTION_STRING",),
        odbc_keyword="Informix",
    ),
}

# One Oracle connection; the prefix is ORACLE_ (single) or ORACLE_<NAME>_ (several).
ORACLE_FIELDS = (
    Field("HOST", "Host o IP del servidor"),
    Field("PORT", "Puerto", "1521", numeric=True),
    Field("SID", "Service name o SID"),
    _USER,
    _PASSWORD,
)

_TEST_CODE = (
    "import importlib, sys\n"
    "tools = importlib.import_module('mcp_' + sys.argv[1] + '.tools')\n"
    "print(tools.test_connection(*sys.argv[2:]))\n"
)


def read_env() -> dict[str, str]:
    if not ENV_FILE.exists():
        return {}
    return {k: v for k, v in dotenv_values(ENV_FILE, interpolate=False).items() if v is not None}


def _quote(value: str) -> str:
    # Single quotes stop python-dotenv from expanding ${...} and treating # as a comment.
    if _PLAIN_VALUE.fullmatch(value):
        return value
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def write_env(values: dict[str, str], comment_out: list[str] | tuple[str, ...] = ()) -> None:
    """Set keys in .env in place (uncommenting template lines) and comment out others."""
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    pending = dict(values)
    to_comment = set(comment_out)
    written: set[str] = set()
    result: list[str] = []
    for line in lines:
        match = _KEY_LINE.match(line)
        key = match.group(2) if match else None
        is_comment = bool(match and match.group(1))
        if key in pending:
            result.append(f"{key}={_quote(pending.pop(key))}")
            written.add(key)
        elif key and not is_comment and (key in written or key in to_comment):
            # A later definition would win over the value just written.
            result.append("# " + line)
        else:
            result.append(line)

    for key, value in pending.items():
        group = key.split("_", 1)[0] + "_"
        related = [i for i, line in enumerate(result) if line.lstrip("# ").startswith(group)]
        index = related[-1] + 1 if related else len(result)
        result.insert(index, f"{key}={_quote(value)}")

    # mkstemp creates the file readable only by its owner, and os.replace keeps that.
    fd, tmp_path = tempfile.mkstemp(dir=ENV_FILE.parent, prefix=".env.")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(result) + "\n")
    os.replace(tmp_path, ENV_FILE)


def ask(label: str, current: str = "", *, secret: bool = False, required: bool = True, numeric: bool = False) -> str:
    while True:
        if secret:
            hint = " [Enter = mantener la actual]" if current else ""
            value = getpass.getpass(f"      {label}{hint}: ")
        else:
            hint = f" [{current}]" if current else ""
            value = input(f"      {label}{hint}: ").strip()
        value = value or current
        if required and not value:
            print("      Este dato es obligatorio.")
        elif numeric and value and not value.isdigit():
            print("      Debe ser un número.")
        else:
            return value


def ask_yes_no(question: str, default: bool) -> bool:
    hint = "S/n" if default else "s/N"
    while True:
        answer = input(f"    {question} [{hint}]: ").strip().lower()
        if not answer:
            return default
        if answer in ("s", "si", "sí", "y", "yes"):
            return True
        if answer in ("n", "no"):
            return False


def installed_odbc_drivers(keyword: str) -> list[str]:
    try:
        import pyodbc
    except Exception:
        return []
    drivers = [d for d in pyodbc.drivers() if keyword.lower() in d.lower()]
    # Newest first: "ODBC Driver 18 ..." before "ODBC Driver 17 ...".
    return sorted(drivers, key=lambda d: [int(n) for n in re.findall(r"\d+", d)], reverse=True)


def is_configured(env: dict[str, str], prefix: str, fields: tuple[Field, ...], overrides: tuple[str, ...]) -> bool:
    if any(env.get(key) for key in overrides):
        return True
    return all(env.get(prefix + f.key) for f in fields if f.required)


def describe(env: dict[str, str], prefix: str, overrides: tuple[str, ...]) -> str:
    for key in overrides:
        if env.get(key):
            return f"usa {key}"
    target = env.get(prefix + "DATABASE") or env.get(prefix + "SID") or ""
    return f"{env.get(prefix + 'USER', '')}@{env.get(prefix + 'HOST', '')}:{env.get(prefix + 'PORT', '')}/{target}"


def prompt_fields(fields: tuple[Field, ...], prefix: str, overrides: tuple[str, ...], odbc_keyword: str = "") -> None:
    env = read_env()
    values: dict[str, str] = {}
    for field in fields:
        key = prefix + field.key
        current = env.get(key) or field.default
        if field.key == "DRIVER":
            drivers = installed_odbc_drivers(odbc_keyword)
            if drivers:
                print(f"      Drivers ODBC instalados: {', '.join(drivers)}")
                if current not in drivers:
                    current = drivers[0]
            else:
                print(f"      AVISO: no encontré un driver ODBC de {odbc_keyword} instalado;")
                print("      la conexión va a fallar hasta que lo instales (ver README).")
        value = ask(field.label, current, secret=field.secret, required=field.required, numeric=field.numeric)
        if value or key in env:
            values[key] = value
    active_overrides = [key for key in overrides if env.get(key)]
    if active_overrides:
        print(f"      Se comenta {', '.join(active_overrides)}: tenía prioridad sobre estos datos.")
    write_env(values, comment_out=active_overrides)


def test_connection(engine: str, *args: str) -> tuple[bool, str]:
    """Run the engine's test_connection tool in a fresh process, so it reads the new .env."""
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _TEST_CODE, engine, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TEST_TIMEOUT_SECONDS,
            cwd=ROOT_DIR,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
    except subprocess.TimeoutExpired:
        return False, f"no respondió en {TEST_TIMEOUT_SECONDS} s; revisa host, puerto, VPN o firewall"
    try:
        result = json.loads(proc.stdout)
    except ValueError:
        lines = (proc.stderr or proc.stdout).strip().splitlines()
        return False, lines[-1] if lines else f"el proceso terminó con código {proc.returncode}"
    if result.get("status") == "connected":
        database = result.get("database_name") or result.get("db_name") or ""
        return True, f"conectado a {database}" if database else "conectado"
    error = " ".join(str(result.get("error", result)).split())
    return False, error[:300]


def check(label: str, engine: str, *args: str) -> bool:
    print(f"    Probando la conexión a {label}...")
    ok, message = test_connection(engine, *args)
    print(f"    {'OK' if ok else 'ERROR'}: {message}")
    return ok


def configure_engine(engine: Engine) -> bool:
    print(f"\n  == {engine.label} ==")
    env = read_env()
    if not is_configured(env, engine.prefix, engine.fields, engine.overrides) or ask_yes_no(
        f"Ya está configurado ({describe(env, engine.prefix, engine.overrides)}). ¿Cambiar los datos?", False
    ):
        prompt_fields(engine.fields, engine.prefix, engine.overrides, engine.odbc_keyword)
    while not check(engine.name, engine.name):
        if not ask_yes_no(f"¿Volver a ingresar los datos de {engine.name}?", True):
            return False
        prompt_fields(engine.fields, engine.prefix, engine.overrides, engine.odbc_keyword)
    return True


def _oracle_prefix(name: str) -> str:
    return f"ORACLE_{name.upper()}_" if name else "ORACLE_"


def configure_oracle() -> bool:
    print("\n  == Oracle ==")
    env = read_env()
    names = [n.strip() for n in env.get("ORACLE_CONNECTIONS", "").split(",") if n.strip()]
    profiles = names or [""]
    configured = all(
        is_configured(env, _oracle_prefix(p), ORACLE_FIELDS, (_oracle_prefix(p) + "DSN",)) for p in profiles
    )
    if configured:
        summary = ", ".join(
            f"{p or 'única'}: {describe(env, _oracle_prefix(p), (_oracle_prefix(p) + 'DSN',))}" for p in profiles
        )
        print(f"    Conexiones actuales: {summary}")
    if not configured or ask_yes_no("¿Cambiar los datos de Oracle?", False):
        count = int(ask("¿Cuántas bases Oracle vas a usar?", str(len(names) or 1), numeric=True) or "1")
        if count <= 1:
            profiles = [""]
            prompt_fields(ORACLE_FIELDS, "ORACLE_", ("ORACLE_DSN",))
            write_env({}, comment_out=("ORACLE_CONNECTIONS", "ORACLE_DEFAULT"))
        else:
            profiles = []
            for i in range(count):
                default = names[i] if i < len(names) else f"B{i + 1}"
                while True:
                    name = ask(f"Nombre de la conexión {i + 1} (ej: PROD, QA)", default)
                    if not _PROFILE_NAME.fullmatch(name):
                        print("      Usa letras, números o _ y empieza con una letra.")
                    elif name in profiles:
                        print("      Ese nombre ya está usado.")
                    else:
                        break
                profiles.append(name)
                print(f"    Conexión {name}:")
                prefix = _oracle_prefix(name)
                prompt_fields(ORACLE_FIELDS, prefix, (prefix + "DSN",))
            current_default = read_env().get("ORACLE_DEFAULT", "")
            while True:
                default_name = ask(
                    "Conexión por defecto", current_default if current_default in profiles else profiles[0]
                )
                if default_name in profiles:
                    break
                print(f"      Elige una de: {', '.join(profiles)}")
            write_env({"ORACLE_CONNECTIONS": ",".join(profiles), "ORACLE_DEFAULT": default_name})

    all_ok = True
    for profile in profiles:
        label = f"oracle ({profile})" if profile else "oracle"
        while not check(label, "oracle", profile):
            if not ask_yes_no(f"¿Volver a ingresar los datos de {label}?", True):
                all_ok = False
                break
            prefix = _oracle_prefix(profile)
            prompt_fields(ORACLE_FIELDS, prefix, (prefix + "DSN",))
    return all_ok


def main(argv: list[str]) -> int:
    unknown = [name for name in argv if name not in ENGINES and name != "oracle"]
    if unknown:
        print(f"Motores desconocidos: {', '.join(unknown)}", file=sys.stderr)
        return 2
    if not sys.stdin.isatty():
        print("    Sin terminal interactiva: no se piden credenciales; completa .env a mano.")
        return 0

    print("    Los datos se guardan en .env, solo en este equipo. Usa un usuario de solo lectura.")
    print("    Enter mantiene el valor entre corchetes.")
    failed = []
    try:
        for name in argv:
            ok = configure_oracle() if name == "oracle" else configure_engine(ENGINES[name])
            if not ok:
                failed.append(name)
    except (KeyboardInterrupt, EOFError):
        print("\n    Cancelado. Lo que ya se guardó en .env se mantiene.")
        return 130
    if failed:
        print(f"\n    Sin conexión: {', '.join(failed)}. Los datos quedaron guardados en .env.")
        print("    Si son correctos, revisa la VPN o el firewall; si no, vuelve a ejecutar el setup.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
