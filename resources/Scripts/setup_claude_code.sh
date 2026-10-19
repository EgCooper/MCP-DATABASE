#!/usr/bin/env bash
set -euo pipefail

# Usage: setup_claude_code.sh [motores...]   e.g. "mysql oracle", "1,4", "todos" or "ninguno".
# Without arguments it asks which engines to register in Claude Code.

# The script lives in resources/Scripts; everything runs from the repo root.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT_DIR"

# uv installs Python and the venv without sudo and without touching the system Python.
UV_VERSION="0.12.24"
PYTHON_VERSION="3.13"
UV_INSTALL_DIR="${UV_INSTALL_DIR:-$HOME/.local/bin}"
PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
ENV_FILE="$ROOT_DIR/.env"
ALL_ENGINES="mysql oracle postgresql sqlserver informix"

engine_prefix() {
    case "$1" in
        mysql) echo "MYSQL" ;;
        oracle) echo "ORACLE" ;;
        postgresql) echo "POSTGRES" ;;
        sqlserver) echo "SQLSERVER" ;;
        informix) echo "INFORMIX" ;;
    esac
}

engine_label() {
    case "$1" in
        mysql) echo "MySQL / osTicket" ;;
        oracle) echo "Oracle" ;;
        postgresql) echo "PostgreSQL" ;;
        sqlserver) echo "SQL Server (requiere ODBC Driver 18 for SQL Server)" ;;
        informix) echo "Informix (requiere IBM Informix Client SDK)" ;;
    esac
}

# Engines with at least one uncommented value in .env.
configured_engines() {
    local engine found=""
    for engine in $ALL_ENGINES; do
        if grep -qE "^$(engine_prefix "$engine")_[A-Z0-9_]+=." "$ENV_FILE" 2>/dev/null; then
            found="$found $engine"
        fi
    done
    echo "${found# }"
}

# Turns "1,4", "mysql sqlserver", "todos" or "ninguno" into engine names; fails on an unknown option.
parse_engines() {
    local token candidate engine index selected=""
    for token in $(echo "$*" | tr ',' ' ' | tr '[:upper:]' '[:lower:]'); do
        case "$token" in
            todos|all) echo "$ALL_ENGINES"; return 0 ;;
            ninguno|none|no|n) echo ""; return 0 ;;
        esac
        engine=""
        index=1
        for candidate in $ALL_ENGINES; do
            if [ "$token" = "$index" ] || [ "$token" = "$candidate" ]; then
                engine="$candidate"
            fi
            index=$((index + 1))
        done
        if [ -z "$engine" ]; then
            echo "    Opcion no valida: $token" >&2
            return 1
        fi
        case " $selected " in
            *" $engine "*) ;;
            *) selected="$selected $engine" ;;
        esac
    done
    echo "${selected# }"
}

# Ask first, so the rest of the setup runs unattended.
SELECTED=""
if [ "$#" -gt 0 ]; then
    SELECTED="$(parse_engines "$@")"
elif [ -t 0 ]; then
    DEFAULT_ENGINES="$(configured_engines)"
    DEFAULT_ENGINES="${DEFAULT_ENGINES:-mysql}"
    echo "==> Que motores vas a usar? Despues de instalar te pedire sus datos de conexion y los registrare en Claude Code."
    index=1
    for engine in $ALL_ENGINES; do
        printf '    %d) %-11s %s\n' "$index" "$engine" "$(engine_label "$engine")"
        index=$((index + 1))
    done
    echo "    Escribe numeros o nombres separados por coma (ej: 1,4), 'todos' o 'ninguno'."
    while true; do
        read -r -p "    [Enter = $DEFAULT_ENGINES]: " answer
        if [ -z "$answer" ]; then
            SELECTED="$DEFAULT_ENGINES"
            break
        fi
        if SELECTED="$(parse_engines "$answer")"; then
            break
        fi
    done
    echo
fi

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

if [ ! -f "$ENV_FILE" ]; then
    echo "==> No existe .env. Copiando .env.example -> .env"
    cp .env.example .env
fi

# Asks for the credentials of each chosen engine, writes them to .env and tests the connection.
if [ -n "$SELECTED" ]; then
    echo
    echo "==> Datos de conexion de: $SELECTED"
    "$PYTHON_BIN" "$SCRIPT_DIR/configure_env.py" $SELECTED
    echo
fi

if command -v claude >/dev/null 2>&1; then
    CLAUDE_BIN="$(command -v claude)"
elif [ -x "$HOME/.local/bin/claude" ]; then
    CLAUDE_BIN="$HOME/.local/bin/claude"
else
    CLAUDE_BIN=""
fi

register_engine() {
    local engine="$1" module="mcp_$1" output scope status replaced=""
    # Fail here instead of as "Connection closed" inside Claude Code.
    if ! output="$("$PYTHON_BIN" -c "import $module.server" 2>&1)"; then
        echo "    ERROR $engine: Python no pudo cargar $module: $(echo "$output" | tail -n 1)"
        case "$engine" in
            sqlserver|informix)
                echo "          Instala unixODBC (Fedora: sudo dnf install unixODBC, Ubuntu: sudo apt install unixodbc)"
                echo "          y el driver ODBC del motor; despues vuelve a ejecutar este setup."
                ;;
        esac
        return 1
    fi
    # Drop older registrations: a stale path, or a per-folder one that would hide the user-wide one.
    for scope in user local; do
        if "$CLAUDE_BIN" mcp remove --scope "$scope" "$engine" >/dev/null 2>&1; then
            replaced=" (reemplaza el registro anterior)"
        fi
    done
    if ! output="$("$CLAUDE_BIN" mcp add --scope user "$engine" -- "$PYTHON_BIN" -m "$module" 2>&1)"; then
        echo "    ERROR $engine: claude mcp add fallo: $output"
        return 1
    fi
    # "claude mcp get" starts the server once; it does not need the database credentials.
    status="$("$CLAUDE_BIN" mcp get "$engine" 2>&1 | grep -m 1 'Status:' || true)"
    case "$status" in
        *Failed*|"")
            echo "    AVISO $engine: registrado, pero Claude Code no pudo iniciarlo. ${status# }"
            return 1
            ;;
        *Connected*)
            echo "    OK    $engine: registrado y conectado$replaced"
            ;;
        *)
            echo "    AVISO $engine: registrado, estado: ${status# }"
            ;;
    esac
}

REGISTERED=""
FAILED=""
if [ -n "$SELECTED" ] && [ -n "$CLAUDE_BIN" ]; then
    echo "==> Registrando los MCP en Claude Code (disponibles en todas tus carpetas)..."
    for engine in $SELECTED; do
        if register_engine "$engine"; then
            REGISTERED="$REGISTERED $engine"
        else
            FAILED="$FAILED $engine"
        fi
    done
    REGISTERED="${REGISTERED# }"
    FAILED="${FAILED# }"
fi

CONFIGURED=" $(configured_engines) "
MISSING=""
for engine in $SELECTED; do
    case "$CONFIGURED" in
        *" $engine "*) ;;
        *) MISSING="$MISSING $engine" ;;
    esac
done
MISSING="${MISSING# }"

echo
echo "==> Entorno listo."
if [ -z "$SELECTED" ]; then
    echo "    - Completa en $ENV_FILE (quitando el # de cada linea) los datos de los motores que vayas a usar."
elif [ -n "$MISSING" ]; then
    echo "    - Faltan los datos de conexion de: $MISSING. Vuelve a ejecutar este setup para ingresarlos."
fi
if [ -n "$REGISTERED" ]; then
    echo "    - Abre Claude Code (si ya estaba abierto, reinicialo) y pide: \"prueba la conexion a ${REGISTERED%% *}\"."
elif [ -z "$SELECTED" ]; then
    echo "    - Registra cada MCP volviendo a ejecutar este setup, o desde una terminal (no dentro de Claude) con:"
    echo "        claude mcp add --scope user <nombre> -- \"$PYTHON_BIN\" -m mcp_<nombre>"
    echo "      (ej: claude mcp add --scope user mysql -- \"$PYTHON_BIN\" -m mcp_mysql)"
elif [ -z "$CLAUDE_BIN" ]; then
    echo "    - No se encontro Claude Code (comando claude). Instalalo y vuelve a ejecutar este setup,"
    echo "      o registra cada MCP desde una terminal (no dentro de Claude) con:"
    for engine in $SELECTED; do
        echo "        claude mcp add --scope user $engine -- \"$PYTHON_BIN\" -m mcp_$engine"
    done
else
    echo "    - Corrige lo indicado arriba y vuelve a ejecutar este setup."
fi
echo "    - Para cambiar credenciales mas adelante, vuelve a ejecutar este setup."
echo "    - Para revisar el estado de los MCP: claude mcp list"

if [ -n "$FAILED" ]; then
    echo
    echo "ERROR: no se pudieron registrar: $FAILED (ver mensajes arriba)." >&2
    exit 1
fi
