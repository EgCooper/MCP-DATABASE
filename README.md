# MCP osTicket

Servidor [MCP](https://modelcontextprotocol.io) de **solo lectura** sobre la base de datos de
osTicket (MySQL/MariaDB). Lo usan los agentes de soporte desde **LibreChat** para consultar
tickets, conversaciones, clientes, empresas y reportes de agentes en lenguaje natural, sin
escribir SQL.

Corre como un contenedor más junto a LibreChat. Cualquier otro servicio de la misma red Docker
que hable MCP puede consumirlo con el token.

## Qué puede responder

- **Tickets:** "¿En qué estado está el ticket 012345?", "¿Qué solución se registró?",
  "Tickets de prioridad alta vencidos".
- **Conversaciones:** "¿Qué fue lo último que respondió el cliente?", "Resume el hilo",
  "¿Hay notas internas?".
- **Clientes y empresas:** "¿Cuál es el último ticket de HOSPICIO?", "Historial de Juan Pérez",
  "Tickets del cliente x@dominio.com".
- **Reportes:** "¿Cuántos tickets abiertos tiene cada agente?", "¿Cuántos cerró María en
  octubre y cuántas horas registró?", "Horas por empresa el mes pasado".

Más ejemplos, con la herramienta que debe usar el modelo, en
[docs/banco-de-preguntas.md](docs/banco-de-preguntas.md).

### Herramientas

| Herramienta | Para qué |
|-------------|----------|
| `test_connection` | Conexión y **hora del servidor** (para resolver "hoy", "esta semana") |
| `list_catalog` | Estados, departamentos, prioridades, temas de ayuda, equipos y SLA con sus IDs |
| `find_companies` | Buscar una empresa por nombre y obtener su `company_id` |
| `list_company_tickets` | Tickets de una empresa (`limit=1` devuelve el último) |
| `search_tickets` | Búsqueda con filtros combinables y paginación |
| `count_tickets` | Totales exactos con los mismos filtros |
| `ticket_report` | Conteos por estado, agente, empresa, mes, etc., con horas opcionales |
| `get_ticket` | Detalle completo: prioridad, SLA, solicitante, colaboradores, apoyo, horas y resumen del hilo |
| `get_ticket_thread` | Conversación en texto plano, con mensajes, respuestas y notas internas |
| `find_agents` | Buscar agentes y obtener su `staff_id` |
| `get_agent_report` | Carga, actividad, apoyo y horas de un agente en un período |
| `find_users` | Buscar clientes por nombre o correo y obtener su `user_id` |
| `get_user` | Perfil del cliente: correos, historial, empresas y último ticket |

Filtros de búsqueda, conteo y reportes:
- **Personas y empresa:** `company_id`, `staff_id`, `assigned`, `user_id` (`include_collaborations` agrega los tickets donde el cliente está en copia).
- **Estado:** `status` (nombre exacto) y `state` (`open`, `closed`, `archived`, `deleted`).
- **Clasificación:** `dept_id`, `priority_id`, `topic_id` y `overdue`.
- **Fechas:** `created_from`/`created_to` y `closed_from`/`closed_to`, como días calendario inclusivos.
- **Texto:** `subject` (subcadena literal).

No existe una herramienta de SQL libre: todas las consultas son fijas y parametrizadas. Hay
tres herramientas de exploración del esquema para administradores (`list_tables`,
`describe_table`, `sample_rows`). Están ocultas salvo que se active
`MCP_ENABLE_EXPLORATION_TOOLS=true`.

## Arquitectura

```
Agentes ──▶ LibreChat ──── Authorization: Bearer <token> ────▶ mcp-osticket ──── solo lectura ────▶ MariaDB osTicket
            (contenedor)                                         (contenedor, :8000)
            └───────────── red Docker librechat_default ────────────┘
```

- El contenedor `mcp-osticket` **no publica puertos**. Solo lo alcanzan los contenedores de su
  red, en `http://mcp-osticket:8000/mcp`, y solo con el token.
- **LibreChat decide qué personas** pueden usarlo. El registro público está cerrado y las
  cuentas las crea el administrador.

## Despliegue

Requisitos:
- Docker con Compose.
- LibreChat levantado con Docker Compose, que crea la red `librechat_default`.
- Acceso de red a la base de osTicket con una cuenta de solo lectura.

### 1. Cuenta de base de datos de solo lectura

El MCP genera los permisos por columna que corresponden exactamente a lo que consulta.
Revísalos y ejecútalos como administrador de la base:

```bash
docker run --rm mcp-osticket:latest grants --database osticket --user mcp_readonly --host '<IP del servidor>'
```

`<IP del servidor>` es la IP desde la que el servidor llega a la base. La imagen se construye
en el paso 3; si es la primera vez, ejecuta este comando después de ese paso.

### 2. Configuración

```bash
sudo install -d -o "$USER" -g "$USER" /opt/mcp-osticket
git clone --branch mysql git@github.com:EgCooper/MCP-DATABASE.git /opt/mcp-osticket
cd /opt/mcp-osticket
cp .env.example .env && chmod 600 .env
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # token para MCP_AUTH_TOKEN
```

Edita `.env`:

| Variable | Uso |
|----------|-----|
| `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE` | Conexión a osTicket (`MYSQL_USER` es obligatorio) |
| `MCP_AUTH_TOKEN` | Token que deben enviar los clientes (mínimo 32 caracteres) |
| `MYSQL_SSL_CA`, `MYSQL_SSL_VERIFY_IDENTITY` | TLS con verificación de certificado, si la base lo admite |
| `OSTICKET_COMPANY_LIST_ID` | Lista de osTicket con las empresas (3 por defecto) |
| `MYSQL_QUERY_TIMEOUT_MS` | Tiempo máximo por consulta (15000) |
| `MCP_MAX_DB_CONNECTIONS` | Conexiones simultáneas a la base (8) |
| `MCP_ENABLE_EXPLORATION_TOOLS` | Herramientas de exploración del esquema (`false`) |

### 3. Levantar el contenedor

```bash
docker compose up -d --build --wait     # termina cuando el MCP está "healthy"
```

El contenedor corre con un usuario sin privilegios, sistema de archivos de solo lectura, sin
*capabilities*, 256 MB de memoria y reinicio automático. El `.env` no entra en la imagen: se
lee al arrancar. Si la red de LibreChat tiene otro nombre, defínelo en `LIBRECHAT_NETWORK`.

### 4. Conectar LibreChat

En `LibreChat/.env`, define el mismo token:
```dotenv
MCP_OSTICKET_TOKEN=<el mismo valor que MCP_AUTH_TOKEN>
ALLOW_REGISTRATION=false
```

En `LibreChat/librechat.yaml`:
```yaml
mcpSettings:
  allowedAddresses:
    - 'mcp-osticket:8000'        # excepción SSRF solo para este destino privado

mcpServers:
  mysql:
    type: streamable-http
    url: http://mcp-osticket:8000/mcp
    headers:
      Authorization: "Bearer ${MCP_OSTICKET_TOKEN}"
    requiresOAuth: false         # token fijo, no OAuth
    title: osTicket
    description: Consultas de solo lectura sobre tickets, hilos, clientes y agentes de osTicket.
    serverInstructions: true     # incluye las instrucciones del MCP para el modelo
    timeout: 60000
```

Usa `allowedAddresses` y no `allowedDomains`: este último deja pasar solo lo que está en la
lista y bloquearía el resto de los destinos. `requiresOAuth: false` es obligatorio: sin esa
línea, LibreChat confunde el token con OAuth y no carga las herramientas.

Reinicia LibreChat **después** de que el MCP esté sano y verifica:
```bash
docker restart LibreChat
docker logs LibreChat 2>&1 | grep "\[MCP\] Initialized" | tail -1   # ... 1 configured server and 13 tools
```

Actualizaciones, cambio de token, diagnóstico, volver a una versión anterior y usuarios de
LibreChat: [docs/despliegue.md](docs/despliegue.md).

## Consumirlo desde otro servicio

Cualquier cliente MCP en la misma red Docker puede usarlo:

| | |
|-|-|
| Protocolo | MCP sobre Streamable HTTP |
| Endpoint | `http://mcp-osticket:8000/mcp` |
| Autenticación | Encabezado `Authorization: Bearer <MCP_AUTH_TOKEN>` en cada petición (sin token o con uno incorrecto: `401`) |
| Salud | `GET http://mcp-osticket:8000/health`, sin token, responde `{"status":"ok"}` |
| Red | `librechat_default`. Otro proyecto compose la declara como red `external` |
| Encabezado `Host` | Solo se aceptan los nombres de `MCP_ALLOWED_HOSTS` (`mcp-osticket:*` en `compose.yaml`) y `localhost`. Si el cliente usa otro nombre o alias, agrégalo ahí |

Todas las herramientas devuelven un único bloque de texto JSON con la misma estructura:

```json
{"ok": true, "data": {...}, "error": null,
 "meta": {"request_id": "…", "is_sample": false, "truncated": false, "truncation": null}}
```

- **Errores:** `ok` es `false` y `error` trae un `code` estable (por ejemplo `NOT_FOUND`,
  `INVALID_ARGUMENTS` o `DATABASE_TIMEOUT`), un mensaje seguro y `retryable`. Nunca incluye
  texto del driver, consultas ni credenciales.
- **Recortes:** las respuestas miden como máximo 64 KiB y cada campo 4000 caracteres.
  `meta.truncated` avisa cuando algo se recortó.
- **Paginación:** se continúa con `next_offset`, `next_after_entry_id` o `next_before_entry_id`
  mientras `has_more` sea `true`.
- **Campos ausentes:** `unavailable_fields` lista los campos que esta base no tiene, que no es
  lo mismo que estar vacíos.

Hoy todos los consumidores comparten un mismo token.

## Seguridad

1. **Lista de columnas permitidas** ([access.py](src/mcp_mysql/access.py)). Lo que no está
   listado se rechaza, incluidas las columnas que agreguen futuras versiones de osTicket. Del
   personal se exponen nombre, departamento y estado, nunca credenciales, correo ni teléfono.
2. **Consultas fijas y parametrizadas.** Los argumentos se validan de forma estricta antes de
   tocar la base, y los desconocidos se rechazan.
3. **Sesión de solo lectura:** transacción de solo lectura, sin multi-sentencias ni
   `LOCAL INFILE`, tiempo máximo por consulta y nunca `COMMIT`.
4. **Permisos por columna en la base**, generados con `grants`.
5. **Token entre clientes y MCP**, comparado en tiempo constante y nunca registrado. El
   contenedor no publica puertos.
6. **Auditoría:** cada llamada deja una línea `tool_call` con `request_id`, herramienta,
   resultado y duración, sin argumentos ni datos. Los accesos sin token válido dejan
   `http_unauthorized`, con la IP de origen.
7. **El texto de tickets e hilos se trata como no confiable:** las instrucciones del MCP piden
   al modelo no obedecer órdenes que vengan dentro de un mensaje.

Todos los agentes de soporte ven todos los tickets, notas internas incluidas.

## Particularidades de esta instalación de osTicket

- **Empresa:** `listaEmpresa` guarda `"id,Nombre"` o solo `"id"`, de la lista 3. Un ticket
  tiene una sola empresa.
- **Horas:** `time`, `timeExtra` y `timeApoyoN` son texto `h:mm`. Los reportes suman solo los
  valores con ese formato y cuentan el resto en `unparsed_time_values`, sin adivinarlos.
- **Personal de apoyo** (`apoyo1` a `apoyo3`): el `staff_id` se lee de las respuestas del
  formulario (`{"s12":"Nombre"}`).
- **Estados:** "Resuelto" está configurado como estado `open`.
  `list_catalog("statuses")` muestra qué cuenta como abierto.
- **Zona horaria:** la de la base (UTC−4). Las fechas de los filtros se interpretan en esa zona.

## Desarrollo

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest -q
```

Las pruebas unitarias no se conectan a ninguna base. Las de integración usan un servidor
desechable en `127.0.0.1`, con `root` sin contraseña. Crean un esquema ficticio y una cuenta
con solo los permisos por columna de la política, y los eliminan al terminar:

```bash
docker run --rm -d --name mcp-it -p 127.0.0.1:33061:3306 -e MYSQL_ALLOW_EMPTY_PASSWORD=yes mariadb:10.3
MCP_TEST_MYSQL_PORT=33061 .venv/bin/python -m pytest -q tests/test_mysql_integration.py
docker stop mcp-it
```

Están verificadas con MySQL 8.0 y MariaDB 10.3. Para desplegar un cambio: commit aquí, y luego
`git pull` y `docker compose up -d --build --wait` en `/opt/mcp-osticket`. El detalle está en
[docs/despliegue.md](docs/despliegue.md).
