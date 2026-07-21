# MCP Database

Servidores MCP en Python para conectar asistentes de IA (Cursor, Claude, Gemini, etc.) a **MySQL**, **Oracle**, **SQL Server** e **Informix**.

Hay cuatro servidores independientes en el mismo repo:

| Servidor | Módulo | Entrada MCP | Driver extra en la PC |
|----------|--------|-------------|------------------------|
| MySQL | `mcp_mysql` | `mysql` | No (pip alcanza) |
| Oracle | `mcp_oracle` | `oracle` | No (pip / thin mode) |
| SQL Server | `mcp_sqlserver` | `sqlserver` | **Sí** — ODBC Driver 17/18 |
| Informix | `mcp_informix` | `informix` | **Sí** — Client SDK / ODBC IBM |

## Requisitos

- Python 3.11+
- Acceso a la(s) base(s) que vayas a usar
- **SQL Server e Informix:** además de `pip install -e .`, debes instalar el driver nativo en cada máquina (ver sección abajo)

## Drivers adicionales (obligatorio para SQL Server e Informix)

`pip install -e .` instala `pyodbc`, pero **no** instala el driver del sistema. Sin eso, la conexión falla.

### SQL Server — ODBC Driver

1. Descarga e instala **Microsoft ODBC Driver 18 for SQL Server** (x64):  
   https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server
2. Si el instalador lo pide, instala también el [Visual C++ Redistributable](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist).
3. Verifica en PowerShell:

```powershell
Get-OdbcDriver | Where-Object { $_.Name -like "*SQL Server*" }
```

4. En `.env` usa el nombre exacto del driver, por ejemplo:

```env
SQLSERVER_DRIVER=ODBC Driver 18 for SQL Server
```

### Informix — Client SDK / ODBC

1. Descarga el **IBM Informix Client SDK** (incluye el ODBC Driver). Requiere cuenta/licencia IBM o HCL:  
   - https://www.ibm.com/support/pages/download-informix-products  
   - https://www.ibm.com/support/fixcentral  
   - HCL/Actian ESD: https://esd.actian.com/
2. Instala el Client SDK para **Windows x64**.
3. Verifica en *Orígenes de datos ODBC (64 bits)* que aparezca algo como `IBM INFORMIX ODBC DRIVER`.
4. En `.env`:

```env
INFORMIX_DRIVER=IBM INFORMIX ODBC DRIVER
INFORMIX_SERVER=ol_informix1410
```

`INFORMIX_SERVER` es el nombre del servidor Informix (`INFORMIXSERVER`), no solo el host.

## Instalación del proyecto

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

Instala el paquete (incluye los cuatro servidores):

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

Edita `.env` con las bases que uses (ver `.env.example`).

## Configurar el cliente MCP

Cada servidor se registra por separado (fusiona sin borrar otros MCPs):

```bash
python -m mcp_mysql setup
python -m mcp_oracle setup
python -m mcp_sqlserver setup
python -m mcp_informix setup
```

Opciones comunes:

```bash
python -m mcp_informix setup --client claude
python -m mcp_informix setup --dry-run
python -m mcp_informix setup --print
```

También: `mcp-mysql-setup` / `mcp-oracle-setup` / `mcp-sqlserver-setup` / `mcp-informix-setup`.

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

Las mismas tools en los cuatro servidores (solo lectura):

| Tool | Descripción |
|------|-------------|
| `test_connection` | Verifica la conexión |
| `list_tables` | Lista tablas |
| `list_views` | Lista vistas |
| `describe_table` | Columnas de una tabla |
| `list_indexes` | Índices de una tabla |
| `list_foreign_keys` | FKs de una tabla o de toda la DB |
| `find_column` | Busca columnas por nombre (`%` wildcard) |
| `sample_rows` | Muestra filas de ejemplo (máx. 100) |
| `count_rows` | Cuenta filas de una tabla |
| `execute_query` | SQL libre de solo lectura |

**MySQL:** `SELECT`, `SHOW`, `DESCRIBE`, `EXPLAIN`, `WITH` (usa `LIMIT`).

**Oracle / SQL Server / Informix:** `SELECT` / `WITH` (límites con `FETCH FIRST` / `TOP` / `FIRST`).

`execute_query` rechaza múltiples sentencias (`;`) y keywords de escritura (`INSERT`, `UPDATE`, `DELETE`, `DROP`, etc.). En producción usa además un usuario DB read-only.

## Notas

- Los comandos `python -m mcp_*` arrancan el servidor stdio; lo lanza el cliente.
- Las credenciales viven en `.env`, no en el JSON del cliente.
- MySQL y Oracle no requieren instalador de driver aparte (en el flujo típico).
- SQL Server e Informix **sí** requieren driver/SDK instalado en el sistema además de `pyodbc`.

## Estructura

```
MCP-DATABASE/
├── pyproject.toml
├── .env.example
├── src/
│   ├── mcp_mysql/
│   ├── mcp_oracle/
│   ├── mcp_sqlserver/
│   └── mcp_informix/
└── README.md
```

## Prueba

  ![Image Test](/img/test.png)
