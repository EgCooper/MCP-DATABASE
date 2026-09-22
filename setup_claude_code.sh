set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"

if [ ! -x "$PYTHON_BIN" ]; then
    echo "==> Creando entorno virtual (.venv)..."
    python3 -m venv .venv
fi

echo "==> Instalando dependencias..."
"$SCRIPT_DIR/.venv/bin/pip" install --upgrade pip >/dev/null
"$SCRIPT_DIR/.venv/bin/pip" install -e . >/dev/null

if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo "==> No existe .env. Copiando .env.example -> .env"
    cp .env.example .env
fi

echo
echo "==> Entorno listo. Antes de continuar:"
echo "    1. Edita $SCRIPT_DIR/.env e inserta las credenciales de las bases que vayas a usar."
echo "    2. Registra cada MCP con:"
echo "         claude mcp add <nombre> -- $PYTHON_BIN -m <modulo>"
echo "       (ej: claude mcp add mysql -- $PYTHON_BIN -m mcp_mysql)"
