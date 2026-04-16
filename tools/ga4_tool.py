from __future__ import annotations

"""
Google Analytics 4 Tool
-----------------------
Consulta la GA4 Data API usando Application Default Credentials (ADC).

Autenticación:
  - Local:      gcloud auth application-default login
  - Cloud Run:  asignar la Service Account en la config del servicio
                (sin JSON de credenciales, sin token.json)

La Service Account debe tener el rol:
  "Viewer" en la propiedad de GA4 (Google Analytics → Admin → Property Access Management)
"""

import json
from datetime import date, timedelta

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Metric,
    RunReportRequest,
)


# ── Tool principal ─────────────────────────────────────────────────────────────

async def buscar_ga4(input_data: str) -> str:
    """
    Consulta Google Analytics 4 para una propiedad dada.

    input_data (JSON string):
      - property_id  (str, requerido): ID de la propiedad GA4, solo el número
                      Ej: "123456789"
      - start_date   (str, opcional): "YYYY-MM-DD" — default: hace 28 días
      - end_date     (str, opcional): "YYYY-MM-DD" — default: ayer
      - metrics      (list, opcional): métricas GA4
                      default: ["sessions", "activeUsers", "screenPageViews"]
      - dimensions   (list, opcional): dimensiones GA4
                      default: ["pagePath"]
      - row_limit    (int, opcional): máximo filas a devolver — default: 10
    """
    try:
        data = json.loads(input_data)

        property_id = data.get("property_id")
        if not property_id:
            # Propiedad por defecto del proyecto
            property_id = "525948952"

        # 1. Prioridad: days_ago (para evitar alucinaciones del LLM)
        days_ago = data.get("days_ago")
        
        if days_ago:
            try:
                days_int = int(days_ago)
                end_date   = str(date.today() - timedelta(days=1))
                start_date = str(date.today() - timedelta(days=days_int))
            except Exception:
                end_date   = data.get("end_date",   str(date.today() - timedelta(days=1)))
                start_date = data.get("start_date", str(date.today() - timedelta(days=28)))
        else:
            # Fechas por defecto: últimos 28 días
            end_date   = data.get("end_date",   str(date.today() - timedelta(days=1)))
            start_date = data.get("start_date", str(date.today() - timedelta(days=28)))

        metrics_input    = data.get("metrics",    ["sessions", "activeUsers", "screenPageViews"])
        dimensions_input = data.get("dimensions", ["pagePath"])
        row_limit        = int(data.get("row_limit", 10))

        # ADC — detecta automáticamente las credenciales (local o Cloud Run)
        client = BetaAnalyticsDataClient()

        request = RunReportRequest(
            property=f"properties/{property_id}",
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            metrics=[Metric(name=m) for m in metrics_input],
            dimensions=[Dimension(name=d) for d in dimensions_input],
            limit=row_limit,
        )

        response = client.run_report(request)

        # Formatear filas
        rows = []
        for row in response.rows:
            row_data = {}
            for i, dim in enumerate(response.dimension_headers):
                row_data[dim.name] = row.dimension_values[i].value
            for i, met in enumerate(response.metric_headers):
                row_data[met.name] = row.metric_values[i].value
            rows.append(row_data)

        return json.dumps(
            {
                "status":       "success",
                "connection_verified": True,
                "message":      "Conexión exitosa con la API de Google Analytics 4.",
                "property_id":  property_id,
                "start_date":   start_date,
                "end_date":     end_date,
                "metrics":      metrics_input,
                "dimensions":   dimensions_input,
                "total_rows":   len(rows),
                "rows":         rows,
            },
            ensure_ascii=False,
        )

    except Exception as e:
        return json.dumps(
            {
                "status":  "error",
                "message": f"Error en buscar_ga4: {str(e)}",
            },
            ensure_ascii=False,
        )
