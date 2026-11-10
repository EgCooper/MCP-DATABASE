# Despliegue del MCP osTicket con LibreChat

Guía de operación para el servidor donde corren LibreChat y el MCP. Ejecuta los comandos
con tu usuario normal, no como `root`: los archivos de `/opt` son tuyos y git rechaza a
veces repositorios que pertenecen a otro usuario.

Este repositorio publica el servidor MCP, un único `compose.yaml`, sus dependencias y
sus pruebas. Los informes, evidencias, checklist y entornos auxiliares se conservan
en `extras/`, una carpeta local excluida de Git y de la imagen Docker. La integración específica de LibreChat/MiniMax se entrega
como un paquete independiente; actualizar el MCP no modifica la imagen de LibreChat.

## Cómo está armado

| Qué | Dónde | Notas |
|-----|-------|-------|
| Código de desarrollo del MCP | `~/Documents/MCP-DATABASE` | Aquí se edita, se prueba y se hace commit |
| Copia desplegada del MCP | `/opt/mcp-osticket` | Clon de git del anterior. **No se edita a mano** |
| LibreChat | `/opt/librechat` | Proyecto compose `librechat` |
| Contenedor del MCP | `mcp-osticket` | Red `librechat_default`, sin puertos publicados |
| Contenedor de LibreChat | `LibreChat` | Con mayúsculas: Docker distingue mayúsculas y minúsculas. Solo en `127.0.0.1:3080` |
| Panel de administración | `admin-panel` | Solo en `127.0.0.1:3000` |
| Proxy HTTPS | `caddy` | Parte del proyecto `librechat`. Publica 80 y 443. Configuración en `/opt/librechat/caddy/Caddyfile` |

**Dirección para los usuarios:** `https://192.168.100.221`

```
PCs de la red ──HTTPS 443──▶ caddy ──▶ LibreChat (127.0.0.1:3080) ──token──▶ mcp-osticket ──▶ MariaDB osTicket
                                        admin-panel (127.0.0.1:3000)

~/Documents/MCP-DATABASE ──git commit──▶ rama mysql ──git pull──▶ /opt/mcp-osticket ──docker compose up --build──▶ mcp-osticket
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
git pull --ff-only
docker compose up -d --build --wait

# 3. Que LibreChat se reconecte y vuelva a leer las herramientas
docker restart LibreChat

# 4. Verificar
docker logs LibreChat 2>&1 | grep "\[MCP\] Initialized" | tail -1    # mysql: 15 herramientas de negocio
```

- `--build` reconstruye la imagen con el código nuevo. Sin esta opción, compose reutiliza la
  imagen anterior.
- `--wait` no termina hasta que el MCP pasa su chequeo de salud. Así LibreChat nunca intenta
  conectarse antes de tiempo.
- LibreChat se reinicia **después** del MCP, siempre.

### Integración independiente con LibreChat/MiniMax

Las correcciones de tipos de IDs y salida visible de MiniMax requieren la imagen
adaptada de LibreChat y `reasoning_split: true`. Su código se conserva en el paquete
local `extras/.local-artifacts/librechat-p3.tar.gz`, excluido del repositorio MCP. Si se
despliega en otro host, transferir también ese archivo; `git pull` no lo descarga.

Para construir la imagen desde el paquete en este servidor:

```bash
mkdir -p "$HOME/.local/share/librechat-osticket"
tar -xzf /home/vpinto/Documents/MCP-DATABASE/extras/.local-artifacts/librechat-p3.tar.gz \
  -C "$HOME/.local/share/librechat-osticket"
cd "$HOME/.local/share/librechat-osticket/librechat-p3"
docker build -f deploy/librechat/Dockerfile -t librechat:osticket-mcp-adapter .
```

El paquete contiene las pruebas del adaptador, un fragmento `minimax-profile.yaml`
y un override de imagen. Fusionar el fragmento con `/opt/librechat/librechat.yaml`,
conservando tokens y servidores existentes. El perfil se llama **Soporte osTicket**.
No reemplazar la configuración completa por el fragmento. El adaptador conserva la
validación del MCP y entrega el texto al finalizar cada llamada del modelo.

Se puede usar el override del paquete junto con los dos Compose actuales de LibreChat:

```bash
cp compose.override.yaml /opt/librechat/docker-compose.osticket.yml
docker compose -p librechat \
  -f /opt/librechat/docker-compose.yml \
  -f /opt/librechat/docker-compose.override.yml \
  -f /opt/librechat/docker-compose.osticket.yml \
  up -d --no-deps --no-build --pull never --wait api
```

Para conservar esa imagen en futuras actualizaciones, volver a incluir los tres
archivos. Guardar la imagen y configuración anteriores antes de reemplazarlas.

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

### TLS hacia MySQL

El MCP acepta `MYSQL_SSL_CA` y `MYSQL_SSL_VERIFY_IDENTITY=true`. En Docker, montar
la CA verificada como archivo de solo lectura en el servicio `mcp-osticket` del
único `compose.yaml`, por ejemplo:

```yaml
volumes:
  - /ruta/host/mysql-ca.pem:/certs/mysql-ca.pem:ro
```

Configurar `MYSQL_SSL_CA=/certs/mysql-ca.pem` en `.env`; el UID 10001 del contenedor
debe poder leer el archivo. El certificado debe corresponder al `MYSQL_HOST` real.
Después recrear el MCP y comprobar `/ready` y `test_connection`.

### Disponibilidad y métricas

`/health` comprueba que el proceso esté vivo. `/ready` comprueba la conexión de solo
lectura a la base y requiere el token HTTP; devuelve 200 o 503. `/metrics` también
requiere token y expone contadores y tiempos sin datos de tickets. Estos endpoints
pertenecen al MCP y no requieren levantar Prometheus ni otro contenedor.

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
| Sospecha de un problema con las conexiones reutilizadas | — | Desactivar el pool con `MCP_DB_POOL_SIZE=0` en `.env` y ejecutar `docker compose up -d --wait` (sección 2) |
| `tlsv1 alert internal error` al entrar por `https://IP` | Falta `default_sni` en el Caddyfile: al entrar por IP no se envía nombre | Agregar la opción global (sección 6) |
| Caddy responde `config is unchanged` tras editar el Caddyfile | El contenedor ve una versión vieja (montaje de archivo individual) | Montar la carpeta `./caddy:/etc/caddy:ro`, no el archivo |
| `caddy` en `Restarting` y log `open /etc/caddy/Caddyfile: no such file` | El montaje apunta a una ruta inexistente; Docker crea una carpeta vacía con ese nombre | Corregir el montaje y borrar la carpeta vacía con `sudo rmdir` |
| `curl: (77) error adding trust anchors` | No se puede leer `caddy-root-ca.crt` (dueño `root`, permisos 600) | `sudo chmod 644 /opt/librechat/caddy-root-ca.crt` |
| El navegador dice "conexión no privada" | La PC no tiene instalado el certificado raíz de Caddy | Instalarlo (sección 6) |

Para diagnosticar con `curl`, usa `-sS` y no `-s`: `-s` solo oculta los errores.

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

## 6. HTTPS (Caddy) y puertos

Caddy recibe el HTTPS y reenvía a LibreChat por la red interna de Docker. LibreChat y el
panel de administración solo escuchan en `127.0.0.1`, así que desde la red no se puede
entrar a ellos sin pasar por Caddy.

Docker publica los puertos por fuera de firewalld, así que **firewalld no sirve para
cerrarlos**. El cierre real es ligarlos a `127.0.0.1` en el compose.

### Configuración

`/opt/librechat/caddy/Caddyfile`:
```caddyfile
{
	# Al entrar por IP no se envía nombre (SNI): usar este certificado por defecto.
	default_sni 192.168.100.221
}

https://192.168.100.221 {
	tls internal
	encode zstd gzip
	reverse_proxy api:3080
}

# Descarga del certificado raíz (público) para instalarlo antes de confiar en el HTTPS.
http://192.168.100.221 {
	handle /ca.crt {
		root * /data/caddy/pki/authorities/local
		rewrite * /root.crt
		header Content-Type application/x-x509-ca-cert
		header Content-Disposition "attachment; filename=librechat-ca.crt"
		file_server
	}
	handle {
		redir https://{host}{uri} permanent
	}
}
```

El bloque `http://` hace dos cosas:
- `http://192.168.100.221/ca.crt` descarga el certificado raíz. Siempre se sirve `root.crt` y nada más: no se puede listar la carpeta ni pedir las llaves.
- Cualquier otra dirección por HTTP redirige a HTTPS.

`/opt/librechat/docker-compose.override.yml`:
```yaml
services:
  api:
    image: registry.librechat.ai/librechat-ai/librechat:v0.8.8
    ports: !override
      - "127.0.0.1:3080:3080"
    volumes:
      - type: bind
        source: ./librechat.yaml
        target: /app/librechat.yaml

  admin-panel:
    ports: !override
      - "127.0.0.1:3000:3000"

  caddy:
    image: caddy:2.10
    container_name: caddy
    restart: unless-stopped
    depends_on:
      - api
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./caddy:/etc/caddy:ro        # la carpeta, no el archivo: así se ven los cambios
      - caddy_data:/data             # contiene la CA interna: no borrar
      - caddy_config:/config

volumes:
  caddy_data:
  caddy_config:
```

`!override` reemplaza los puertos del `docker-compose.yml` original en vez de sumarles
los nuevos.

En `/opt/librechat/.env`:
```dotenv
DOMAIN_CLIENT=https://192.168.100.221
DOMAIN_SERVER=https://192.168.100.221
TRUST_PROXY=1
```

### Cambiar la configuración de Caddy

```bash
# editar /opt/librechat/caddy/Caddyfile y aplicar sin reiniciar:
docker exec caddy caddy reload --config /etc/caddy/Caddyfile
```

### Verificar

```bash
ss -ltn | grep -E ':(80|443|3000|3080) '
# esperado: 80 y 443 en 0.0.0.0; 3000 y 3080 solo en 127.0.0.1

docker exec caddy wget -qO- http://127.0.0.1:2019/config/ | grep -o '"default_sni":"[^"]*"'
echo | openssl s_client -connect 192.168.100.221:443 2>/dev/null | grep issuer=
curl -sSI --cacert /opt/librechat/caddy-root-ca.crt https://192.168.100.221 | head -1   # HTTP/2 200

# descarga del certificado: la huella debe coincidir con la publicada (más abajo)
curl -sS http://192.168.100.221/ca.crt | openssl x509 -noout -fingerprint -sha1
curl -sSI http://192.168.100.221/ | grep -i location                                 # redirige a https
curl -sS -o /dev/null -w "%{http_code}\n" http://192.168.100.221/root.key            # 301, nunca la llave
```

Desde otra PC: `https://192.168.100.221` abre LibreChat, y `http://192.168.100.221:3080` y
`:3000` no responden.

### Certificado raíz para las PCs

Caddy usa su propia autoridad certificadora (CA) interna. Cada PC debe instalar su
certificado raíz una sola vez; si no, el navegador muestra "conexión no privada". Es válido
hasta septiembre de 2036.

**Qué es público y qué no:**

| Archivo | ¿Se comparte? |
|---------|---------------|
| `root.crt` (`/ca.crt`, `/opt/librechat/caddy-root-ca.crt`) | **Sí**, a todos los usuarios |
| `root.key`, `intermediate.key` (dentro del volumen `caddy_data`) | **Nunca** |
| Respaldos de `caddy_data` | **Nunca**: contienen las llaves |

**Cómo repartirlo:**
1. **Enlace de descarga** (configurado): enviar a cada usuario `http://192.168.100.221/ca.crt`.
   Al abrirlo se descarga `librechat-ca.crt`. No queda instalado: el usuario debe abrirlo e
   instalarlo.
2. **Archivo compartido:** `/opt/librechat/caddy-root-ca.crt`, por carpeta compartida o correo.
3. **GPO de TI:** se instala en todas las PCs del dominio sin intervención del usuario. Es lo
   recomendable si son muchas.

**Publica siempre la huella por un canal distinto del archivo**, por ejemplo en un mensaje
aparte. Si alguien cambiara el archivo en el camino, el usuario confiaría en un impostor; la
huella permite detectarlo.

| Huella | Valor |
|--------|-------|
| SHA-1 (Windows la muestra como "Huella digital") | `1A:E5:D8:99:D1:82:CC:92:13:41:30:18:58:D4:BC:1A:42:F5:48:DB` |
| SHA-256 | `FA:39:33:56:A1:7C:4C:D0:8B:04:EB:B4:6D:BD:45:EA:0E:E8:2E:DA:D0:DE:AC:A5:42:B9:9E:9B:62:75:67:7E` |

Si la CA se regenera (por ejemplo, porque se perdió `caddy_data`), las huellas cambian.
Calcúlalas de nuevo con:
```bash
docker compose -p librechat cp caddy:/data/caddy/pki/authorities/local/root.crt /opt/librechat/caddy-root-ca.crt
sudo chmod 644 /opt/librechat/caddy-root-ca.crt
openssl x509 -in /opt/librechat/caddy-root-ca.crt -noout -fingerprint -sha1
openssl x509 -in /opt/librechat/caddy-root-ca.crt -noout -fingerprint -sha256
```

**Verificar la huella antes de instalar:**
- **Windows:** doble clic en el `.crt` → pestaña **Detalles** → **Huella digital** (SHA-1).
- **Linux o macOS:** `openssl x509 -in librechat-ca.crt -noout -fingerprint -sha256`.

**Instalar:**
- **Windows:** doble clic → Instalar certificado → Equipo local → "Entidades de
  certificación raíz de confianza".
- **Fedora/Linux:** `sudo cp caddy-root-ca.crt /etc/pki/ca-trust/source/anchors/ && sudo update-ca-trust`.
- **macOS:** Acceso a Llaveros → importar → "Confiar siempre".
- **Firefox** usa su propio almacén de certificados: activa
  `security.enterprise_roots.enabled` en `about:config`, o importa el certificado en sus
  ajustes.

El volumen `caddy_data` guarda la llave de esa CA. **Respáldalo**: si se pierde, Caddy
crea otra y hay que reinstalar el certificado en todas las PCs.

### Panel de administración

Se abre en el propio servidor, en `http://localhost:3000`. Desde otra PC solo con un túnel SSH:
```bash
ssh -L 3000:127.0.0.1:3000 -L 3080:127.0.0.1:3080 vpinto@192.168.100.221
# y luego abrir http://localhost:3000
```

### Si se usa un nombre en vez de la IP

Si el DNS de la oficina resuelve un nombre (por ejemplo `librechat.empresa.local`), hay que
agregarlo al sitio del Caddyfile (`https://192.168.100.221, https://librechat.empresa.local {`)
y ponerlo en `DOMAIN_CLIENT`/`DOMAIN_SERVER`. Con un nombre, los navegadores sí envían SNI.
La IP del servidor debe estar reservada en el DHCP: si cambia, el certificado y los enlaces
dejan de servir.

---

## 7. Usuarios de LibreChat

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

## 8. Desplegar desde cero en un servidor nuevo

1. Instalar Docker y habilitarlo al arranque: `sudo systemctl enable --now docker`.
2. LibreChat en `/opt/librechat`, en la versión probada `v0.8.8`, con:
   - el override y `caddy/Caddyfile` de la sección 6, cambiando la IP por la del servidor
     nuevo;
   - su `.env`, con `MCP_OSTICKET_TOKEN`, `ALLOW_REGISTRATION=false`, `DOMAIN_CLIENT`,
     `DOMAIN_SERVER` y `TRUST_PROXY=1`;
   - su `librechat.yaml`, con este bloque:
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
4. `docker restart LibreChat` y verificar que diga `15 tools` (sección 3).
5. Extraer el certificado raíz de Caddy, instalarlo en las PCs y verificar el HTTPS
   (sección 6).
6. Permitir la IP del servidor en el Security Group de la base y en la cuenta de MariaDB
   (`docker run --rm mcp-osticket:latest grants --database osticket --user ... --host ...`).

---

## Pendientes de seguridad de este despliegue

- La conexión a la base de osTicket no va cifrada (TLS desactivado en MariaDB). Está
  reportado al administrador.
- Reservar en el DHCP la IP `192.168.100.221`, o usar un nombre DNS.
- Respaldar los volúmenes `caddy_data` (CA interna) y MongoDB (`/opt/librechat/data-node`),
  y los dos `.env`.
