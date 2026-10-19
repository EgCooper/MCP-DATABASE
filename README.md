# MCP Database

Servidores MCP en Python para conectar asistentes de IA (Cursor, Claude, Gemini, etc.) a **MySQL**, **Oracle**, **SQL Server**, **Informix** y **PostgreSQL**.

Hay cinco servidores independientes en el mismo repo:

| Servidor | Módulo | Entrada MCP | Driver extra en la PC |
|----------|--------|-------------|------------------------|
| MySQL | `mcp_mysql` | `mysql` | No (pip alcanza) |
| Oracle | `mcp_oracle` | `oracle` | No (pip / thin mode) |
| PostgreSQL | `mcp_postgresql` | `postgresql` | No (pip / `psycopg`) |
| SQL Server | `mcp_sqlserver` | `sqlserver` | **Sí** — ODBC Driver 17/18 |
| Informix | `mcp_informix` | `informix` | **Sí** — Client SDK / ODBC IBM |

## Requisitos

- Python 3.11+ (los scripts de [Setup rápido](#setup-rápido-recomendado) lo instalan solos si falta)
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

Instala el paquete (incluye los cinco servidores):

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

## Setup rápido (recomendado)

Este repo incluye scripts en `resources/Scripts/` que dejan todo listo sin necesitar Python instalado ni permisos de administrador:

1. Preguntan qué motores vas a usar. Con Enter aceptas la sugerencia: los motores que ya tengas configurados en `.env`, o `mysql` la primera vez.
2. Instalan [uv](https://docs.astral.sh/uv/) 0.12.24 en `~/.local/bin` si no está.
3. Instalan Python 3.13 en tu carpeta de usuario, sin tocar el Python del sistema:
   - **Linux / macOS:** el Python que descarga uv.
   - **Windows:** el instalador oficial de python.org (3.13.16), en `%LOCALAPPDATA%\Programs\Python\Python313`. El script verifica que esté firmado por la Python Software Foundation antes de ejecutarlo. No se usa el Python de uv porque no está firmado y [Smart App Control](#windows-smart-app-control) lo bloquea.
4. Crean el `.venv` en la raíz del repo e instalan el paquete. Si encuentran un `.venv` creado con otro Python (por una versión anterior del script), lo recrean.
5. Verifican que Python pueda cargar los MCP, para que un problema aparezca aquí y no como "Connection closed" dentro de Claude Code.
6. Copian `.env.example` → `.env` si no existe.
7. Piden los datos de conexión de cada motor elegido (host, puerto, base, usuario, contraseña, etc.), los guardan en `.env` y prueban la conexión en el momento. Si falla, muestran el error y ofrecen corregir los datos. La contraseña no se ve al escribirla, y en Linux/macOS el `.env` queda legible solo por tu usuario. Si un motor ya está configurado, solo preguntan si quieres cambiarlo. Oracle admite varias bases (perfiles, ver [Oracle: varias conexiones](#oracle-varias-conexiones-perfiles)).
8. Registran en Claude Code cada motor elegido, disponible en todas tus carpetas (`claude mcp add --scope user`), y comprueban que arranque. Si ya estaba registrado, lo reemplazan; por eso, si mueves el repo de carpeta, basta con volver a ejecutar el script. Si no encuentran Claude Code, imprimen los comandos para registrarlos a mano.

Puedes ejecutarlos desde cualquier carpeta; siempre trabajan sobre la raíz del repo. Necesitan acceso a internet (astral.sh, github.com y, en Windows, python.org) la primera vez.

**Linux / macOS:**
```bash
./resources/Scripts/setup_claude_code.sh
```

**Windows:** doble clic en `resources\Scripts\setup_claude_code.cmd`, o desde una terminal:
```powershell
.\resources\Scripts\setup_claude_code.cmd
```

Para no elegir los motores en el menú, pásalos como argumento (nombres o números, `todos` o `ninguno`):

```bash
./resources/Scripts/setup_claude_code.sh mysql oracle
.\resources\Scripts\setup_claude_code.cmd mysql
```

Al terminar, solo falta abrir Claude Code (o reiniciarlo, si ya estaba abierto) y pedir *"prueba la conexión a mysql"*. Para cambiar credenciales más adelante, vuelve a ejecutar el script: con Enter mantienes los datos actuales.

Si el script corre sin terminal interactiva (por ejemplo, desde otra herramienta), no pide credenciales: completa `.env` a mano, quitando el `#` de cada línea.

El `.cmd` ejecuta el `.ps1` con `-ExecutionPolicy Bypass` solo para esa ejecución, así que no hace falta cambiar la execution policy de la máquina. Si tu empresa fija la política por GPO (directiva de grupo), esa directiva tiene prioridad y el script no correrá: en ese caso pide a TI que lo habilite o usa la [instalación manual](#instalación-del-proyecto).

#### Windows: Smart App Control

En equipos con Windows 11 que tienen Smart App Control activo, Windows puede bloquear archivos de Python sin firma. El error se ve así:

```
ImportError: DLL load failed while importing unicodedata: Una directiva de Control de aplicaciones bloqueó este archivo.
```

El script evita el caso más común usando el Python oficial (firmado). Algunos paquetes instalados con pip traen archivos `.pyd` sin firma que Smart App Control también puede bloquear; si pasa, el script se detiene y lo indica. La única solución en ese caso es desactivarlo en *Seguridad de Windows → Control de aplicaciones y navegador → Configuración de Smart App Control*, y volver a ejecutar el script. El script no lo desactiva solo: es una protección de todo el equipo, requiere ser administrador y, según la versión de Windows 11, puede no volver a activarse sin reinstalar Windows. En equipos de la empresa, consúltalo con TI.

## Configurar el cliente MCP

Cada servidor se registra por separado (fusiona sin borrar otros MCPs):

```bash
python -m mcp_mysql setup
python -m mcp_oracle setup
python -m mcp_postgresql setup
python -m mcp_sqlserver setup
python -m mcp_informix setup
```

Opciones comunes:

```bash
python -m mcp_postgresql setup --client claude
python -m mcp_postgresql setup --dry-run
python -m mcp_postgresql setup --print
```

También: `mcp-mysql-setup` / `mcp-oracle-setup` / `mcp-postgresql-setup` / `mcp-sqlserver-setup` / `mcp-informix-setup`.

Recarga los MCP del cliente y prueba con `test_connection`.

### Claude Code (CLI)

Los scripts de [Setup rápido](#setup-rápido-recomendado) ya registran los MCP en Claude Code. Para hacerlo a mano, usa el comando nativo `claude mcp add` (el comando `setup` de este repo solo soporta `--client cursor` y `--client claude`, que es Claude **Desktop**).

Ejecuta estos comandos en una terminal normal, no dentro de una sesión de Claude, y desde la raíz del repo (si no, reemplaza `$(pwd)` / `$PWD` por la ruta absoluta al proyecto). `--scope user` deja el MCP disponible en todas tus carpetas; sin esa opción, Claude Code lo registra solo para la carpeta donde ejecutaste el comando.

**Linux / macOS:**

```bash
claude mcp add --scope user mysql -- "$(pwd)/.venv/bin/python" -m mcp_mysql
claude mcp add --scope user oracle -- "$(pwd)/.venv/bin/python" -m mcp_oracle
claude mcp add --scope user postgresql -- "$(pwd)/.venv/bin/python" -m mcp_postgresql
claude mcp add --scope user sqlserver -- "$(pwd)/.venv/bin/python" -m mcp_sqlserver
claude mcp add --scope user informix -- "$(pwd)/.venv/bin/python" -m mcp_informix
```

**Windows (PowerShell):**

```powershell
claude mcp add --scope user mysql -- "$PWD\.venv\Scripts\python.exe" -m mcp_mysql
claude mcp add --scope user oracle -- "$PWD\.venv\Scripts\python.exe" -m mcp_oracle
claude mcp add --scope user postgresql -- "$PWD\.venv\Scripts\python.exe" -m mcp_postgresql
claude mcp add --scope user sqlserver -- "$PWD\.venv\Scripts\python.exe" -m mcp_sqlserver
claude mcp add --scope user informix -- "$PWD\.venv\Scripts\python.exe" -m mcp_informix
```

Registra solo los motores que vayas a usar. Puedes registrarlos antes de completar `.env`: el MCP lee las credenciales al arrancar, así que si cambias `.env` después, reinicia Claude Code.

Verifica con:

```bash
claude mcp list
```

Y quita un servidor mal configurado con:

```bash
claude mcp remove --scope user <nombre>
```

Luego prueba con la tool `test_connection` dentro de una sesión de Claude Code.

### Oracle: varias conexiones (perfiles)

Un solo MCP `oracle` puede apuntar a varias bases. En `.env`:

```env
Multi Connection

ORACLE_CONNECTIONS=B1,B2
ORACLE_DEFAULT=B1

ORACLE_B1_USER=
ORACLE_B1_PASSWORD=
ORACLE_B1_HOST=
ORACLE_B1_PORT=
ORACLE_B1_SID=

ORACLE_B2_USER=
ORACLE_B2_PASSWORD=
ORACLE_B2_HOST=
ORACLE_B2_PORT=  
ORACLE_B2_SID=

```

Uso en tools: `list_connections`, luego `list_tables(connection="qa")`, `execute_query(..., connection="qa")`, etc.  
Si omites `connection`, se usa `ORACLE_DEFAULT`.

El modo simple (una sola DB) sigue funcionando con `ORACLE_USER` / `ORACLE_DSN` sin `ORACLE_CONNECTIONS`.

| Cliente | Archivo por defecto |
|---------|---------------------|
| Cursor Windows| `\Users\username\.cursor`  |
| Cursor Linux| `/home/user/.cursor/mcp.json`  |
| Gemini Windows | `C:\users\user_name\.gemini\config\mcp_config.json`  |
| Gemini Linux | `/home/username/.gemini/config/mcp_config.json`  |
| Claude Desktop Windows | `%APPDATA%\Claude\claude_desktop_config.json`  |
| Claude Desktop macOS/Linux | `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) / `~/.config/Claude/claude_desktop_config.json` (Linux)  |

> **Claude Code (CLI):** no uses `--client claude` para esto — ese modo apunta a Claude Desktop, no a Claude Code. Usa `claude mcp add` como se explica en la sección [Claude Code (CLI)](#claude-code-cli) arriba.

## Tools disponibles

Las mismas tools en los cinco servidores (solo lectura):

| Tool | Descripción |
|------|-------------|
| `list_connections` | Lista perfiles Oracle configurados (solo Oracle por ahora) |
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

**MySQL / PostgreSQL:** `SELECT`, `SHOW`/`EXPLAIN` donde aplique, `WITH` (usa `LIMIT`).

**Oracle / SQL Server / Informix:** `SELECT` / `WITH` (límites con `FETCH FIRST` / `TOP` / `FIRST`).

`execute_query` rechaza múltiples sentencias (`;`) y keywords de escritura (`INSERT`, `UPDATE`, `DELETE`, `DROP`, etc.). En producción usa además un usuario DB read-only.

### Reportes fijos (solo MySQL)

Para reportes que siempre deben ejecutar la misma query (y no una armada por el modelo), el servidor MySQL expone tools que leen el SQL desde `resources/querys/`:

| Tool | Query | Parámetros |
|------|-------|------------|
| `report_hours` | `resources/querys/hours.sql` | `desde`, `hasta` en formato `YYYYMMDD` (ej. `20260101`, `20260826`) |

- El SQL se lee del archivo en cada llamada: si editas `hours.sql`, el cambio aplica sin reiniciar el MCP.
- `hours.sql` usa los marcadores `%(desde)s` y `%(hasta)s`; no se puede pegar tal cual en otro cliente SQL. Para eso está `hours.original.sql` (con fechas fijas).
- Estos reportes no pasan por el validador de `execute_query` (la query usa la función `REPLACE()`) ni se recortan con `LIMIT`.

## Notas

- Los comandos `python -m mcp_*` arrancan el servidor stdio; lo lanza el cliente.
- Las credenciales viven en `.env`, no en el JSON del cliente.
- MySQL, Oracle y PostgreSQL no requieren instalador de driver aparte (en el flujo típico).
- SQL Server e Informix **sí** requieren driver/SDK instalado en el sistema además de `pyodbc`.

## Estructura

```
MCP-DATABASE/
├── pyproject.toml
├── .env.example
├── src/
│   ├── mcp_mysql/
│   ├── mcp_oracle/
│   ├── mcp_postgresql/
│   ├── mcp_sqlserver/
│   └── mcp_informix/
├── resources/
│   ├── querys/          # SQL de reportes fijos (ej. hours.sql)
│   └── Scripts/         # setup_claude_code.sh / .ps1 / .cmd y configure_env.py (credenciales)
└── README.md
```

## Prueba

  ![Image Test](/img/test.png)
