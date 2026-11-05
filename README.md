# MCP osTicket (MySQL/MariaDB)

Servidor [MCP](https://modelcontextprotocol.io) de **solo lectura** sobre la base de datos de
osTicket. Está pensado para que agentes de soporte consulten, desde un asistente (LibreChat),
tickets, hilos, clientes, empresas y reportes de agentes, sin escribir SQL.

El modelo solo puede usar herramientas con consultas fijas y parametrizadas. No existe una
herramienta de SQL libre.

## Estado

| Fase | Contenido | Estado |
|------|-----------|--------|
| 1. Refinar | Herramientas de soporte, seguridad, pruebas | Completa |
| 2. Exponer | Despliegue HTTP con autenticación junto a LibreChat | Pendiente |
| 3. LibreChat | Configuración del servidor MCP y del agente | Pendiente |

Hasta completar la fase 2, el transporte HTTP **no autentica clientes**. Úsalo solo en
`127.0.0.1` o en una red controlada.

## Instalación

Requiere Python 3.11 o superior.

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
cp .env.example .env   # y edita las credenciales
```

### Cuenta de base de datos

Usa una cuenta exclusiva y de solo lectura. El MCP genera los permisos por columna que
corresponden exactamente a su política de acceso:

```bash
python -m mcp_mysql grants --database osticket --user mcp_readonly --host localhost
```

Revisa la salida y ejecútala como administrador de la base. Con esos permisos, aunque el MCP
tuviera un defecto, la base no le entregaría contraseñas, correos del personal ni otras
columnas fuera de la política. `MYSQL_USER` es obligatorio: no hay usuario por defecto.

### Variables principales (`.env`)

| Variable | Uso |
|----------|-----|
| `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE` | Conexión |
| `MYSQL_SSL_CA`, `MYSQL_SSL_VERIFY_IDENTITY` | TLS con verificación de certificado (recomendado si la base es remota) |
| `MYSQL_QUERY_TIMEOUT_MS` | Tiempo máximo por consulta (15000 por defecto) |
| `OSTICKET_COMPANY_LIST_ID` | Lista de osTicket con las empresas (3 en esta instalación) |
| `MCP_ENABLE_EXPLORATION_TOOLS` | Muestra `list_tables`, `describe_table` y `sample_rows` (desactivado por defecto) |
| `MCP_SCHEMA_CACHE_SECONDS` | Caché del esquema detectado (300 s) |
| `MCP_MAX_DB_CONNECTIONS` | Conexiones simultáneas a la base (8) |

Las variables ya definidas en el entorno tienen prioridad sobre `.env`.

## Ejecución

```bash
# Clientes que lanzan el proceso (Claude Code, Cursor, Claude Desktop): stdio
python -m mcp_mysql --transport stdio

# HTTP (Streamable HTTP) en http://127.0.0.1:8000/mcp
python -m mcp_mysql --host 127.0.0.1 --port 8000
```

El transporte por defecto es HTTP. Las entradas de cliente deben pedir `--transport stdio`
de forma explícita. `--allowed-host` añade nombres aceptados en el encabezado `Host`; protege
contra DNS rebinding, pero no autentica.

### Registrar el MCP en un cliente

```bash
python -m mcp_mysql setup --client claude-code   # imprime el comando "claude mcp add"
python -m mcp_mysql setup --client cursor        # escribe ~/.cursor/mcp.json
python -m mcp_mysql setup --client claude        # Claude Desktop
python -m mcp_mysql setup --print                # solo muestra el JSON
```

Las credenciales se quedan en `.env` y nunca se copian a la configuración del cliente.

## Herramientas

| Herramienta | Para qué |
|-------------|----------|
| `test_connection` | Conexión, versión y **hora del servidor** (para "hoy", "esta semana") |
| `list_catalog` | Estados, departamentos, prioridades, temas de ayuda, equipos y SLA con sus IDs |
| `find_companies` | Buscar empresa (entidad) por nombre y obtener `company_id` |
| `list_company_tickets` | Tickets de una empresa (`limit=1` devuelve el último) |
| `search_tickets` | Búsqueda con filtros combinables y paginación |
| `count_tickets` | Totales exactos con los mismos filtros |
| `ticket_report` | Conteos agrupados por estado, agente, empresa, mes, etc., con horas opcionales |
| `get_ticket` | Detalle completo: prioridad, SLA, solicitante, colaboradores, apoyo, horas y resumen del hilo |
| `get_ticket_thread` | Conversación en texto plano, con mensajes, respuestas y notas internas |
| `find_agents` | Buscar agentes y obtener `staff_id` |
| `get_agent_report` | Carga, actividad, apoyo y horas de un agente en un período |
| `find_users` | Buscar clientes por nombre o correo y obtener `user_id` |
| `get_user` | Perfil del cliente: correos, historial, empresas y último ticket |

Filtros de búsqueda, conteo y reportes:
- **Personas y empresa:** `company_id`, `staff_id`, `assigned`, `user_id` (`include_collaborations` agrega los tickets donde el usuario está en copia).
- **Estado:** `status` (nombre exacto) y `state` (`open`, `closed`, `archived`, `deleted`).
- **Clasificación:** `dept_id`, `priority_id`, `topic_id` y `overdue`.
- **Fechas:** `created_from`/`created_to` y `closed_from`/`closed_to`, como días calendario inclusivos.
- **Texto:** `subject` (subcadena literal).

Ejemplos de preguntas y las herramientas que deberían usarse están en
[docs/banco-de-preguntas.md](docs/banco-de-preguntas.md).

### Contrato de respuesta

Toda respuesta es JSON con `ok`, `data`, `error` y `meta`:

- `meta.truncated` y `meta.truncation` indican campos recortados (4000 caracteres) o filas
  omitidas por el límite de 64 KiB por respuesta.
- La paginación usa `next_offset`, `next_after_entry_id` o `next_before_entry_id` mientras
  `has_more` sea `true`. El desplazamiento máximo es 10000.
- `unavailable_fields` lista campos que esta base no tiene; no significa que estén vacíos.
- Los errores tienen un `code` estable, un mensaje seguro, `retryable` y `meta.request_id`,
  pero nunca el texto del driver, consultas ni credenciales.

## Particularidades de esta instalación de osTicket

Verificadas contra la base real (MariaDB 10.3, ~12 000 tickets):

- **Empresa:** `listaEmpresa` guarda `"id,Nombre"` o solo `"id"`, siempre de la lista 3.
  Un ticket tiene una sola empresa.
- **Horas:** `time`, `timeExtra` y `timeApoyoN` son texto `h:mm`. Los reportes suman solo los
  valores con ese formato y cuentan el resto en `unparsed_time_values`, sin adivinarlos.
- **Personal de apoyo** (`apoyo1` a `apoyo3`): el `staff_id` se lee de las respuestas del
  formulario (`{"s12":"Nombre"}`), porque `__cdata` a menudo guarda solo el nombre.
- **Estados:** "Resuelto" está configurado como estado `open`. Usa
  `list_catalog("statuses")` para ver qué cuenta como abierto.
- **Zona horaria:** la base usa la hora del sistema (UTC−4). Las fechas de los filtros se
  interpretan en esa zona.
- Un número de ticket está duplicado: `get_ticket` devuelve `AMBIGUOUS_MATCH` en vez de elegir uno.

## Seguridad

Varias capas independientes:

1. **Lista de columnas permitidas** ([access.py](src/mcp_mysql/access.py)). Lo que no está
   listado se rechaza, incluidas las columnas que agreguen futuras versiones. Las tablas de
   formularios solo se usan para el personal de apoyo y nunca se exploran.
2. **Consultas fijas y parametrizadas.** Ningún argumento se interpola en el SQL, ni siquiera
   los comodines de `LIKE`.
3. **Sesión de solo lectura:** `SET SESSION TRANSACTION READ ONLY`, transacción de solo
   lectura, sin multi-sentencias ni `LOCAL INFILE`, tiempo máximo por consulta y nunca `COMMIT`.
4. **Permisos por columna** en la base (`grants`).
5. **Validación estricta** de argumentos antes de tocar la base. Los argumentos desconocidos
   se rechazan.
6. **Errores sin filtrar detalles** y **auditoría** de cada llamada en el logger
   `mcp_mysql.audit`: `request_id`, herramienta, resultado y duración, sin argumentos ni datos.
7. El texto de tickets e hilos se trata como no confiable. Las instrucciones del servidor
   piden al modelo no seguir órdenes que contenga.

Todos los agentes de soporte ven todos los tickets, notas internas incluidas. Se exponen
nombres y correos de clientes; del personal se exponen nombre, departamento y estado, pero
no su correo, teléfono ni credenciales.

## Rendimiento

Cada llamada abre una conexión, protegida como se describe arriba, y ejecuta todas sus
consultas en ella. Desde el equipo de desarrollo, con 113 ms de latencia hacia la base, cada
llamada tarda unos 1,6 s, casi todo en establecer la conexión. Si en producción la base no
está en la misma red, conviene evaluar un pool de conexiones (fase 2).

Las herramientas corren en hilos de trabajo, así que una consulta lenta no bloquea a los
demás usuarios.

## Pruebas

```bash
.venv/bin/python -m pytest -q
```

Las pruebas unitarias no se conectan a ninguna base. Las de integración son opcionales y
usan un servidor desechable con `root` sin contraseña, solo en `127.0.0.1`:

```bash
docker run --rm -d --name mcp-it -p 127.0.0.1:33061:3306 -e MYSQL_ALLOW_EMPTY_PASSWORD=yes mariadb:10.3
MCP_TEST_MYSQL_PORT=33061 .venv/bin/python -m pytest -q tests/test_mysql_integration.py
docker stop mcp-it
```

Cada ejecución crea un esquema con datos ficticios y una cuenta que solo tiene los permisos
por columna de la política, y los elimina al terminar. Están verificadas con MySQL 8.0 y
MariaDB 10.3.
