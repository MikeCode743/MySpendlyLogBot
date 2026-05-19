# sheets.py
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

def registrar(transaccion):
    gc = gspread.service_account(filename='credentials.json')
    hoja = gc.open("Mis Finanzas 2026").sheet1
    hoja.append_row([
        datetime.now().strftime("%d/%m/%Y %H:%M"),
        transaccion["tipo"],
        transaccion["monto"],
        transaccion["descripcion"],
        transaccion["categoria"],
        transaccion.get("persona", "")
    ])