# MCP MySQL

Servidor MCP en Python para conectar asistentes de IA (Cursor, Claude, Gemini, etc.) a una base de datos MySQL.

## Requisitos

- Python 3.11+
- Acceso a un servidor MySQL

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

Instala el paquete:

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

Edita `.env` con tu MySQL:

```env
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your_password
MYSQL_DATABASE=your_database
```

## Configurar el cliente MCP

Genera el JSON listo para pegar (rutas absolutas de tu máquina, sin passwords):

```bash
python -m mcp_mysql setup
```

También puedes usar:

```bash
mcp-mysql-setup
```

Copia la salida y pégala en la config MCP de tu cliente:

| Cliente | Dónde pegarlo |
|---------|----------------|
| Cursor | `~/.cursor/mcp.json` o MCP del proyecto |
| Claude Desktop | `claude_desktop_config.json` |
| Otros (Gemini, etc.) | Panel / archivo de servidores MCP del producto |

Si ya tienes otros servidores, fusiona solo la entrada `"mysql"`.

Ejemplo de salida:

```json
{
  "mcpServers": {
    "mysql": {
      "command": "C:\\ruta\\a\\MCP-DATABASE\\.venv\\Scripts\\python.exe",
      "args": ["-m", "mcp_mysql"],
      "cwd": "C:\\ruta\\a\\MCP-DATABASE"
    }
  }
}
```

Las credenciales viven en `.env`. Reinicia o recarga los MCP del cliente y prueba con `test_connection`.

## Tools disponibles

| Tool | Descripción |
|------|-------------|
| `test_connection` | Verifica la conexión a MySQL |
| `list_tables` | Lista las tablas de la base de datos |
| `describe_table` | Muestra columnas de una tabla |
| `execute_query` | Ejecuta consultas de solo lectura |

Por defecto solo se permiten consultas `SELECT`, `SHOW`, `DESCRIBE`, `EXPLAIN` y `WITH`.

## Notas

- `python -m mcp_mysql` arranca el servidor MCP (stdio). Lo lanza el cliente; no hace falta ejecutarlo a mano en el flujo normal.
- `python -m mcp_mysql setup` solo imprime el JSON de configuración.

## Estructura

```
MCP-DATABASE/
├── pyproject.toml
├── .env.example
├── src/
│   └── mcp_mysql/
│       ├── __init__.py
│       ├── __main__.py
│       ├── config.py      # Variables de entorno
│       ├── db.py          # Conexión MySQL
│       ├── tools.py       # Lógica de las tools
│       ├── setup.py       # Genera JSON para el cliente MCP
│       └── server.py      # Servidor MCP (FastMCP)
└── README.md
```

## Prueba

  ![Image Test](/img/test.png)
