# MCP Database

Permite consultar las bases de datos de soporte (MySQL/osTicket, Oracle, SQL Server, PostgreSQL e Informix) pidiéndoselo a Claude con tus palabras, por ejemplo *"dame el reporte de horas de septiembre"*.

Es **solo de lectura**: Claude puede consultar, pero no modificar, borrar ni crear datos.

## Antes de empezar

Necesitas:

- **Claude Code**, instalado y con tu sesión iniciada ([descargar](https://claude.com/claude-code)). Instálalo antes de ejecutar el instalador de este proyecto.
- **Git** ([descargar](https://git-scm.com/downloads)).
- **Acceso a la red de la base de datos** (la VPN, si corresponde).
- **Los datos de conexión** de un usuario de solo lectura: servidor, base de datos, usuario y contraseña. Pídeselos a tu responsable.
- **Solo si vas a usar SQL Server o Informix:** el driver ODBC instalado ([cómo instalarlo](docs/DESARROLLO.md#drivers-para-sql-server-e-informix)).

No hace falta instalar Python ni tener permisos de administrador: el instalador se encarga de todo.

## Instalación

### 1. Descarga el proyecto

Abre una terminal (en Windows, **PowerShell**) y ejecuta:

```
git clone https://github.com/EgCooper/MCP-DATABASE.git
```

Se crea la carpeta `MCP-DATABASE`. Déjala siempre en el mismo lugar; si algún día la mueves, vuelve a ejecutar el instalador.

### 2. Ejecuta el instalador

**Windows:** en la misma terminal, ejecuta:

```
.\MCP-DATABASE\resources\Scripts\setup_claude_code.cmd
```

(o haz doble clic en `setup_claude_code.cmd`, dentro de la carpeta `MCP-DATABASE\resources\Scripts`).

**Linux / macOS:**

```
./MCP-DATABASE/resources/Scripts/setup_claude_code.sh
```

### 3. Responde las preguntas

1. **Qué bases vas a usar.** Escribe el número de cada una (por ejemplo `1` para MySQL/osTicket, o `1,4` para dos) o presiona Enter para aceptar la sugerida.
2. **Espera la instalación.** La primera vez tarda uno o dos minutos.
3. **Ingresa los datos de conexión** de cada base. Presiona Enter para mantener el valor que aparece entre corchetes. La contraseña no se ve mientras la escribes; es normal.
4. El instalador **prueba la conexión** y deja todo configurado en Claude Code. Al final debes ver algo así:

   ```
   OK: conectado a osticket
   OK    mysql: registrado y conectado
   ```

   Si la conexión falla, te muestra el error y te ofrece corregir los datos.

### 4. Pruébalo

Abre Claude Code (si ya estaba abierto, ciérralo y vuelve a abrirlo) y escribe:

> prueba la conexión a mysql

## Qué puedo pedir

Escríbele a Claude como le escribirías a un compañero. Por ejemplo:

- *"Dame el reporte de horas de septiembre de 2026."*
- *"¿Cuántas horas extra y horas compensadas hubo en agosto, por agente?"*
- *"Busca el ticket 123456 y dime su estado."*
- *"¿Qué tablas de la base de osTicket tienen que ver con tickets?"*
- Si tienes varias bases Oracle: *"En la base QA, lista las tablas de clientes."*

## Cambiar datos o actualizar

Vuelve a ejecutar el instalador (paso 2) cuando necesites:

- **Cambiar una contraseña u otro dato:** responde `s` cuando te pregunte si quieres cambiar los datos. Lo demás se mantiene con Enter.
- **Agregar otra base:** elígela en el menú.
- **Instalar una versión nueva:** antes, entra a la carpeta y descarga los cambios con `cd MCP-DATABASE` y `git pull`.
- **Mover la carpeta** a otro lugar.

Después, reinicia Claude Code.

## Si algo falla

| Qué ves | Qué hacer |
|---|---|
| `ERROR` al probar la conexión | Revisa los datos y que estés conectado a la VPN. El instalador te ofrece corregirlos ahí mismo. |
| `No se encontro Claude Code` | Instala Claude Code, inicia sesión y vuelve a ejecutar el instalador. |
| Windows: un mensaje sobre *"Control de aplicaciones"* o *Smart App Control* | Windows está bloqueando archivos de Python. Pide ayuda a TI ([detalles](docs/DESARROLLO.md#windows-smart-app-control)). |
| Windows: PowerShell no deja ejecutar el instalador | Tu empresa bloquea los scripts por directiva. Pide a TI que lo habilite. |
| Claude dice que no tiene acceso a la base | En una terminal, ejecuta `claude mcp list`. Si la base aparece con `Failed`, vuelve a ejecutar el instalador. |
| Linux: el instalador no encuentra Claude Code aunque está instalado | Si usas la terminal de VS Code, prueba desde la terminal del sistema. |

Si sigue sin funcionar, envía a tu responsable una captura de lo que muestra el instalador.

## Seguridad

- Tus datos de conexión se guardan **solo en tu equipo**, en el archivo `.env` de la carpeta `MCP-DATABASE`. No lo compartas ni lo envíes a nadie.
- Usa siempre un usuario de base de datos de **solo lectura**.

## Para desarrolladores

El instalador configura las bases en Claude Code. Para usarlas desde otro asistente (Cursor, VS Code, Claude Desktop…), instalar a mano, ver qué hace el instalador paso a paso o conocer las tools disponibles, consulta la [documentación técnica](docs/DESARROLLO.md).
