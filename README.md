# MCP Database

Servidores MCP en Python para conectar asistentes de IA (Cursor, Claude, Gemini, etc.) a **MySQL**, **Oracle** y **SQL Server**.

Hay tres servidores independientes en el mismo repo:

| Servidor | Módulo | Entrada MCP |
|----------|--------|-------------|
| MySQL | `mcp_mysql` | `mysql` |
| Oracle | `mcp_oracle` | `oracle` |
| SQL Server | `mcp_sqlserver` | `sqlserver` |

## Requisitos

- Python 3.11+
- Acceso al servidor MySQL, Oracle y/o SQL Server que vayas a usar
- Para SQL Server: driver ODBC instalado (p. ej. **ODBC Driver 18 for SQL Server**)

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

Instala el paquete (incluye los tres servidores):

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

# SQL Server
SQLSERVER_HOST=localhost
SQLSERVER_PORT=1433
SQLSERVER_DATABASE=your_database
SQLSERVER_USER=sa
SQLSERVER_PASSWORD=your_password
SQLSERVER_DRIVER=ODBC Driver 18 for SQL Server
SQLSERVER_TRUST_SERVER_CERTIFICATE=yes
```

## Configurar el cliente MCP

Cada servidor se registra por separado (fusiona sin borrar otros MCPs):

```bash
# MySQL → entrada "mysql" en ~/.cursor/mcp.json
python -m mcp_mysql setup

# Oracle → entrada "oracle"
python -m mcp_oracle setup

# SQL Server → entrada "sqlserver"
python -m mcp_sqlserver setup
```

Opciones comunes:

```bash
python -m mcp_sqlserver setup --client claude
python -m mcp_sqlserver setup --dry-run
python -m mcp_sqlserver setup --print
```

También: `mcp-mysql-setup` / `mcp-oracle-setup` / `mcp-sqlserver-setup`.

Recarga los MCP del cliente y prueba con `test_connection`.

| Cliente | Archivo por defecto |
|---------|---------------------|
| Cursor Windows| `\Users\username\.cursor`  |
| Cursor Linux| `/home/user/.cursor/mcp.json`  |
| Gemini Windows | `C:\users\user_name\.gemini\config\mcp_config.json`  |
| Gemini Linux | `/home/username/.gemini/config/mcp_config.json`  |
| Claude Windows | `./`  |
| Claude Linux | `/home/user/.claude.json`  |


## Tools disponibles

Las mismas tools en los tres servidores:

| Tool | Descripción |
|------|-------------|
| `test_connection` | Verifica la conexión |
| `list_tables` | Lista tablas |
| `describe_table` | Columnas de una tabla |
| `execute_query` | Consultas de solo lectura |


**MySQL:** permite `SELECT`, `SHOW`, `DESCRIBE`, `EXPLAIN`, `WITH` (usa `LIMIT`).

**Oracle:** permite `SELECT` y `WITH` (usa `FETCH FIRST n ROWS ONLY`).

**SQL Server:** permite `SELECT` y `WITH` (inyecta `TOP` en `SELECT` sin límite).

## Notas

- `python -m mcp_mysql` / `python -m mcp_oracle` / `python -m mcp_sqlserver` arrancan el servidor stdio; lo lanza el cliente.
- Las credenciales viven en `.env`, no en el JSON del cliente.
- Oracle usa el driver `oracledb` en modo thin (sin Instant Client, en la mayoría de casos).
- SQL Server usa `pyodbc` + ODBC Driver 17/18.

## Estructura

```
MCP-DATABASE/
├── pyproject.toml
├── .env.example
├── src/
│   ├── mcp_mysql/
│   ├── mcp_oracle/
│   └── mcp_sqlserver/
└── README.md
```

## Prueba

  ![Image Test](/img/test.png)
