# Aceptación con LibreChat y un modelo real

La suite automática comprueba contratos, SQL y el protocolo MCP. La aceptación de
lenguaje natural requiere ejecutar las 30 preguntas del banco con el modelo elegido
y contrastarlas con osTicket. El validador de registros comprueba que exista evidencia;
la evaluación del contenido corresponde al revisor.

## Preparar una ejecución

Usar una instalación de pruebas, con datos ficticios que incluyan un ticket con notas
internas, un hilo largo, dos agentes llamados Ana y un mensaje con una instrucción
maliciosa. El caso 29 debe contener esa instrucción dentro del mensaje del ticket,
no como una orden del usuario al asistente. Registrar el dataset o snapshot empleado.
No ejecutar fixtures de integración contra producción.

Generar un registro nuevo para cada combinación de versión, dataset y modelo:

```bash
.venv/bin/python scripts/acceptance.py init \
  --librechat-url http://localhost:3080 \
  --librechat-version VERSION_O_COMMIT \
  --provider PROVEEDOR --model MODELO_Y_VERSION \
  --model-settings 'temperatura=0; instrucciones adicionales=ninguna' \
  --dataset IDENTIFICADOR_DEL_SNAPSHOT --reviewer RESPONSABLE \
  --output /tmp/aceptacion-osticket.json
```

El registro conserva los 30 escenarios, el comportamiento esperado, la fecha UTC,
el commit del MCP, si hay cambios locales y la huella del banco. Se crea en estado
`pending`: generar el archivo no ejecuta preguntas ni acredita su aprobación.
Usar un commit limpio para una aceptación final reproducible.

## Ejecutar y registrar

1. Verificar la conexión de LibreChat y sus 13 herramientas. Guardar la configuración
   del modelo (temperatura, instrucciones adicionales y proveedor/versiones) junto al
   registro, sin tokens ni contraseñas. Usar las instrucciones del servidor MCP.
2. Sustituir los valores de ejemplo del banco por los del dataset. En los casos
   26–30 escribir en `prompt` la pregunta concreta que reproduce la situación.
3. Consultar osTicket directamente para completar `verified_expected`, incluyendo
   los valores concretos y la fecha/zona horaria de las consultas temporales.
4. Enviar cada pregunta en una conversación nueva para evitar contaminación entre
   casos; guardar en `observed` la respuesta y en `tool_calls` las llamadas reales
   como `{"name": "get_ticket", "arguments": {"number": "012345"}}`.
   Usar `[]` cuando no se llamó ninguna herramienta.
5. Registrar `executed_at` en ISO 8601 con zona horaria, y en `evidence` una referencia
   al transcript anonimizado y al contraste con osTicket. Revisar respuesta y llamadas;
   marcar `passed`, `failed` o `blocked`, explicando el motivo en `observed`.
6. Revisar especialmente: desambiguación (26), no inventar tickets (27), aviso de
   información incompleta (28), ignorar instrucciones del ticket (29), usar conteos
   exactos (30) y exposición correcta de notas internas (12). Para reportes completos,
   seguir `next_offset`; para perfiles, seguir ambas paginaciones independientes.

## Validar el registro

```bash
.venv/bin/python scripts/acceptance.py check /tmp/aceptacion-osticket.json
.venv/bin/python scripts/acceptance.py check /tmp/aceptacion-osticket.json --require-pass
```

El primer comando permite registros parciales y muestra los estados. El segundo
falla si alguno de los 30 casos no pasó o carece de resultado, fecha o evidencia.
Guardar el registro y sus evidencias anonimizadas en el repositorio o ubicación de
QA acordada, bajo control de acceso. Nunca guardar credenciales ni conversaciones
reales con datos personales en Git.

La ejecución real sigue pendiente hasta contar con acceso al entorno de LibreChat,
el modelo y el dataset de pruebas; las pruebas automáticas no sustituyen esa ejecución.
