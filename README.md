# MCP MySQL

Servicio MCP para consultar MySQL desde un consumidor como LibreChat. Este branch contiene únicamente el servidor MySQL y conserva el reporte de horas de osTicket.

## Instalación

Requiere Python 3.11 o superior y acceso de red a MySQL.

```bash
python -m venv .venv
# Linux / macOS
source .venv/bin/activate
# Windows PowerShell
# .\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

Define `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD` y `MYSQL_DATABASE` en el entorno del proceso. Para desarrollo también puedes copiar `.env.example` a `.env` y completar los valores. Las variables del entorno tienen prioridad. No subas ni compartas `.env`.

Usa una cuenta MySQL con permisos de solo lectura. El filtro SQL de la aplicación no sustituye los permisos de la base de datos.

## Ejecutar por HTTP

```bash
python -m mcp_mysql
```

El transporte predeterminado es Streamable HTTP. Escucha en `127.0.0.1:8000` y publica MCP en `/mcp`:

```text
http://127.0.0.1:8000/mcp
```

Para aceptar conexiones desde otra máquina o contenedor:

```bash
python -m mcp_mysql --host 0.0.0.0 --port 8000 --allowed-host mcp-mysql:8000
```

Sustituye `mcp-mysql:8000` por el host y puerto de la URL que utilizará el consumidor. Puedes repetir `--allowed-host`. Esta opción valida el encabezado HTTP Host; no autentica al consumidor.

Configura el consumidor MCP con transporte Streamable HTTP y la URL accesible del servicio terminada en `/mcp`. En contenedores separados, `localhost` apunta al propio contenedor; utiliza el nombre del servicio o la dirección del servidor MCP.

El servicio todavía no implementa autenticación. Antes de publicarlo en Internet hay que configurar autenticación, HTTPS y controles de acceso. Para esta etapa, ejecútalo en una red privada controlada.

## Depuración local

Se conserva stdio como opción explícita:

```bash
python -m mcp_mysql --transport stdio
```

También está disponible el comando `mcp-mysql` después de instalar el paquete. Ya no se incluyen asistentes para registrar clientes locales.

## Herramientas

- `test_connection`: verifica conectividad y versión de MySQL.
- `list_tables`, `list_views`: descubren objetos.
- `describe_table`, `list_indexes`, `list_foreign_keys`: consultan estructura y relaciones.
- `find_column`: busca columnas por nombre o patrón.
- `sample_rows`, `count_rows`: consultan muestras y cantidades.
- `execute_query`: ejecuta SQL sujeto al validador de la aplicación.
- `report_hours`: ejecuta el reporte de osTicket con fechas `desde` y `hasta` en formato `YYYYMMDD`.

Consulta [la documentación técnica](docs/DESARROLLO.md) para conocer la estructura y las limitaciones actuales.
