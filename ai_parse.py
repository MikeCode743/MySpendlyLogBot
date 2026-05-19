# ai_parser.py
import anthropic, json

client = anthropic.Anthropic(api_key="TU_KEY")

def parsear_transaccion(texto_usuario):
    respuesta = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=300,
        system="""Eres un asistente financiero. Extrae del mensaje del usuario
        una transacción y devuelve SOLO un JSON con estos campos:
        tipo (gasto/ingreso/retiro/transferencia/prestamo),
        monto (número),
        descripcion (texto corto),
        categoria (Vivienda/Alimentación/Transporte/Salud/Entretenimiento/Ahorros/Otro),
        persona (si aplica, o null)
        No devuelvas nada más que el JSON.""",
        messages=[{"role": "user", "content": texto_usuario}]
    )
    return json.loads(respuesta.content[0].text)