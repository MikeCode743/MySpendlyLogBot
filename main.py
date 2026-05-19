"""
DonDineroBot — Bot de finanzas personales para Telegram
Registra gastos, ingresos, retiros, transferencias y préstamos
usando lenguaje natural con Claude AI → Google Sheets
"""

import os
import json, tempfile
import logging
from datetime import datetime
from dotenv import load_dotenv

import anthropic
import gspread
from google.oauth2.service_account import Credentials

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ─────────────────────────────────────────────
# Configuración
# ─────────────────────────────────────────────

load_dotenv()

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "Mis Finanzas 2026")
CREDENTIALS_FILE  = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Clientes IA y Google Sheets
# ─────────────────────────────────────────────

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def get_sheet():
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        # Viene de variable de entorno (Railway)
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    else:
        # Viene de archivo local (desarrollo)
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    gc = gspread.authorize(creds)
    return gc.open(GOOGLE_SHEET_NAME).sheet1


# ─────────────────────────────────────────────
# Sistema de prompt para Claude
# ─────────────────────────────────────────────

SYSTEM_PROMPT = """
Eres un asistente financiero personal. Tu única tarea es extraer información
de transacciones financieras de mensajes en español (o inglés) y devolver
EXCLUSIVAMENTE un objeto JSON válido — sin texto adicional, sin markdown,
sin backticks.

Campos del JSON:
- tipo        : "gasto" | "ingreso" | "retiro" | "transferencia" | "prestamo"
- monto       : número decimal positivo (sin símbolo de moneda)
- moneda      : "USD" por defecto, o la que indique el usuario
- descripcion : texto corto describiendo la transacción (máx 60 caracteres)
- categoria   : una de estas exactas:
                  "Vivienda" | "Alimentación" | "Transporte" | "Salud" |
                  "Entretenimiento" | "Ahorros/Inversiones" | "Otro"
- persona     : nombre de la persona involucrada o null si no aplica
- confianza   : "alta" | "media" | "baja" según qué tan clara fue la instrucción
- nota        : aclaración breve si confianza es baja, o null

Ejemplos de entrada → salida:

"gaste 10 en combustible"
→ {"tipo":"gasto","monto":10,"moneda":"USD","descripcion":"Combustible","categoria":"Transporte","persona":null,"confianza":"alta","nota":null}

"retiré 40 dólares"
→ {"tipo":"retiro","monto":40,"moneda":"USD","descripcion":"Retiro de efectivo","categoria":"Otro","persona":null,"confianza":"alta","nota":null}

"presté 10 a JC"
→ {"tipo":"prestamo","monto":10,"moneda":"USD","descripcion":"Préstamo a JC","categoria":"Otro","persona":"JC","confianza":"alta","nota":null}

"transferí 5 a alguien"
→ {"tipo":"transferencia","monto":5,"moneda":"USD","descripcion":"Transferencia","categoria":"Otro","persona":"alguien","confianza":"media","nota":"No se especificó destinatario exacto"}

"gaste 20 en el supermercado"
→ {"tipo":"gasto","monto":20,"moneda":"USD","descripcion":"Supermercado","categoria":"Alimentación","persona":null,"confianza":"alta","nota":null}

Si el mensaje no contiene ninguna transacción financiera, devuelve:
{"error": "no_transaction", "mensaje": "Explica brevemente qué necesitas"}
"""


def parsear_con_ia(texto: str) -> dict:
    """Envía el texto a Claude y retorna el JSON parseado."""
    respuesta = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=400,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": texto}],
    )
    raw = respuesta.content[0].text.strip()
    return json.loads(raw)


# ─────────────────────────────────────────────
# Escritura en Google Sheets
# ─────────────────────────────────────────────

HEADERS = [
    "Fecha", "Hora", "Tipo", "Monto", "Moneda",
    "Descripción", "Categoría", "Persona", "Confianza", "Mensaje original"
]


def asegurar_cabeceras(hoja):
    """Crea la fila de cabeceras si la hoja está vacía."""
    if not hoja.row_values(1):
        hoja.insert_row(HEADERS, index=1)
        log.info("Cabeceras creadas en Google Sheets")


def registrar_en_sheets(transaccion: dict, mensaje_original: str):
    """Agrega una fila nueva con la transacción."""
    hoja  = get_sheet()
    asegurar_cabeceras(hoja)
    ahora = datetime.now()
    fila  = [
        ahora.strftime("%d/%m/%Y"),
        ahora.strftime("%H:%M"),
        transaccion.get("tipo", ""),
        transaccion.get("monto", 0),
        transaccion.get("moneda", "USD"),
        transaccion.get("descripcion", ""),
        transaccion.get("categoria", "Otro"),
        transaccion.get("persona") or "",
        transaccion.get("confianza", ""),
        mensaje_original,
    ]
    hoja.append_row(fila)
    log.info(f"Registrado: {fila}")


# ─────────────────────────────────────────────
# Helpers de formato
# ─────────────────────────────────────────────

ICONOS = {
    "gasto":         "💸",
    "ingreso":       "💵",
    "retiro":        "💰",
    "transferencia": "↔️",
    "prestamo":      "🤝",
}

ALERTAS_CONFIANZA = {
    "media": "⚠️ _Confianza media — revisa que el dato sea correcto._",
    "baja":  "🔴 _Confianza baja_",
}


def formatear_confirmacion(t: dict) -> str:
    icono   = ICONOS.get(t["tipo"], "📌")
    persona = f" → *{t['persona']}*" if t.get("persona") else ""
    alerta  = ALERTAS_CONFIANZA.get(t.get("confianza", "alta"), "")
    nota    = f"\n💬 _{t['nota']}_" if t.get("nota") else ""

    texto = (
        f"{icono} *{t['tipo'].capitalize()} registrado*\n"
        f"━━━━━━━━━━━━━━\n"
        f"💲 Monto:     `{t['monto']} {t['moneda']}`\n"
        f"📂 Categoría: `{t['categoria']}`\n"
        f"📝 Detalle:   {t['descripcion']}{persona}\n"
        f"🕐 Hora:      {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
    )
    if alerta:
        texto += f"\n{alerta}"
    if nota:
        texto += nota
    return texto


# ─────────────────────────────────────────────
# Teclado rápido
# ─────────────────────────────────────────────

def teclado_rapido():
    botones = [
        [KeyboardButton("💸 Gasto"), KeyboardButton("💵 Ingreso")],
        [KeyboardButton("💰 Retiro"), KeyboardButton("↔️ Transferencia")],
        [KeyboardButton("📊 Resumen"), KeyboardButton("❓ Ayuda")],
    ]
    return ReplyKeyboardMarkup(botones, resize_keyboard=True)


# ─────────────────────────────────────────────
# Handlers de Telegram
# ─────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nombre = update.effective_user.first_name or "amigo"
    await update.message.reply_text(
        f"👋 ¡Hola *{nombre}*! Soy *DonDineroBot*.\n\n"
        "Registra cualquier movimiento de dinero escribiendo en lenguaje natural:\n\n"
        "• `Gaste 10 en combustible`\n"
        "• `Retiré 40 dólares`\n"
        "• `Presté 15 a Juan`\n"
        "• `Cobré 200 de mi trabajo`\n"
        "• `Transferí 5 a María`\n\n"
        "Todo queda guardado en tu Google Sheets automáticamente. 🗂️\n\n"
        "Usa /ayuda para ver todos los comandos.",
        parse_mode="Markdown",
        reply_markup=teclado_rapido(),
    )


async def cmd_ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Comandos disponibles*\n\n"
        "/start   — Bienvenida\n"
        "/ayuda   — Este menú\n"
        "/ultimo  — Ver última transacción\n"
        "/cancelar — Cancelar acción en curso\n\n"
        "*Ejemplos de mensajes:*\n"
        "• `Gaste 25 en el supermercado`\n"
        "• `Retiré 100 dólares del cajero`\n"
        "• `Transferí 50 a mi hermano`\n"
        "• `Presté 20 a JC`\n"
        "• `Cobré 300 del freelance`\n"
        "• `Ingresé 500 de mi salario`\n\n"
        "No importa cómo lo escribas, la IA lo entiende. 🤖",
        parse_mode="Markdown",
        reply_markup=teclado_rapido(),
    )


async def cmd_ultimo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ultima = context.user_data.get("ultima_transaccion")
    if not ultima:
        await update.message.reply_text(
            "No hay transacciones registradas en esta sesión todavía."
        )
        return
    await update.message.reply_text(
        f"📌 *Última transacción registrada:*\n\n{formatear_confirmacion(ultima)}",
        parse_mode="Markdown",
    )


async def cmd_cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❌ Acción cancelada. Escribe una nueva transacción cuando quieras.",
        reply_markup=teclado_rapido(),
    )


async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler principal — procesa cualquier mensaje de texto."""
    texto = update.message.text.strip()

    # Ignorar botones del teclado que no son transacciones
    if texto in ("📊 Resumen", "❓ Ayuda"):
        if texto == "❓ Ayuda":
            await cmd_ayuda(update, context)
        else:
            await update.message.reply_text(
                "📊 Abre tu Google Sheets para ver el resumen completo.\n"
                "Próximamente agregaré un resumen directo aquí. 👷"
            )
        return

    # Prefijos de teclado rápido: agregar contexto al mensaje
    prefijos = {
        "💸 Gasto":        "Gasto: ",
        "💵 Ingreso":      "Ingreso: ",
        "💰 Retiro":       "Retiro de ",
        "↔️ Transferencia": "Transferencia de ",
    }
    for boton, prefijo in prefijos.items():
        if texto == boton:
            await update.message.reply_text(
                f"¿Cuánto y en qué? Ej: `{prefijo}15 dólares en comida`",
                parse_mode="Markdown",
            )
            return

    # Indicador de escritura mientras procesa
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing",
    )

    try:
        resultado = parsear_con_ia(texto)

        # Si la IA no encontró transacción
        if "error" in resultado:
            await update.message.reply_text(
                f"🤔 No pude identificar una transacción.\n\n"
                f"_{resultado.get('mensaje', 'Intenta ser más específico.')}_\n\n"
                f"Ejemplo: `Gaste 10 en combustible`",
                parse_mode="Markdown",
            )
            return

        # Guardar en Sheets
        registrar_en_sheets(resultado, texto)

        # Guardar en contexto de sesión
        context.user_data["ultima_transaccion"] = resultado

        # Confirmar al usuario
        await update.message.reply_text(
            formatear_confirmacion(resultado),
            parse_mode="Markdown",
            reply_markup=teclado_rapido(),
        )

    except json.JSONDecodeError:
        log.error("Claude no devolvió JSON válido")
        await update.message.reply_text(
            "⚠️ Error procesando el mensaje. Intenta de nuevo con una descripción más clara."
        )
    except gspread.exceptions.APIError as e:
        log.error(f"Error Google Sheets: {e}")
        await update.message.reply_text(
            "⚠️ Transacción interpretada pero *no se pudo guardar* en Google Sheets.\n"
            "Revisa la conexión con tu hoja.",
            parse_mode="Markdown",
        )
    except Exception as e:
        log.error(f"Error inesperado: {e}")
        await update.message.reply_text(
            f"⚠️ Error: `{str(e)}`",
            parse_mode="Markdown"
        )


# ─────────────────────────────────────────────
# Punto de entrada
# ─────────────────────────────────────────────

def main():
    if not TELEGRAM_TOKEN:
        raise ValueError("Falta TELEGRAM_TOKEN en el archivo .env")
    if not ANTHROPIC_API_KEY:
        raise ValueError("Falta ANTHROPIC_API_KEY en el archivo .env")

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Comandos
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("ayuda",    cmd_ayuda))
    app.add_handler(CommandHandler("ultimo",   cmd_ultimo))
    app.add_handler(CommandHandler("cancelar", cmd_cancelar))

    # Mensajes de texto (cualquier texto que no sea comando)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))

    log.info("🤖 DonDineroBot iniciado. Esperando mensajes...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
