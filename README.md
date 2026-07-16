# MCP MySQL

Servidor MCP en Python para conectar asistentes de IA (Cursor, Claude, etc.) a una base de datos MySQL.

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
│       └── server.py      # Servidor MCP (FastMCP)
└── README.md
```

## Requisitos

- Python 3.11+
- Acceso a un servidor MySQL

## Instalación

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Copia y edita las credenciales:

```bash
cp .env.example .env
```

## Tools disponibles

| Tool | Descripción |
|------|-------------|
| `test_connection` | Verifica la conexión a MySQL |
| `list_tables` | Lista las tablas de la base de datos |
| `describe_table` | Muestra columnas de una tabla |
| `execute_query` | Ejecuta consultas de solo lectura |

Por defecto solo se permiten consultas `SELECT`, `SHOW`, `DESCRIBE`, `EXPLAIN` y `WITH`.

## Uso con Cursor

En la configuración de MCP de Cursor (`~/.cursor/mcp.json` o settings del proyecto):

```json
{
  "mcpServers": {
    "mysql": {
      "command": "python",
      "args": ["-m", "mcp_mysql"],
      "cwd": "/ruta/absoluta/a/MCP-DATABASE",
      "env": {
        "MYSQL_HOST": "localhost",
        "MYSQL_PORT": "3306",
        "MYSQL_USER": "root",
        "MYSQL_PASSWORD": "tu_password",
        "MYSQL_DATABASE": "tu_database"
      }
    }
  }
}
```

Si usas el virtualenv del proyecto:

```json
{
  "mcpServers": {
    "mysql": {
      "command": "/ruta/absoluta/a/MCP-DATABASE/.venv/bin/python",
      "args": ["-m", "mcp_mysql"],
      "cwd": "/ruta/absoluta/a/MCP-DATABASE",
      "env": {
        "MYSQL_HOST": "localhost",
        "MYSQL_PORT": "3306",
        "MYSQL_USER": "root",
        "MYSQL_PASSWORD": "tu_password",
        "MYSQL_DATABASE": "tu_database"
      }
    }
  }
}
```

## Ejecución local

```bash
python -m mcp_mysql
```

El servidor usa transporte `stdio` (estándar para clientes MCP).

## Prueba

  ![Image Test](/img/test.png)

