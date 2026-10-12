#!/usr/bin/env bash
set -euo pipefail

# The script lives in resources/Scripts; everything runs from the repo root.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="$ROOT_DIR/.venv/bin/python"

if [ ! -x "$PYTHON_BIN" ]; then
    echo "==> Creando entorno virtual (.venv)..."
    python3 -m venv .venv
fi

echo "==> Instalando dependencias..."
"$PYTHON_BIN" -m pip install --upgrade pip >/dev/null
"$PYTHON_BIN" -m pip install -e . >/dev/null

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
