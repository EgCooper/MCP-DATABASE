# Checklist de pendientes del proyecto

Revisión: 10 de noviembre de 2026. Alcance: código, pruebas, configuración Docker y documentación del repositorio. No se verificó la instalación productiva ni se consultó la base real.

Este listado distingue brechas observadas de mejoras propuestas. No hay un backlog explícito de TODO/FIXME en el código; las tareas siguientes surgen de la revisión y deben priorizarse con el responsable del servicio.

## Base ya implementada

- [x] Servidor MCP de solo lectura con HTTP y stdio; 13 herramientas de negocio y 3 de exploración opcionales.
- [x] Búsquedas, conteos, detalle e hilos de tickets; clientes, empresas, agentes y reportes de horas.
- [x] Consultas parametrizadas, validación estricta y política de tablas/columnas permitidas.
- [x] Token HTTP, protección del encabezado Host, errores sanitizados y auditoría por llamada.
- [x] Transacciones de solo lectura, límites de filas/respuesta, tiempos máximos y pool de conexiones.
- [x] Contenedor sin privilegios, guía de despliegue y suite unitaria/de integración.

## P1 — Completitud y exactitud de las respuestas

- [x] **Permitir continuar los reportes por grupos.** Implementados `offset`, `next_offset`, límite de paginación explícito y ajuste de continuación ante recorte por bytes. Orden determinista cuando los datos no cambian; la documentación aclara que no hay snapshot entre llamadas. Pruebas unitarias y SQL real cubren más de 100 grupos y continuidad sin duplicados. Referencias: `src/mcp_mysql/tickets.py`, `src/mcp_mysql/validation.py`, `src/mcp_mysql/responses.py`, `tests/test_p1_pagination.py`, `tests/test_mysql_integration.py`.
- [x] **Informar los recortes del perfil de cliente.** Implementados `emails_offset`, `companies_offset` y metadatos de paginación independientes. Se recuperan todos los correos y empresas, contando correctamente el grupo sin empresa para avanzar. Pruebas con 23 correos y 12 empresas. Referencias: `src/mcp_mysql/tickets.py`, `src/mcp_mysql/tools.py`, `tests/test_p1_pagination.py`, `tests/test_mysql_integration.py`.
- [x] **Unificar los campos no disponibles en perfiles.** Las secciones no disponibles devuelven `null` y `unavailable_fields`; se conserva la diferencia con listas vacías. Incluye campos del usuario, correo principal, empresas, colaboradores y resumen por estado, con pruebas de esquemas parciales. Referencias: `src/mcp_mysql/tickets.py`, `tests/test_p1_pagination.py`.

## P1 — Validaciones para entregar cambios con confianza

- [x] **Automatizar las pruebas en CI.** Agregado workflow para push/PR con Python 3.11, 3.13 y 3.14, integración con servicios desechables MySQL 8.0/MariaDB 10.3 y artefactos JUnit. YAML validado localmente; su primera ejecución en GitHub queda por observar al publicar el cambio. Referencia: `.github/workflows/tests.yml`.
- [x] **Validar el transporte HTTP de extremo a extremo.** Prueba con servidor Uvicorn sobre TCP local y cliente SDK MCP: inicialización, 13 herramientas, llamada válida, argumentos inválidos, rechazo de tokens y terminación de sesión mediante DELETE. No requiere base real. Referencia: `tests/test_http_integration.py`.
- [ ] **Completar la aceptación real de las 30 preguntas en LibreChat/modelo.** Ya están implementados el generador de registros y el validador con fecha, commit, configuración, dataset, resultados y evidencias. El cierre con `--require-pass` exige los 30 casos aprobados y documentados. Falta ejecutar las preguntas y guardar sus evidencias: se necesita acceso al entorno, modelo y dataset de pruebas. Referencias: `scripts/acceptance.py`, `docs/aceptacion.md`, `docs/banco-de-preguntas.md`.

## P2 — Operación, rendimiento y mantenimiento

- [ ] **Separar salud del proceso y disponibilidad de la base.** `/health` responde OK sin consultar MySQL; el contenedor puede estar healthy con la base inaccesible. Es válido como liveness, pero falta una comprobación de disponibilidad para operación. Cierre: mantener el chequeo liviano y agregar readiness o una sonda autenticada con timeout y sin datos sensibles. Referencias: `src/mcp_mysql/server.py:279`, `Dockerfile`.
- [ ] **Medir carga y saturación.** Existen límites de conexiones y espera, pero no se encontraron pruebas de carga ni un presupuesto de latencia/memoria. Cierre: medir consultas concurrentes, agotamiento de conexiones, recuperación ante caída de BD y consumo con el límite de 256 MB; documentar parámetros recomendados según resultados. Referencias: `src/mcp_mysql/db.py`, `compose.yaml`.
- [ ] **Revisar planes de las consultas más costosas.** Búsquedas por subcadena, extracción de empresa desde texto, agregados de horas y paginación por offset merecen medición con volúmenes representativos. No se constató lentitud. Cierre: registrar planes y tiempos, y proponer índices o ajustes respaldados por esas mediciones. Referencia: `src/mcp_mysql/tickets.py`.
- [ ] **Fijar dependencias e imágenes para releases reproducibles.** `pyproject.toml` usa rangos y Docker instala al construir; la imagen base y la aplicación usan etiquetas variables. Cierre: versionar una resolución reproducible y publicar imágenes identificables por versión/commit, con procedimiento de actualización y rollback. Referencias: `pyproject.toml`, `Dockerfile`, `compose.yaml`.
- [ ] **Agregar monitoreo y alertas operativas.** Hay logs de llamadas y rotación local, pero no configuración de alertas en el repositorio. Cierre: detectar indisponibilidad, errores/timeouts y rechazos de autenticación; definir retención y acceso a logs, y comprobar que la auditoría llega al destino elegido. Referencias: `src/mcp_mysql/server.py`, `compose.yaml`, `docs/despliegue.md`.
- [ ] **Documentar y verificar TLS hasta MySQL.** El soporte existe, pero es opcional y Compose no proporciona un montaje del archivo CA. No se verificó si producción usa TLS. Cierre: documentar montaje del CA, habilitar verificación de identidad donde corresponda y comprobar rechazo de certificados/hosts inválidos. Referencias: `src/mcp_mysql/config.py`, `.env.example`, `compose.yaml`.
- [ ] **Definir compatibilidad y versionado del contrato.** Se depende de detalles internos de FastMCP, nombres `ost_*` y campos personalizados de una instalación. Cierre: declarar versiones soportadas de Python, MCP, MySQL/MariaDB y osTicket, ejecutar la matriz acordada y registrar cambios del contrato de herramientas/respuestas. Referencias: `pyproject.toml`, `src/mcp_mysql/access.py`, `README.md`.

## P3 — Decisiones de alcance, si cambia el uso actual

- [ ] **Confirmar si todos los consumidores deben compartir acceso.** Hoy hay un token global y todos los agentes ven todos los tickets y notas internas; está documentado como comportamiento actual. Si se requieren restricciones, diseñar identidad por consumidor/usuario, autorización por ticket/departamento y auditoría atribuible. No es un fallo respecto al alcance documentado. Referencias: `README.md`, `src/mcp_mysql/server.py`.
- [ ] **Decidir si se necesita lectura completa de textos largos.** Los cuerpos y campos se recortan con aviso; no hay continuación del contenido de un campo. Si se necesita recuperar una conversación íntegra para análisis, definir un acceso acotado a fragmentos y sus pruebas. Referencias: `src/mcp_mysql/responses.py`, `src/mcp_mysql/tickets.py:612`.
- [ ] **Evaluar modularizar las consultas.** `tickets.py` concentra esquema, filtros, tickets, personas, catálogos y reportes. Si aumenta el alcance, dividir por responsabilidad conservando las pruebas del contrato. Es mantenimiento propuesto, no una falla funcional.

## Verificación de esta revisión

- Comando: `.venv/bin/python -m pytest -q`.
- Resultado inicial de la revisión: **443 pruebas aprobadas y 17 omitidas**.
- Tras implementar P1 se ejecutó toda la suite contra MySQL 8.0 desechable: **494 pruebas aprobadas**, sin omisiones. También se ejecutó contra MariaDB 10.3 desechable: **493 aprobadas** antes de agregar una prueba adicional del validador de aceptación.
- Se ejecutaron las pruebas SQL de integración en bases ficticias; no se consultó la base real ni se desplegaron los cambios.
- Dentro del aislamiento, la suite se bloqueó en una llamada asyncio/AnyIO. Al repetir fuera del aislamiento pasó; no se registra ese bloqueo como defecto confirmado del proyecto.
- Las tareas de aceptación productiva, TLS y carga quedan abiertas porque no se inspeccionó la infraestructura desplegada.

Orden sugerido: completitud de reportes/perfiles → pruebas y aceptación automatizadas → disponibilidad y medición de carga → releases y monitoreo → ampliaciones de alcance.
