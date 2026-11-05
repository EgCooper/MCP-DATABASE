server.py  → Publica las herramientas y configura el servidor.

tools.py   → Implementa las operaciones y valida sus argumentos.

db.py      → Gestiona conexiones y ejecuta SQL.

config.py  → Centraliza la configuración.

access.py  → Define las tablas y columnas permitidas para las herramientas.

validation.py → Define los argumentos estrictos y sus esquemas MCP.

responses.py → Limita el contenido JSON e informa cualquier recorte.

Herramientas disponibles:

- `test_connection`: verifica la conexión y devuelve la base y la versión de MySQL.
- `list_tables`: lista únicamente las tablas existentes autorizadas en la base configurada.
- `describe_table(table_name)`: muestra únicamente las columnas autorizadas de una tabla permitida.
- `sample_rows(table_name, limit=10)`: devuelve las columnas autorizadas de una muestra de entre 1 y 100 filas.

El MCP utiliza consultas fijas y no ofrece ejecución de SQL libre. Usa una cuenta
MySQL de solo lectura. Cada conexión configura la sesión y abre una transacción
de solo lectura antes de quedar disponible para las consultas.

Política de acceso:

| Área | Tablas autorizadas |
|---|---|
| Tickets | `ost_ticket`, `ost_ticket__cdata`, `ost_ticket_status`, `ost_ticket_priority` |
| Hilos e historial | `ost_thread`, `ost_thread_entry`, `ost_thread_event`, `ost_event` |
| Solicitantes | `ost_user`, `ost_user_email` |
| Agentes y asignaciones | `ost_staff`, `ost_department`, `ost_team`, `ost_team_member` |
| Empresas y catálogos | `ost_list`, `ost_list_items` |
| Clasificación | `ost_help_topic` |

Toda tabla o columna ausente de `src/mcp_mysql/access.py` se rechaza por defecto,
incluidos los campos nuevos. En `ost_staff` se permiten identificadores,
nombres, departamento, estado de actividad, vacaciones y fechas; se excluyen
contraseñas, permisos, contactos personales y campos internos.

Las consultas de estructura y muestras utilizan únicamente las columnas
autorizadas que existen en la base configurada. Si no existe ninguna, devuelven
un error; nunca se utiliza `SELECT *`. Los nombres deben coincidir exactamente
con los definidos en la política, sin prefijos de otra base ni comillas.

La entidad es la empresa del ticket: `ost_ticket__cdata.listaEmpresa`, relacionada
con `ost_list_items`. Se conservan los campos de horas del reporte anterior,
como `time`, `timeExtra`, `horaExtra`, `horaCompensada` y los agentes de apoyo.
Habilitar estos campos todavía no agrega herramientas de cálculo o reportes.

Esta política se aplica a todos los consumidores del MCP. No reproduce los
permisos individuales de osTicket ni filtra filas por usuario, empresa o tipo de
hilo. Los textos autorizados de tickets e hilos pueden contener información
sensible: el servicio debe mantenerse en una red privada controlada hasta
preparar autenticación y autorización del consumidor.

Protecciones de conexión y consulta:

- Se configura `SET SESSION TRANSACTION READ ONLY` y se inicia explícitamente una
  transacción con `readonly=True`. Si falla la configuración de protección, la
  conexión se cierra y no se ejecuta la consulta de la herramienta.
- No se ejecuta `commit()`. Al finalizar se revierte la transacción y se cierran
  cursor y conexión. Si hay resultados pendientes, se desconecta sin descargarlos;
  MySQL revierte la transacción al cerrar la sesión.
- Se deshabilitan el autocommit, la descarga automática de resultados pendientes,
  la capacidad de múltiples sentencias y la carga local de archivos del conector.
- La lectura usa un cursor sin buffer y `fetchmany()`: se solicita el
  límite interno más una fila para detectar excesos. El límite interno es de
  1000 filas; `sample_rows` mantiene su máximo de 100. Un exceso devuelve error,
  nunca un resultado parcial presentado como completo.
- `fetch_one` acepta cero o una fila y rechaza resultados con más de una.
- Los errores de limpieza no reemplazan el error original y siempre se intenta
  cerrar la conexión, incluso si fallan el rollback o el cierre del cursor.

Estas protecciones complementan los permisos de la cuenta: no los sustituyen.
Las transacciones de solo lectura tienen excepciones para tablas temporales;
las herramientas del MCP no ofrecen creación de tablas ni ejecución de SQL libre.
Referencia: [transacciones de solo lectura de MySQL](https://dev.mysql.com/doc/refman/8.4/en/commit.html).

Tiempos de espera opcionales (no hace falta modificar `.env` para usar los valores predeterminados):

| Variable | Predeterminado | Alcance |
|---|---|---|
| `MYSQL_CONNECT_TIMEOUT` | `10` segundos | Establecimiento de conexión |
| `MYSQL_READ_TIMEOUT` | `30` segundos | Espera de lectura del conector |
| `MYSQL_WRITE_TIMEOUT` | `30` segundos | Espera de escritura del conector |
| `MYSQL_QUERY_TIMEOUT_MS` | `15000` milisegundos | `MAX_EXECUTION_TIME` de la sesión MySQL |

Todos deben ser enteros positivos; `0` no permite desactivar los límites. El
tiempo de ejecución se aplica a los `SELECT` de solo lectura compatibles con
`MAX_EXECUTION_TIME`, no al tiempo total de una llamada MCP. Los tiempos del
conector limitan esperas de comunicación, no la duración total de una consulta.
Consulta [MAX_EXECUTION_TIME](https://dev.mysql.com/doc/refman/8.4/en/server-system-variables.html#sysvar_max_execution_time)
y [los tiempos del conector](https://dev.mysql.com/doc/connectors/en/connector-python-connectargs.html).

Se requiere un servidor MySQL que soporte `READ ONLY` y `MAX_EXECUTION_TIME`;
si no los soporta, la operación falla sin quitar las protecciones. Este flujo
no implementa una alternativa para MariaDB. Se requiere Connector/Python 9.2.0
o superior para `read_timeout` y `write_timeout`; después de actualizar ejecuta
`python -m pip install -e '.[dev]'` en tu entorno y reinicia el MCP.

Validación de argumentos y límites de contenido:

- Los esquemas publicados y la validación del servidor exigen los mismos
  argumentos. Se rechazan parámetros desconocidos o ausentes, sin repetir sus
  valores en el mensaje de error. Las herramientas sin argumentos solo aceptan `{}`.
- `table_name` debe ser texto de 1 a 64 caracteres ASCII alfanuméricos o `_`,
  y coincidir con una tabla autorizada. No se normalizan nombres ni se admiten
  prefijos de otra base. La misma restricción se aplica a llamadas Python directas.
- `limit` debe ser un entero de 1 a 100. No se convierten cadenas como `"10"`,
  números decimales como `10.0` ni booleanos como `true` a enteros. Se mantiene el
  valor predeterminado de 10.
- Cada campo de texto devuelve hasta 4000 caracteres. Las consultas SQL acotan
  previamente los campos de texto/binarios y los metadatos potencialmente grandes;
  se pide un carácter o byte adicional para detectar excesos.
- El JSON de contenido de cada herramienta tiene un máximo de 64 KiB, contando
  Unicode y caracteres escapados. La envoltura del protocolo MCP/HTTP es adicional.
  El contenido se envía una sola vez como bloque de texto JSON, sin duplicarlo como
  salida estructurada. Se requiere MCP SDK 1.10.0 o superior y menor que 2.
- Si se supera el presupuesto, se conserva un prefijo de filas completas y se
  actualiza `row_count` con las filas efectivamente devueltas. Si una sola fila
  es demasiado grande, sus textos se acortan más, conservando sus valores numéricos
  y el nombre de tabla. El documento JSON nunca se corta como texto bruto.

Cuando hay un recorte se agregan `truncated: true` y `truncation`:

```json
{
  "truncated": true,
  "truncation": {
    "field_count": 1,
    "field_paths": ["rows[0].body"],
    "omitted_rows": 5,
    "response_limited": true
  }
}
```

`field_count` cuenta los campos acortados en el contenido devuelto; se detallan
hasta 32 rutas y, si faltan detalles, aparece `unlisted_field_count`.
`omitted_rows` se incluye únicamente si se omitieron filas por el tamaño de la
respuesta; cuenta filas de la muestra obtenida, no todos los registros de la base.
El formato también informa `omitted_columns` o `omitted_tables` si una lista de
metadatos supera el presupuesto. `response_limited` distingue el ajuste por tamaño
total del límite individual de campo. Las respuestas sin recortes conservan su
estructura anterior y no agregan estos indicadores.

Pruebas (sin conexiones a una base real):

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
```

Checklist:

- [x] 1. Reducir el MCP a cuatro herramientas, sin SQL libre.
- [x] 2. Aplicar la política común de tablas y columnas permitidas.
- [x] 3. Reforzar `db.py`: solo lectura, tiempos máximos y cierre de recursos.
- [x] 4. Completar el endurecimiento de argumentos y límites de resultados.
- [ ] 5. Uniformar respuestas y errores sin exponer detalles internos.
- [ ] 6. Completar la validación en una base de pruebas aislada. Ya existen pruebas simuladas de acceso, transacciones, errores y recursos.
- [ ] 7. Completar la documentación de configuración, permisos y despliegue.
- [ ] 8. Preparar autenticación, HTTPS y conexión con LibreChat.
