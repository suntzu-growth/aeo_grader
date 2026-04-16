from __future__ import annotations

import json
import os
from typing import Any

import yaml
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI


DEFAULT_PROMPT = """
Eres un especialista en Google Analytics 4 centrado en tráfico procedente de fuentes de IA.

Objetivos:
- Resumir el volumen de tráfico IA.
- Identificar las principales fuentes.
- Señalar si existen conversiones o si faltan.
- Explicar claramente los diagnósticos y warnings.
- Ser prudente si faltan datos o si la tool devolvió error.

Devuelve SIEMPRE JSON válido con esta forma:
{
  "summary": "...",
  "top_sources": ["..."],
  "insights": ["..."],
  "recommendations": ["..."],
  "status": "success|error"
}
""".strip()


def load_especialista_prompt(path: str = "prompt.yml") -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data.get("especialista_ga4") or DEFAULT_PROMPT
    except Exception:
        return DEFAULT_PROMPT


async def especialista_ga4_node(state: dict[str, Any]) -> dict[str, Any]:
    load_dotenv()
    print("TOOL GA4: ESPECIALISTA")

    ga4_data = state.get("ga4_data")

    state["especialista_ga4_output"] = {
        "summary": "No hay datos GA4 para analizar.",
        "top_sources": [],
        "insights": [],
        "recommendations": [],
        "status": "error",
    }
    state["status"] = "error"
    state["response_msg"] = "No hay `ga4_data` disponible para el especialista."

    if not ga4_data:
        return state

    prompt_text = load_especialista_prompt("prompt.yml")
    model_name = os.getenv("LLM_MODEL")

    if not model_name:
        fallback = {
            "summary": ga4_data.get("message", "No hay análisis GA4 disponible."),
            "top_sources": [],
            "insights": [],
            "recommendations": [
                "Configura la variable de entorno LLM_MODEL para habilitar el especialista GA4."
            ],
            "status": ga4_data.get("status", "error"),
        }

        state["especialista_ga4_output"] = fallback
        state["status"] = fallback["status"]
        state["response_msg"] = fallback["summary"]
        return state

    llm = ChatGoogleGenerativeAI(
        model=model_name,
        temperature=0,
    )

    messages = [
        SystemMessage(content=prompt_text),
        HumanMessage(
            content=(
                "Analiza este resultado GA4 y devuelve exclusivamente JSON válido.\n\n"
                + json.dumps(ga4_data, ensure_ascii=False, indent=2)
            )
        ),
    ]

    response = await llm.ainvoke(messages)
    content = response.content

    if isinstance(content, list):
        content = " ".join(
            block.get("text", "") for block in content if isinstance(block, dict)
        ).strip()

    try:
        specialist_output = json.loads(content)
    except Exception:
        specialist_output = {
            "summary": str(content),
            "top_sources": [],
            "insights": [],
            "recommendations": [],
            "status": ga4_data.get("status", "success"),
        }

    state["especialista_ga4_output"] = specialist_output
    state["status"] = specialist_output.get("status", ga4_data.get("status", "success"))
    state["response_msg"] = specialist_output.get("summary", "Análisis GA4 completado.")

    return state