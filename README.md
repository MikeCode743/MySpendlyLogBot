# MySpendlyLogBot 🤖💸

Bot de Telegram para registrar finanzas personales en lenguaje natural. Usa Claude AI (Haiku) para interpretar mensajes y los guarda automáticamente en Google Sheets.

## ¿Qué hace?

Escribe como hablas y el bot entiende:

```
"Gaste 10 en combustible"
"Retiré 40 dólares"
"Presté 15 a Juan"
"Cobré 200 de mi trabajo"
"Transferí 5 a María"
```

Cada transacción queda registrada en tu Google Sheets con fecha, hora, tipo, monto, categoría y más.

## Tipos de transacciones

| Tipo | Ejemplo |
|------|---------|
| Gasto | `Gaste 25 en el supermercado` |
| Ingreso | `Cobré 300 del freelance` |
| Retiro | `Retiré 100 del cajero` |
| Transferencia | `Transferí 50 a mi hermano` |
| Préstamo | `Presté 20 a JC` |

## Comandos y teclado rápido

| Comando / Botón | Descripción |
|-----------------|-------------|
| `/start` | Bienvenida y teclado rápido |
| `/ayuda` | Lista de comandos y ejemplos |
| `/ultimo` | Ver la última transacción registrada (sesión actual) |
| `/cancelar` | Cancelar acción en curso |
| `💸 Gasto` | Atajo para registrar un gasto |
| `💵 Ingreso` | Atajo para registrar un ingreso |
| `💰 Retiro` | Atajo para registrar un retiro |
| `↔️ Transferencia` | Atajo para registrar una transferencia |
| `📊 Resumen` | Enlace a tu Google Sheets |
| `❓ Ayuda` | Muestra el menú de ayuda |

## Requisitos

- Token de bot de Telegram ([@BotFather](https://t.me/BotFather))
- API key de Anthropic (Claude Haiku)
- Cuenta de servicio de Google con acceso a Sheets
- `credentials.json` de la cuenta de servicio (descárgalo desde Google Cloud Console)

Comparte tu Google Sheet con el email de la cuenta de servicio (con permisos de editor).

---

## Instalación — Desarrollo (local)

```bash
git clone <repo-url>
cd MySpendlyLogBot

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env             # edita .env con tus credenciales
# coloca credentials.json en la raíz del proyecto

python main.py
```

`.env` mínimo:

```env
TELEGRAM_TOKEN=tu_token_aqui
ANTHROPIC_API_KEY=tu_api_key_aqui
GOOGLE_SHEET_NAME=Mis Finanzas 2026
GOOGLE_CREDENTIALS_FILE=credentials.json
```

---

## Instalación — Producción (VPS / servidor)

En producción usa `GOOGLE_CREDENTIALS_JSON` (contenido del JSON en una sola línea) en lugar del archivo:

```bash
# Convertir credentials.json a variable de entorno
python3 -c "import json; f=open('credentials.json'); print(json.dumps(json.load(f)))"
```

```env
TELEGRAM_TOKEN=tu_token_aqui
ANTHROPIC_API_KEY=tu_api_key_aqui
GOOGLE_SHEET_NAME=Mis Finanzas 2026
GOOGLE_CREDENTIALS_JSON={"type":"service_account","project_id":"..."}
```

El bot prioriza `GOOGLE_CREDENTIALS_JSON` sobre `GOOGLE_CREDENTIALS_FILE`.

### Systemd (mantener el proceso activo)

```ini
# /etc/systemd/system/spendlybot.service
[Unit]
Description=MySpendlyLogBot
After=network.target

[Service]
WorkingDirectory=/ruta/al/proyecto
EnvironmentFile=/ruta/al/proyecto/.env
ExecStart=/ruta/al/proyecto/.venv/bin/python main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now spendlybot
sudo systemctl status spendlybot
sudo journalctl -u spendlybot -f   # ver logs
```

### Railway / Render / Fly.io

Sube las variables de entorno desde el dashboard y despliega directamente. No se necesita configuración extra.

---

## Instalación — Docker

Requiere `credentials.json` en la raíz del proyecto.

```bash
cp .env.example .env   # edita con tus credenciales

docker compose up -d           # levantar en background
docker compose logs -f bot     # ver logs en tiempo real
docker compose restart bot     # reiniciar el bot
docker compose down            # detener y eliminar contenedor
```

El contenedor usa `restart: always` — se reinicia automáticamente ante crashes y al arrancar el sistema.

Para reconstruir la imagen tras cambios en el código:

```bash
docker compose up -d --build
```

## Estructura de Google Sheets

El bot crea automáticamente las columnas la primera vez que registra una transacción:

| Fecha | Hora | Tipo | Monto | Moneda | Descripción | Categoría | Persona | Confianza | Mensaje original |
|-------|------|------|-------|--------|-------------|-----------|---------|-----------|-----------------|

## Arquitectura

```
main.py          — Bot principal (Telegram + Claude + Sheets integrados)
ai_parse.py      — Prototipo/referencia del parser de IA (no se usa en producción)
sheets.py        — Prototipo/referencia del módulo de Sheets (no se usa en producción)
requirements.txt
.env                  — Variables de entorno (no subir al repo)
credentials.json      — Cuenta de servicio Google (no subir al repo)
```

## Stack

- **[python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot)** — Interfaz de Telegram
- **[Anthropic SDK](https://github.com/anthropics/anthropic-sdk-python)** — Claude Haiku (`claude-haiku-4-5-20251001`) para parsear lenguaje natural
- **[gspread](https://github.com/burnash/gspread)** — Escritura en Google Sheets
- **[python-dotenv](https://github.com/theskumar/python-dotenv)** — Variables de entorno
