#!/usr/bin/env bash
set -euo pipefail

# The script lives in resources/Scripts; everything runs from the repo root.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT_DIR"

# uv installs Python and the venv without sudo and without touching the system Python.
UV_VERSION="0.12.24"
PYTHON_VERSION="3.13"
UV_INSTALL_DIR="${UV_INSTALL_DIR:-$HOME/.local/bin}"
PYTHON_BIN="$ROOT_DIR/.venv/bin/python"

if command -v uv >/dev/null 2>&1; then
    UV_BIN="$(command -v uv)"
elif [ -x "$UV_INSTALL_DIR/uv" ]; then
    UV_BIN="$UV_INSTALL_DIR/uv"
else
    echo "==> Instalando uv $UV_VERSION en $UV_INSTALL_DIR..."
    UV_INSTALLER_URL="https://astral.sh/uv/$UV_VERSION/install.sh"
    if command -v curl >/dev/null 2>&1; then
        curl -LsSf "$UV_INSTALLER_URL" | env UV_INSTALL_DIR="$UV_INSTALL_DIR" sh
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- "$UV_INSTALLER_URL" | env UV_INSTALL_DIR="$UV_INSTALL_DIR" sh
    else
        echo "ERROR: se necesita curl o wget para descargar uv." >&2
        exit 1
    fi
    UV_BIN="$UV_INSTALL_DIR/uv"
fi

echo "==> Instalando Python $PYTHON_VERSION (si falta)..."
"$UV_BIN" python install "$PYTHON_VERSION"

# A .venv from an older setup points to the system Python; rebuild it with uv's Python.
if [ ! -x "$PYTHON_BIN" ] || ! grep -q '^uv = ' "$ROOT_DIR/.venv/pyvenv.cfg" 2>/dev/null; then
    echo "==> Creando entorno virtual (.venv) con Python $PYTHON_VERSION..."
    "$UV_BIN" venv --clear --managed-python --python "$PYTHON_VERSION" .venv
fi

echo "==> Instalando dependencias..."
"$UV_BIN" pip install --python "$PYTHON_BIN" -e .

if [ ! -f "$ROOT_DIR/.env" ]; then
    echo "==> No existe .env. Copiando .env.example -> .env"
    cp .env.example .env
fi

echo
echo "==> Entorno listo. Antes de continuar:"
echo "    1. Edita $ROOT_DIR/.env e inserta las credenciales de las bases que vayas a usar."
echo "    2. Registra cada MCP con:"
echo "         claude mcp add <nombre> -- $PYTHON_BIN -m <modulo>"
echo "       (ej: claude mcp add mysql -- $PYTHON_BIN -m mcp_mysql)"
