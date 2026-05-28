"""
MySpendlyLogBot — Bot de finanzas personales para Telegram
Registra gastos, ingresos, retiros, transferencias y préstamos
usando lenguaje natural con Claude AI → Google Sheets
"""

import os
import json, tempfile, uuid, time
import logging
from datetime import datetime
from dotenv import load_dotenv

import anthropic
import gspread
from google.oauth2.service_account import Credentials

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
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
# Rate limiting por usuario
# ─────────────────────────────────────────────

RATE_COOLDOWN_SEG  = 4    # segundos mínimos entre peticiones
RATE_MAX_POR_MIN   = 8    # máximo de peticiones por ventana de 60 s

_rate: dict[int, dict] = {}  # {user_id: {last, count, window_start}}


def _verificar_rate(user_id: int) -> tuple[bool, str]:
    """Retorna (permitido, mensaje_de_error). Thread-safe para asyncio (single-thread)."""
    ahora = time.monotonic()
    datos = _rate.setdefault(user_id, {"last": 0.0, "count": 0, "window_start": ahora})

    # Resetear ventana si pasaron 60 s
    if ahora - datos["window_start"] >= 60:
        datos["count"]        = 0
        datos["window_start"] = ahora

    # Cooldown entre peticiones
    espera = RATE_COOLDOWN_SEG - (ahora - datos["last"])
    if espera > 0:
        return False, f"⏳ Espera {espera:.0f}s antes de enviar otra transacción."

    # Límite por minuto
    if datos["count"] >= RATE_MAX_POR_MIN:
        restante = 60 - (ahora - datos["window_start"])
        return False, f"🚫 Límite alcanzado. Intenta en {restante:.0f}s."

    datos["last"]   = ahora
    datos["count"] += 1
    return True, ""


# ─────────────────────────────────────────────
# Clientes IA y Google Sheets
# ─────────────────────────────────────────────

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


_sheet_cache: gspread.Worksheet | None = None


def _invalidar_cache_sheets() -> None:
    global _sheet_cache
    _sheet_cache = None


def get_sheet() -> gspread.Worksheet:
    global _sheet_cache
    if _sheet_cache is not None:
        return _sheet_cache
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    else:
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    gc = gspread.authorize(creds)
    _sheet_cache = gc.open(GOOGLE_SHEET_NAME).sheet1
    return _sheet_cache


# ─────────────────────────────────────────────
# Sistema de prompt para Claude
# ─────────────────────────────────────────────

SYSTEM_PROMPT = """
Eres un asistente financiero personal. Tu única tarea es extraer información
de transacciones financieras de mensajes en español (o inglés) y devolver
EXCLUSIVAMENTE un objeto JSON válido — sin texto adicional, sin markdown,
sin backticks.

Hoy es: {hoy}

Campos del JSON:
- tipo        : "gasto" | "ingreso" | "retiro" | "transferencia" | "prestamo"
- monto       : número decimal positivo (sin símbolo de moneda)
- moneda      : "USD" por defecto, o la que indique el usuario
- descripcion : texto corto describiendo la transacción (máx 60 caracteres)
- categoria   : una de estas exactas:
                  "Vivienda" | "Alimentación" | "Transporte" |
                  "Salud" | "Bienestar/Ejercicio" |
                  "Entretenimiento" | "Ahorros/Inversiones" |
                  "Servicios Básicos" | "Suscripciones Digitales" |
                  "Mantenimiento Vehículo" | "Regalos y Detalles" |
                  "Compras Online" | "Hogar y Mejoras" | "Otro"
                  Usa "Servicios Básicos" para: electricidad, agua, gas,
                  internet, teléfono, condominio.
                  Usa "Hogar y Mejoras" para: muebles, decoración,
                  reparaciones del hogar (Vivienda=renta/hipoteca, no mejoras).
                  Usa "Salud" para: médico, farmacia, consultas médicas.
                  Usa "Bienestar/Ejercicio" para: gimnasio, suplementos, spa.
                  Usa "Mantenimiento Vehículo" para: combustible, servicio,
                  reparaciones de vehículo.
                  Usa "Suscripciones Digitales" para: Netflix, Spotify,
                  software, apps de pago.
- fecha       : fecha en formato YYYY-MM-DD. Si el mensaje menciona cuándo ocurrió
                (ayer, el lunes, hace 3 días, el 15 de mayo, etc.) resuélvela
                respecto a la fecha de hoy indicada arriba. Si no se menciona fecha,
                devuelve null.
- persona     : nombre de la persona involucrada o null si no aplica
- confianza   : "alta" | "media" | "baja" según qué tan clara fue la instrucción
- nota        : aclaración breve si confianza es baja, o null

Ejemplos de entrada → salida:

"gaste 10 en combustible"
→ {"tipo":"gasto","monto":10,"moneda":"USD","descripcion":"Combustible","categoria":"Transporte","fecha":null,"persona":null,"confianza":"alta","nota":null}

"ayer gasté 15 en comida"
→ {"tipo":"gasto","monto":15,"moneda":"USD","descripcion":"Comida","categoria":"Alimentación","fecha":"2026-05-19","persona":null,"confianza":"alta","nota":null}

"el lunes retiré 40 dólares"
→ {"tipo":"retiro","monto":40,"moneda":"USD","descripcion":"Retiro de efectivo","categoria":"Otro","fecha":"2026-05-18","persona":null,"confianza":"alta","nota":null}

"hace 3 días presté 10 a JC"
→ {"tipo":"prestamo","monto":10,"moneda":"USD","descripcion":"Préstamo a JC","categoria":"Otro","fecha":"2026-05-17","persona":"JC","confianza":"alta","nota":null}

"transferí 5 a alguien"
→ {"tipo":"transferencia","monto":5,"moneda":"USD","descripcion":"Transferencia","categoria":"Otro","fecha":null,"persona":"alguien","confianza":"media","nota":"No se especificó destinatario exacto"}

"gaste 20 en el supermercado"
→ {"tipo":"gasto","monto":20,"moneda":"USD","descripcion":"Supermercado","categoria":"Alimentación","fecha":null,"persona":null,"confianza":"alta","nota":null}

"pagué 45 de mantenimiento"
→ {"tipo":"gasto","monto":45,"moneda":"USD","descripcion":"Mantenimiento/condominio","categoria":"Servicios Básicos","fecha":null,"persona":null,"confianza":"alta","nota":null}

"pagué la luz"
→ {"tipo":"gasto","monto":0,"moneda":"USD","descripcion":"Servicio eléctrico","categoria":"Servicios Básicos","fecha":null,"persona":null,"confianza":"baja","nota":"No se especificó el monto"}

"pagué internet 30 dólares"
→ {"tipo":"gasto","monto":30,"moneda":"USD","descripcion":"Internet","categoria":"Servicios Básicos","fecha":null,"persona":null,"confianza":"alta","nota":null}

Si el mensaje no contiene ninguna transacción financiera, devuelve:
{"error": "no_transaction", "mensaje": "Explica brevemente qué necesitas"}
"""


def parsear_con_ia(texto: str) -> dict:
    hoy = datetime.now().strftime("%Y-%m-%d")
    system = SYSTEM_PROMPT.replace("{hoy}", hoy)
    respuesta = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        system=[{
            "type": "text",
            "text": system,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": texto}],
    )
    raw = respuesta.content[0].text.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
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


def _resolver_fecha(fecha_iso: str | None) -> str:
    """Convierte fecha YYYY-MM-DD → dd/mm/YYYY. Si es None, usa hoy."""
    if fecha_iso:
        try:
            return datetime.strptime(fecha_iso, "%Y-%m-%d").strftime("%d/%m/%Y")
        except ValueError:
            pass
    return datetime.now().strftime("%d/%m/%Y")


def registrar_en_sheets(transaccion: dict, mensaje_original: str):
    """Agrega una fila nueva. Reintenta una vez si la sesión de Sheets expiró."""
    ahora = datetime.now()
    fila  = [
        _resolver_fecha(transaccion.get("fecha")),
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
    for intento in range(2):
        try:
            hoja = get_sheet()
            asegurar_cabeceras(hoja)
            hoja.append_row(fila)
            log.info(f"Registrado: {fila}")
            return
        except gspread.exceptions.APIError:
            if intento == 0:
                _invalidar_cache_sheets()
                log.warning("Sesión Sheets expirada — reconectando...")
                continue
            raise


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
    fecha   = _resolver_fecha(t.get("fecha"))

    texto = (
        f"{icono} *{t['tipo'].capitalize()} registrado*\n"
        f"━━━━━━━━━━━━━━\n"
        f"💲 Monto:     `{t['monto']} {t['moneda']}`\n"
        f"📅 Fecha:     {fecha}\n"
        f"📂 Categoría: `{t['categoria']}`\n"
        f"📝 Detalle:   {t['descripcion']}{persona}\n"
        f"🕐 Hora reg.: {datetime.now().strftime('%H:%M')}\n"
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
        f"👋 ¡Hola *{nombre}*! Soy *MySpendlyLogBot*.\n\n"
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
        "/start    — Bienvenida\n"
        "/ayuda    — Este menú\n"
        "/ultimo   — Ver última transacción\n"
        "/resumen  — Resumen del mes actual\n"
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
    context.user_data.pop("esperando_monto", None)
    context.user_data.pop("pendiente", None)
    await update.message.reply_text(
        "❌ Acción cancelada. Escribe una nueva transacción cuando quieras.",
        reply_markup=teclado_rapido(),
    )


async def _mostrar_confirmacion(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    resultado: dict,
    texto_original: str,
) -> None:
    """Muestra mensaje de confirmación con botones inline. Invalida el anterior si existe."""
    pendiente_prev = context.user_data.get("pendiente")
    if pendiente_prev and pendiente_prev.get("msg_id"):
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=update.effective_chat.id,
                message_id=pendiente_prev["msg_id"],
                reply_markup=None,
            )
        except Exception:
            pass

    conf_id = str(uuid.uuid4())[:8]
    context.user_data["pendiente"] = {
        "id":               conf_id,
        "transaccion":      resultado,
        "mensaje_original": texto_original,
        "msg_id":           None,
    }
    teclado_conf = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirmar", callback_data=f"confirmar:{conf_id}"),
        InlineKeyboardButton("❌ Cancelar",  callback_data=f"cancelar:{conf_id}"),
    ]])
    msg = await update.message.reply_text(
        f"¿Confirmar este registro?\n\n{formatear_confirmacion(resultado)}",
        parse_mode="Markdown",
        reply_markup=teclado_conf,
    )
    context.user_data["pendiente"]["msg_id"] = msg.message_id


async def _resolver_monto_pendiente(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    texto: str,
) -> None:
    """Intenta parsear `texto` como monto y completa la transacción pendiente."""
    datos = context.user_data.get("esperando_monto")
    try:
        monto = float(texto.replace(",", ".").strip())
        if monto <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "⚠️ Valor inválido. Ingresa solo el monto (ej: `25.50`)\n"
            "o usa /cancelar para descartar.",
            parse_mode="Markdown",
        )
        return

    context.user_data.pop("esperando_monto")
    t = datos["transaccion"]
    t["monto"] = monto
    await _mostrar_confirmacion(update, context, t, datos["mensaje_original"])


async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler principal — procesa cualquier mensaje de texto."""
    texto = update.message.text.strip()

    # Ignorar botones del teclado que no son transacciones
    if texto in ("📊 Resumen", "❓ Ayuda"):
        if texto == "❓ Ayuda":
            await cmd_ayuda(update, context)
        else:
            await cmd_resumen(update, context)
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

    # Monto pendiente de mensaje anterior
    if context.user_data.get("esperando_monto"):
        await _resolver_monto_pendiente(update, context, texto)
        return

    # Rate limit
    permitido, msg_limite = _verificar_rate(update.effective_user.id)
    if not permitido:
        await update.message.reply_text(msg_limite)
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

        # Monto cero → Claude no lo identificó, pedir al usuario
        if resultado.get("monto", 0) == 0:
            context.user_data["esperando_monto"] = {
                "transaccion":      resultado,
                "mensaje_original": texto,
            }
            await update.message.reply_text(
                f"🔢 No pude identificar el monto.\n"
                f"📝 _{resultado.get('descripcion', 'Transacción')}_\n\n"
                f"¿Cuánto fue? (Ej: `25.50`)",
                parse_mode="Markdown",
            )
            return

        await _mostrar_confirmacion(update, context, resultado, texto)

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
            "⚠️ Ocurrió un error inesperado. Intenta de nuevo en un momento."
        )


# ─────────────────────────────────────────────
# Callback de confirmación
# ─────────────────────────────────────────────

async def callback_confirmacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    partes  = query.data.split(":", 1)
    accion  = partes[0]
    conf_id = partes[1] if len(partes) > 1 else None

    pendiente = context.user_data.get("pendiente")

    # Confirmar que el ID coincide (evita actuar sobre confirmaciones viejas)
    if not pendiente or pendiente.get("id") != conf_id:
        await query.edit_message_text("⚠️ Esta confirmación ya expiró.")
        return

    if accion == "confirmar":
        t   = pendiente["transaccion"]
        msg = pendiente["mensaje_original"]
        try:
            registrar_en_sheets(t, msg)
        except Exception as e:
            log.error(f"Error guardando en Sheets: {e}")
            await query.edit_message_text(
                "⚠️ Transacción interpretada pero *no se pudo guardar* en Google Sheets.",
                parse_mode="Markdown",
            )
            return

        context.user_data["ultima_transaccion"] = t
        context.user_data.pop("pendiente", None)

        await query.edit_message_text(
            f"✅ *Registrado correctamente*\n\n{formatear_confirmacion(t)}",
            parse_mode="Markdown",
        )
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="¿Qué más registramos?",
            reply_markup=teclado_rapido(),
        )

    elif accion == "cancelar":
        context.user_data.pop("pendiente", None)
        await query.edit_message_text("❌ Registro cancelado.")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="Escribe una nueva transacción cuando quieras.",
            reply_markup=teclado_rapido(),
        )


# ─────────────────────────────────────────────
# Resumen mensual
# ─────────────────────────────────────────────

MESES_ES = {
    1: "Enero", 2: "Febrero", 3: "Marzo",    4: "Abril",
    5: "Mayo",  6: "Junio",   7: "Julio",    8: "Agosto",
    9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}


async def cmd_resumen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ahora    = datetime.now()
    mes_num  = ahora.month
    anio     = ahora.year
    mes_ref  = f"{mes_num:02d}/{anio}"   # "05/2026"

    try:
        hoja      = get_sheet()
        registros = hoja.get_all_values()
    except Exception as e:
        log.error(f"Error leyendo Sheets: {e}")
        await update.message.reply_text("⚠️ No se pudo conectar con Google Sheets.")
        return

    if len(registros) <= 1:
        await update.message.reply_text("No hay registros aún. 📭")
        return

    # Acumuladores
    totales    = {"ingreso": 0.0, "gasto": 0.0, "retiro": 0.0,
                  "transferencia": 0.0, "prestamo": 0.0}
    categorias = {}
    n_total    = 0

    for fila in registros[1:]:
        if len(fila) < 4:
            continue
        fecha_str = fila[0]           # dd/mm/YYYY
        partes    = fecha_str.split("/")
        if len(partes) != 3:
            continue
        fila_ref = f"{partes[1]}/{partes[2]}"   # "05/2026"
        if fila_ref != mes_ref:
            continue

        tipo = fila[2].lower() if len(fila) > 2 else ""
        try:
            monto = float(fila[3]) if len(fila) > 3 else 0.0
        except ValueError:
            monto = 0.0
        cat = fila[6] if len(fila) > 6 else "Otro"

        if tipo in totales:
            totales[tipo] += monto
            n_total += 1
            if tipo == "gasto":
                categorias[cat] = categorias.get(cat, 0.0) + monto

    balance  = totales["ingreso"] - totales["gasto"] - totales["retiro"]
    signo    = "+" if balance >= 0 else ""
    icono_b  = "📈" if balance >= 0 else "📉"
    nombre_m = f"{MESES_ES[mes_num]} {anio}"

    texto = (
        f"📊 *Resumen — {nombre_m}*\n"
        f"━━━━━━━━━━━━━━\n"
        f"💵 Ingresos:      `+{totales['ingreso']:.2f} USD`\n"
        f"💸 Gastos:        `-{totales['gasto']:.2f} USD`\n"
        f"💰 Retiros:       `-{totales['retiro']:.2f} USD`\n"
    )
    if totales["prestamo"]:
        texto += f"🤝 Préstamos:      `{totales['prestamo']:.2f} USD`\n"
    if totales["transferencia"]:
        texto += f"↔️ Transferencias: `{totales['transferencia']:.2f} USD`\n"

    texto += f"━━━━━━━━━━━━━━\n{icono_b} *Balance:*        `{signo}{balance:.2f} USD`\n"

    if categorias:
        texto += "\n📂 *Gastos por categoría:*\n"
        for cat, monto in sorted(categorias.items(), key=lambda x: -x[1]):
            porcentaje = (monto / totales["gasto"] * 100) if totales["gasto"] else 0
            texto += f"  • {cat}: `{monto:.2f}` _{porcentaje:.0f}%_\n"

    texto += f"\n📝 Transacciones registradas: `{n_total}`"

    await update.message.reply_text(texto, parse_mode="Markdown", reply_markup=teclado_rapido())


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
    app.add_handler(CommandHandler("resumen",  cmd_resumen))

    # Callbacks de confirmación
    app.add_handler(CallbackQueryHandler(callback_confirmacion, pattern=r"^(confirmar|cancelar):"))

    # Mensajes de texto (cualquier texto que no sea comando)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))

    log.info("🤖 MySpendlyLogBot iniciado. Esperando mensajes...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
