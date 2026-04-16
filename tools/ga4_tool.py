from __future__ import annotations

"""
Google Analytics 4 Tool — AI Traffic Report
--------------------------------------------
Analiza el tráfico que llega a la web procedente de fuentes de IA
(ChatGPT, Perplexity, Gemini, Claude, Copilot...) y las conversiones
que generan, para correlacionar visibilidad AEO con impacto real de negocio.

Autenticación: Application Default Credentials (ADC)
  - Local:      gcloud auth application-default login
  - Cloud Run:  Service Account asignada en la config del servicio
"""

import json
from datetime import date, timedelta

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Metric,
    RunReportRequest,
    FilterExpression,
    FilterExpressionList,
    Filter,
)

# ── Prompt del subagente GA4 ──────────────────────────────────────────────────
# Importado por emilio.py e inyectado en el system message del orquestador.

GA4_PROMPT = """
========================
Google Analytics 4 — Tráfico de IA
========================
- La PROPIEDAD POR DEFECTO para GA4 es `525948952`. NO la pidas al usuario si no la menciona.
- REGLA CRÍTICA PARA FECHAS: nunca calcules tú mismo start_date/end_date. Usa el parámetro `days_ago`.
  Ejemplo: "últimos 15 días" → `days_ago: 15`. Deja start_date y end_date vacíos.
- El informe GA4 analiza tráfico que llega desde fuentes de IA (ChatGPT, Perplexity, Gemini,
  Claude, Copilot...) y las conversiones que generan. Conecta visibilidad AEO con impacto de negocio.
- Al presentar resultados, estructura siempre así:
  1. Resumen: total sesiones IA, usuarios IA, conversiones IA en el período
  2. Desglose por fuente: qué IA genera más tráfico y qué calidad tiene (engagementRate)
  3. Conversiones: si total_ai_conversions > 0, muéstralas por fuente
  4. Diagnóstico: si hay warnings en `diagnostics`, explícalos claramente al usuario
- Si `by_source` está vacío:
  - Confirma que la conexión con GA4 fue EXITOSA
  - Explica que no se detectó tráfico de fuentes de IA en ese período
  - Menciona las posibles causas del campo `diagnostics.warning_no_ai_traffic`
- Si hay tráfico pero `total_ai_conversions` es 0:
  - Confirma que la conexión fue exitosa y hay tráfico de IA
  - Explica que no hay conversiones configuradas, usando `diagnostics.warning_conversions`
  - Recomienda activar Key Events en GA4
"""

# ── Fuentes de IA conocidas en GA4 ────────────────────────────────────────────
# GA4 las registra como sessionSource (dominio referrer) o como UTM source

AI_SOURCES = [
    # Dominios referrer
    "chatgpt.com",
    "chat.openai.com",
    "perplexity.ai",
    "claude.ai",
    "gemini.google.com",
    "bard.google.com",
    "copilot.microsoft.com",
    "bing.com",
    "you.com",
    # UTM sources comunes (si el sitio usa UTM tagging desde IA)
    "chatgpt",
    "perplexity",
    "gemini",
    "claude",
    "copilot",
]

# ── Tool principal ─────────────────────────────────────────────────────────────

async def buscar_ga4(input_data: str) -> str:
    """
    Informe de tráfico IA en GA4: sesiones y conversiones por fuente de IA.

    input_data (JSON string):
      - property_id  (str, opcional): ID de la propiedad GA4.
                      Default: "525948952"
      - days_ago     (int, opcional): analizar los últimos N días.
                      Usar esto en lugar de start/end para evitar errores de fecha.
                      Default: 28
      - start_date   (str, opcional): "YYYY-MM-DD" (ignorado si se usa days_ago)
      - end_date     (str, opcional): "YYYY-MM-DD" (ignorado si se usa days_ago)
      - row_limit    (int, opcional): máximo filas por fuente — default: 20
    """
    try:
        data = json.loads(input_data)

        # Property ID con default
        property_id = data.get("property_id") or "525948952"

        # Fechas — days_ago tiene prioridad para evitar alucinaciones del LLM
        days_ago = data.get("days_ago")
        if days_ago:
            try:
                days_int   = int(days_ago)
                end_date   = str(date.today() - timedelta(days=1))
                start_date = str(date.today() - timedelta(days=days_int))
            except Exception:
                end_date   = data.get("end_date",   str(date.today() - timedelta(days=1)))
                start_date = data.get("start_date", str(date.today() - timedelta(days=28)))
        else:
            end_date   = data.get("end_date",   str(date.today() - timedelta(days=1)))
            start_date = data.get("start_date", str(date.today() - timedelta(days=28)))

        row_limit = int(data.get("row_limit", 20))

        # ADC
        client = BetaAnalyticsDataClient()

        # ── Filtro: solo sesiones de fuentes IA ───────────────────────────────
        ai_filter = FilterExpression(
            or_group=FilterExpressionList(
                expressions=[
                    FilterExpression(
                        filter=Filter(
                            field_name="sessionSource",
                            string_filter=Filter.StringFilter(
                                match_type=Filter.StringFilter.MatchType.EXACT,
                                value=source,
                                case_sensitive=False,
                            ),
                        )
                    )
                    for source in AI_SOURCES
                ]
            )
        )

        # ── Report: sesiones + conversiones por fuente ────────────────────────
        request = RunReportRequest(
            property=f"properties/{property_id}",
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            dimensions=[
                Dimension(name="sessionSource"),
                Dimension(name="sessionMedium"),
            ],
            metrics=[
                Metric(name="sessions"),
                Metric(name="activeUsers"),
                Metric(name="conversions"),       # eventos de conversión totales
                Metric(name="engagementRate"),    # calidad del tráfico
                Metric(name="averageSessionDuration"),
            ],
            dimension_filter=ai_filter,
            limit=row_limit,
            order_bys=[
                {
                    "metric": {"metric_name": "sessions"},
                    "desc": True,
                }
            ],
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

        # ── Totales agregados ──────────────────────────────────────────────────
        total_sessions    = sum(float(r.get("sessions", 0))    for r in rows)
        total_users       = sum(float(r.get("activeUsers", 0)) for r in rows)
        total_conversions = sum(float(r.get("conversions", 0)) for r in rows)

        # ── Diagnóstico: ¿tiene la propiedad conversiones configuradas? ────────
        has_conversions = total_conversions > 0
        diagnostics = {}
        if not has_conversions and rows:
            diagnostics["warning_conversions"] = (
                "La propiedad GA4 tiene tráfico de IA pero 0 conversiones registradas. "
                "Probable causa: no hay eventos de conversión configurados en GA4 "
                "(Goals / Key Events). Para activarlo: GA4 → Admin → Events → "
                "marcar evento como conversión."
            )
        if not rows:
            diagnostics["warning_no_ai_traffic"] = (
                "No se encontró tráfico de fuentes de IA en el período analizado. "
                "Posibles causas: (1) la propiedad no recibe tráfico de IA todavía, "
                "(2) el tráfico de IA llega sin identificar (direct/none), "
                "(3) el rango de fechas es demasiado corto."
            )

        return json.dumps(
            {
                "status":               "success",
                "connection_verified":  True,
                "property_id":          property_id,
                "start_date":           start_date,
                "end_date":             end_date,
                "summary": {
                    "total_ai_sessions":    int(total_sessions),
                    "total_ai_users":       int(total_users),
                    "total_ai_conversions": int(total_conversions),
                },
                "by_source":            rows,
                "diagnostics":          diagnostics,
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
