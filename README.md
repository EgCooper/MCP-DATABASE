# MCP Database

Servidores MCP en Python para conectar asistentes de IA (Cursor, Claude, Gemini, etc.) a **MySQL** y **Oracle**.

Hay dos servidores independientes en el mismo repo:

| Servidor | Módulo | Entrada MCP |
|----------|--------|-------------|
| MySQL | `mcp_mysql` | `mysql` |
| Oracle | `mcp_oracle` | `oracle` |

## Requisitos

- Python 3.11+
- Acceso al servidor MySQL y/o Oracle que vayas a usar

## Instalación

```bash
git clone <url-del-repo>
cd MCP-DATABASE
python -m venv .venv
```

Activa el entorno virtual:

```bash
# Windows (PowerShell)
.\.venv\Scripts\Activate.ps1

# Linux / macOS
source .venv/bin/activate
```

Instala el paquete (incluye ambos servidores):

```bash
pip install -e .
```

Crea tu archivo de credenciales (no se sube a git):

```bash
# Windows
Copy-Item .env.example .env

# Linux / macOS
cp .env.example .env
```

Edita `.env` con las bases que uses:

```env
# MySQL
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your_password
MYSQL_DATABASE=your_database

# Oracle (DSN o HOST+PORT+SERVICE)
ORACLE_USER=your_user
ORACLE_PASSWORD=your_password
ORACLE_HOST=localhost
ORACLE_PORT=1521
ORACLE_SERVICE=ORCL
# ORACLE_DSN=localhost:1521/ORCL
```

## Configurar el cliente MCP

Cada servidor se registra por separado (fusiona sin borrar otros MCPs):

```bash
# MySQL → entrada "mysql" en ~/.cursor/mcp.json
python -m mcp_mysql setup

# Oracle → entrada "oracle"
python -m mcp_oracle setup
```

Opciones comunes:

```bash
python -m mcp_oracle setup --client claude
python -m mcp_oracle setup --dry-run
python -m mcp_oracle setup --print
```

También: `mcp-mysql-setup` / `mcp-oracle-setup`.

Recarga los MCP del cliente y prueba con `test_connection`.

| Cliente | Archivo por defecto |
|---------|---------------------|
| Cursor | `~/.cursor/mcp.json` (Windows) |
| Claude Desktop | `%APPDATA%\Claude\claude_desktop_config.json` (Windows) |
| Gemini | `C:\Users\User_Name\.gemini\config` (Windows) |

## Tools disponibles

Las mismas tools en ambos servidores:

| Tool | Descripción |
|------|-------------|
| `test_connection` | Verifica la conexión |
| `list_tables` | Lista tablas |
| `describe_table` | Columnas de una tabla |
| `execute_query` | Consultas de solo lectura |


**MySQL:** permite `SELECT`, `SHOW`, `DESCRIBE`, `EXPLAIN`, `WITH` (usa `LIMIT`).

**Oracle:** permite `SELECT` y `WITH` (usa `FETCH FIRST n ROWS ONLY`).

## Notas

- `python -m mcp_mysql` / `python -m mcp_oracle` arrancan el servidor stdio; lo lanza el cliente.
- Las credenciales viven en `.env`, no en el JSON del cliente.
- Oracle usa el driver `oracledb` en modo thin (sin Instant Client, en la mayoría de casos).

## Estructura

```
MCP-DATABASE/
├── pyproject.toml
├── .env.example
├── src/
│   ├── mcp_mysql/
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── tools.py
│   │   ├── setup.py
│   │   └── server.py
│   └── mcp_oracle/
│       ├── config.py
│       ├── db.py
│       ├── tools.py
│       ├── setup.py
│       └── server.py
└── README.md
```

## Prueba

  ![Image Test](/img/test.png)
