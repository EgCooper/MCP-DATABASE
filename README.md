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
MySQL de solo lectura. El refuerzo de transacciones y tiempos máximos se
implementará en los siguientes pasos.

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

Pruebas (sin conexiones a una base real):

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
```

Checklist:

- [x] 1. Reducir el MCP a cuatro herramientas, sin SQL libre.
- [x] 2. Aplicar la política común de tablas y columnas permitidas.
- [ ] 3. Reforzar `db.py`: solo lectura, tiempos máximos y cierre de recursos.
- [ ] 4. Completar el endurecimiento de argumentos y límites de resultados.
- [ ] 5. Uniformar respuestas y errores sin exponer detalles internos.
- [ ] 6. Ampliar las pruebas a transacciones, errores y recursos. Ya existen pruebas de acceso.
- [ ] 7. Completar la documentación de configuración, permisos y despliegue.
- [ ] 8. Preparar autenticación, HTTPS y conexión con LibreChat.
