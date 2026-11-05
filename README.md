server.py  → Publica las herramientas y configura el servidor.

tools.py   → Implementa las operaciones y valida sus argumentos.

db.py      → Gestiona conexiones y ejecuta SQL.

config.py  → Centraliza la configuración.

Herramientas disponibles:

- `test_connection`: verifica la conexión y devuelve la base y la versión de MySQL.
- `list_tables`: lista las tablas de la base configurada.
- `describe_table(table_name)`: muestra las columnas de una tabla.
- `sample_rows(table_name, limit=10)`: devuelve una muestra de entre 1 y 100 filas.

El MCP utiliza consultas fijas y no ofrece ejecución de SQL libre. Usa una cuenta
MySQL de solo lectura. El refuerzo de transacciones, tiempos máximos y acceso a
tablas se implementará en los siguientes pasos.
