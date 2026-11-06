# Despliegue del MCP osTicket con LibreChat

Guía de operación para el servidor donde corren LibreChat y el MCP. Ejecuta los comandos
con tu usuario normal, no como `root`: los archivos de `/opt` son tuyos y git rechaza a
veces repositorios que pertenecen a otro usuario.

## Cómo está armado

| Qué | Dónde | Notas |
|-----|-------|-------|
| Código de desarrollo del MCP | `~/Documents/MCP-DATABASE` | Aquí se edita, se prueba y se hace commit |
| Copia desplegada del MCP | `/opt/mcp-osticket` | Clon de git del anterior. **No se edita a mano** |
| LibreChat | `/opt/librechat` | Proyecto compose `librechat` |
| Contenedor del MCP | `mcp-osticket` | Red `librechat_default`, sin puertos publicados |
| Contenedor de LibreChat | `LibreChat` | Con mayúsculas: Docker distingue mayúsculas y minúsculas |

```
~/Documents/MCP-DATABASE ──git commit──▶ rama mysql
                                            │ git pull
                                            ▼
                               /opt/mcp-osticket ──docker compose up --build──▶ contenedor mcp-osticket
                                                                                     ▲ token
                               /opt/librechat ──────────────────────────────▶ contenedor LibreChat
```

`/opt/mcp-osticket` trae los cambios desde `~/Documents/MCP-DATABASE`, que es su `origin`.
Solo viaja lo que tiene commit. El `.env` no viaja por git: se copia a mano.

---

## 1. Desplegar un cambio del MCP

```bash
# 1. En desarrollo: probar y guardar el cambio
cd ~/Documents/MCP-DATABASE
.venv/bin/python -m pytest -q
git add -A && git commit -m "Describe el cambio"

# 2. En el despliegue: traer el commit, reconstruir y esperar a que esté sano
cd /opt/mcp-osticket
git pull
docker compose up -d --build --wait

# 3. Que LibreChat se reconecte y vuelva a leer las herramientas
docker restart LibreChat

# 4. Verificar
docker logs LibreChat 2>&1 | grep "\[MCP\] Initialized" | tail -1    # debe decir 13 tools
```

- `--build` reconstruye la imagen con el código nuevo. Sin esta opción, compose reutiliza la
  imagen anterior.
- `--wait` no termina hasta que el MCP pasa su chequeo de salud. Así LibreChat nunca intenta
  conectarse antes de tiempo.
- LibreChat se reinicia **después** del MCP, siempre.

---

## 2. Cambiar la configuración (`.env`)

El `.env` de `/opt/mcp-osticket` tiene la conexión a la base y el token. No se reconstruye
la imagen, solo se recrea el contenedor:

```bash
cp ~/Documents/MCP-DATABASE/.env /opt/mcp-osticket/.env
chmod 600 /opt/mcp-osticket/.env
cd /opt/mcp-osticket && docker compose up -d --wait
docker restart LibreChat
```

### Cambiar el token entre LibreChat y el MCP

El mismo valor va en `MCP_AUTH_TOKEN` (MCP) y en `MCP_OSTICKET_TOKEN` (LibreChat):

```bash
TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
sed -i "s|^MCP_AUTH_TOKEN=.*|MCP_AUTH_TOKEN=$TOKEN|" /opt/mcp-osticket/.env ~/Documents/MCP-DATABASE/.env
sed -i "s|^MCP_OSTICKET_TOKEN=.*|MCP_OSTICKET_TOKEN=$TOKEN|" /opt/librechat/.env
unset TOKEN
cd /opt/mcp-osticket && docker compose up -d --wait
docker restart LibreChat
```

Para comprobar que coinciden sin mostrar el token, las dos huellas deben ser iguales:

```bash
grep '^MCP_AUTH_TOKEN='     /opt/mcp-osticket/.env | cut -d= -f2- | sha256sum | cut -c1-12
grep '^MCP_OSTICKET_TOKEN=' /opt/librechat/.env    | cut -d= -f2- | sha256sum | cut -c1-12
```

---

## 3. Verificar y diagnosticar

```bash
docker ps --format '{{.Names}}\t{{.Status}}'                       # mcp-osticket debe estar "healthy"
docker logs LibreChat 2>&1 | grep "\[MCP\]" | tail -15             # conexión de LibreChat al MCP
docker logs mcp-osticket --since 1h 2>&1 | grep tool_call          # auditoría: cada consulta del modelo
docker logs mcp-osticket --since 1h 2>&1 | grep -c http_unauthorized   # rechazos por token
docker compose -f /opt/mcp-osticket/compose.yaml logs -f           # seguir los logs en vivo
```

Cada línea `tool_call` muestra `request_id`, la herramienta, el resultado y la duración, sin
datos de clientes.

### Problemas conocidos

| Síntoma | Causa | Solución |
|---------|-------|----------|
| `[MCP] Initialized with 1 configured server and 0 tools` | LibreChat arrancó antes que el MCP | `docker restart LibreChat` |
| `OAuth Required: true` y 0 herramientas | Falta `requiresOAuth: false` en `librechat.yaml` | Agregar la línea y reiniciar LibreChat |
| Muchos `http_unauthorized` en el MCP | Los tokens no coinciden, o LibreChat no tiene la variable | Comparar las huellas (sección 2) y reiniciar LibreChat |
| `network librechat_default not found` al levantar el MCP | LibreChat no está levantado | Levantar LibreChat primero (sección 5) |
| `mcp-osticket` en estado `unhealthy` | El proceso no responde | `docker logs mcp-osticket --tail 50` |
| Las herramientas responden `DATABASE_UNAVAILABLE` o `DATABASE_TIMEOUT` | No se llega a la base de osTicket | Revisar la red y el Security Group de AWS |

---

## 4. Volver a una versión anterior del MCP

```bash
cd /opt/mcp-osticket
git log --oneline -10                  # elegir el commit al que volver
git checkout <commit>
docker compose up -d --build --wait
docker restart LibreChat

# para volver a la última versión
git checkout mysql && git pull
docker compose up -d --build --wait
docker restart LibreChat
```

---

## 5. Apagar y encender

Ambos se reinician solos si el servidor se reinicia (`restart: unless-stopped`). Para hacerlo
a mano:

```bash
# Apagar: primero el MCP, que está conectado a la red de LibreChat
cd /opt/mcp-osticket && docker compose down
cd /opt/librechat    && docker compose -p librechat down       # nunca con -v: borraría los datos

# Encender: primero LibreChat, que crea la red, luego el MCP y por último reiniciar LibreChat
cd /opt/librechat    && docker compose -p librechat up -d
cd /opt/mcp-osticket && docker compose up -d --build --wait
docker restart LibreChat
```

---

## 6. Usuarios de LibreChat

El registro público está cerrado (`ALLOW_REGISTRATION=false` en `/opt/librechat/.env`). Las
cuentas las crea el administrador:

```bash
docker exec -it LibreChat npm run create-user -- correo@empresa.com "Nombre Apellido" usuario
docker exec -it LibreChat npm run list-users
docker exec -it LibreChat npm run reset-password
docker exec -it LibreChat npm run ban-user
docker exec -it LibreChat npm run delete-user
```

`create-user` pide la contraseña de forma interactiva.

---

## 7. Desplegar desde cero en un servidor nuevo

1. Instalar Docker y habilitarlo al arranque: `sudo systemctl enable --now docker`.
2. LibreChat en `/opt/librechat`, en la versión probada `v0.8.8`, con su `.env` (incluido
   `MCP_OSTICKET_TOKEN` y `ALLOW_REGISTRATION=false`) y su `librechat.yaml` con este bloque:
   ```yaml
   mcpSettings:
     allowedAddresses:
       - 'mcp-osticket:8000'
   mcpServers:
     mysql:
       type: streamable-http
       url: http://mcp-osticket:8000/mcp
       headers:
         Authorization: "Bearer ${MCP_OSTICKET_TOKEN}"
       requiresOAuth: false
       title: osTicket
       description: Consultas de solo lectura sobre tickets, hilos, clientes y agentes de osTicket.
       serverInstructions: true
       timeout: 60000
   ```
   ```bash
   cd /opt/librechat && docker compose -p librechat up -d
   ```
3. Clonar el MCP y crear su `.env`, con la base de datos y `MCP_AUTH_TOKEN` (ver
   `.env.example`):
   ```bash
   sudo install -d -o "$USER" -g "$USER" /opt/mcp-osticket
   git clone --branch mysql git@github.com:EgCooper/MCP-DATABASE.git /opt/mcp-osticket
   cp /ruta/segura/.env /opt/mcp-osticket/.env && chmod 600 /opt/mcp-osticket/.env
   cd /opt/mcp-osticket && docker compose up -d --build --wait
   ```
4. `docker restart LibreChat` y verificar que diga `13 tools` (sección 3).
5. Permitir la IP del servidor en el Security Group de la base y en la cuenta de MariaDB
   (`python -m mcp_mysql grants`).

---

## Pendientes de seguridad de este despliegue

- LibreChat (3080) y su panel de administración (3000) están publicados en `0.0.0.0`.
  Conviene poner un proxy con HTTPS delante y dejar el panel accesible solo localmente.
- La conexión a la base de osTicket no va cifrada (TLS desactivado en MariaDB). Está
  reportado al administrador.
