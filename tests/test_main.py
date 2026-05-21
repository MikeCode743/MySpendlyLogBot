import json
import os
import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

os.environ.setdefault("TELEGRAM_TOKEN", "test_token")
os.environ.setdefault("ANTHROPIC_API_KEY", "test_key")

import main


# ─────────────────────────────────────────────
# _resolver_fecha
# ─────────────────────────────────────────────

class TestResolverFecha:
    def test_none_devuelve_hoy(self):
        assert main._resolver_fecha(None) == datetime.now().strftime("%d/%m/%Y")

    def test_fecha_iso_valida(self):
        assert main._resolver_fecha("2026-03-15") == "15/03/2026"

    def test_fecha_invalida_devuelve_hoy(self):
        assert main._resolver_fecha("no-es-fecha") == datetime.now().strftime("%d/%m/%Y")

    def test_cadena_vacia_devuelve_hoy(self):
        assert main._resolver_fecha("") == datetime.now().strftime("%d/%m/%Y")

    def test_fin_de_anio(self):
        assert main._resolver_fecha("2025-12-31") == "31/12/2025"


# ─────────────────────────────────────────────
# parsear_con_ia
# ─────────────────────────────────────────────

def _mock_claude(data: dict) -> MagicMock:
    resp = MagicMock()
    resp.content = [MagicMock(text=json.dumps(data))]
    return resp


class TestParsearConIA:
    def test_gasto_normal(self):
        payload = {
            "tipo": "gasto", "monto": 10, "moneda": "USD",
            "descripcion": "Combustible", "categoria": "Transporte",
            "fecha": None, "persona": None, "confianza": "alta", "nota": None,
        }
        with patch.object(main.claude.messages, "create", return_value=_mock_claude(payload)):
            result = main.parsear_con_ia("gaste 10 en combustible")
        assert result["tipo"] == "gasto"
        assert result["monto"] == 10
        assert result["categoria"] == "Transporte"

    def test_sin_transaccion_devuelve_error(self):
        payload = {"error": "no_transaction", "mensaje": "Sin transacción detectada"}
        with patch.object(main.claude.messages, "create", return_value=_mock_claude(payload)):
            result = main.parsear_con_ia("hola como estás")
        assert "error" in result

    def test_servicios_basicos(self):
        payload = {
            "tipo": "gasto", "monto": 45, "moneda": "USD",
            "descripcion": "Mantenimiento/condominio", "categoria": "Servicios Básicos",
            "fecha": None, "persona": None, "confianza": "alta", "nota": None,
        }
        with patch.object(main.claude.messages, "create", return_value=_mock_claude(payload)):
            result = main.parsear_con_ia("pagué 45 de mantenimiento")
        assert result["categoria"] == "Servicios Básicos"

    def test_respuesta_con_backticks_se_parsea(self):
        payload = {
            "tipo": "ingreso", "monto": 200, "moneda": "USD",
            "descripcion": "Salario", "categoria": "Otro",
            "fecha": None, "persona": None, "confianza": "alta", "nota": None,
        }
        resp = MagicMock()
        resp.content = [MagicMock(text=f"```json\n{json.dumps(payload)}\n```")]
        with patch.object(main.claude.messages, "create", return_value=resp):
            result = main.parsear_con_ia("cobré 200 de salario")
        assert result["monto"] == 200

    def test_monto_cero_confianza_baja(self):
        payload = {
            "tipo": "gasto", "monto": 0, "moneda": "USD",
            "descripcion": "Servicio eléctrico", "categoria": "Servicios Básicos",
            "fecha": None, "persona": None, "confianza": "baja",
            "nota": "No se especificó el monto",
        }
        with patch.object(main.claude.messages, "create", return_value=_mock_claude(payload)):
            result = main.parsear_con_ia("pagué la luz")
        assert result["monto"] == 0
        assert result["confianza"] == "baja"

    def test_prompt_caching_enviado(self):
        payload = {
            "tipo": "gasto", "monto": 5, "moneda": "USD",
            "descripcion": "Café", "categoria": "Alimentación",
            "fecha": None, "persona": None, "confianza": "alta", "nota": None,
        }
        with patch.object(main.claude.messages, "create", return_value=_mock_claude(payload)) as mock_create:
            main.parsear_con_ia("gaste 5 en café")
            call_kwargs = mock_create.call_args.kwargs
            system_arg = call_kwargs.get("system", [])
            assert isinstance(system_arg, list)
            assert system_arg[0].get("cache_control") == {"type": "ephemeral"}
