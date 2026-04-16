from __future__ import annotations
from typing import Any

import json
import os
from datetime import date, timedelta

# Google API client
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# Configuración 
SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
CREDENTIALS_FILE = os.getenv("GSC_CREDENTIALS_FILE", "credentials.json")
TOKEN_FILE = os.getenv("GSC_TOKEN_FILE", "token.json")

# Auth 

def _get_gsc_service():
    """Devuelve un cliente autenticado de la Search Console API."""
    creds = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_FILE):
                raise FileNotFoundError(
                    f"No se encontró {CREDENTIALS_FILE}. "
                    "Descárgalo de GCP → APIs & Services → Credentials."
                )
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return build("searchconsole", "v1", credentials=creds)


# Tool principal 

async def buscar_gsc(input_data: str) -> str:
    """
    Consulta Google Search Console para una propiedad y rango de fechas.

    input_data (JSON string):
      - site_url         (str, requerido): URL de la propiedad GSC
                          Ej: "https://www.ejemplo.com/" o "sc-domain:ejemplo.com"
      - start_date       (str, opcional): "YYYY-MM-DD" — default: hace 28 días
      - end_date         (str, opcional): "YYYY-MM-DD" — default: ayer
      - dimensions       (list, opcional): ["query", "page", "country", "device"]
                          default: ["query"]
      - row_limit        (int, opcional): máximo filas a devolver — default: 10
    """
    try:
        data = json.loads(input_data)

        site_url = data.get("site_url")
        if not site_url:
            raise ValueError("Campo requerido: site_url")

        # Fechas por defecto: últimos 28 días
        end_date   = data.get("end_date",   str(date.today() - timedelta(days=1)))
        start_date = data.get("start_date", str(date.today() - timedelta(days=28)))
        dimensions = data.get("dimensions", ["query"])
        row_limit  = int(data.get("row_limit", 10))

        service = _get_gsc_service()

        request_body = {
            "startDate": start_date,
            "endDate":   end_date,
            "dimensions": dimensions,
            "rowLimit":  row_limit,
        }

        response = service.searchanalytics().query(
            siteUrl=site_url,
            body=request_body,
        ).execute()

        rows = response.get("rows", [])

        return json.dumps(
            {
                "status":     "success",
                "site_url":   site_url,
                "start_date": start_date,
                "end_date":   end_date,
                "dimensions": dimensions,
                "total_rows": len(rows),
                "rows":       rows,
            },
            ensure_ascii=False,
        )

    except Exception as e:
        return json.dumps(
            {
                "status":  "error",
                "message": f"Error en buscar_gsc: {str(e)}",
            },
            ensure_ascii=False,
        )

async def tool_gsc_node(state: dict[str, Any]) -> dict[str, Any]:
    input_data = state.get("input_data")

    if not input_data:
        state["gsc_data"] = None
        state["status"] = "error"
        state["response_msg"] = "Falta `input_data` en el subestado GSC."
        return state

    raw_result = await buscar_gsc(input_data)

    try:
        gsc_data = json.loads(raw_result)
    except Exception:
        gsc_data = {
            "status": "error",
            "message": "La tool GSC devolvió una respuesta no parseable.",
            "raw_output": raw_result,
        }

    state["gsc_data"] = gsc_data
    state["status"] = gsc_data.get("status", "error")
    state["response_msg"] = gsc_data.get("message", "Consulta GSC ejecutada.")

    return state