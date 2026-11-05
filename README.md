server.py  → Publica las herramientas y configura el servidor.

tools.py   → Implementa las operaciones y valida sus argumentos.

db.py      → Gestiona conexiones y ejecuta SQL.

config.py  → Centraliza la configuración.

access.py  → Define las tablas y columnas permitidas para las herramientas.

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

Pruebas (sin conexiones a una base real):

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
```

Checklist:

- [x] 1. Reducir el MCP a cuatro herramientas, sin SQL libre.
- [x] 2. Aplicar la política común de tablas y columnas permitidas.
- [x] 3. Reforzar `db.py`: solo lectura, tiempos máximos y cierre de recursos.
- [ ] 4. Completar el endurecimiento de argumentos y límites de resultados.
- [ ] 5. Uniformar respuestas y errores sin exponer detalles internos.
- [ ] 6. Completar la validación en una base de pruebas aislada. Ya existen pruebas simuladas de acceso, transacciones, errores y recursos.
- [ ] 7. Completar la documentación de configuración, permisos y despliegue.
- [ ] 8. Preparar autenticación, HTTPS y conexión con LibreChat.
