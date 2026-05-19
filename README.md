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

- Python 3.10+
- Token de bot de Telegram ([@BotFather](https://t.me/BotFather))
- API key de Anthropic (Claude Haiku)
- Cuenta de servicio de Google con acceso a Sheets

## Instalación (local)

1. Clona el repositorio:
   ```bash
   git clone <repo-url>
   cd MySpendlyLogBot
   ```

2. Instala dependencias:
   ```bash
   pip install -r requirements.txt
   ```

3. Crea el archivo `.env`:
   ```env
   TELEGRAM_TOKEN=tu_token_aqui
   ANTHROPIC_API_KEY=tu_api_key_aqui
   GOOGLE_SHEET_NAME=Mis Finanzas 2026
   GOOGLE_CREDENTIALS_FILE=credentials.json
   ```

4. Coloca el archivo `credentials.json` de tu cuenta de servicio de Google en la raíz del proyecto.

5. Comparte tu Google Sheet con el email de la cuenta de servicio (con permisos de editor).

6. Ejecuta el bot:
   ```bash
   python main.py
   ```

## Deploy en Railway (u otro servidor)

En lugar de `GOOGLE_CREDENTIALS_FILE`, usa `GOOGLE_CREDENTIALS_JSON` con el contenido completo del JSON de credenciales:

```env
TELEGRAM_TOKEN=tu_token_aqui
ANTHROPIC_API_KEY=tu_api_key_aqui
GOOGLE_SHEET_NAME=Mis Finanzas 2026
GOOGLE_CREDENTIALS_JSON={"type":"service_account","project_id":"..."}
```

El bot detecta automáticamente cuál usar: primero `GOOGLE_CREDENTIALS_JSON`, luego `GOOGLE_CREDENTIALS_FILE`.

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
