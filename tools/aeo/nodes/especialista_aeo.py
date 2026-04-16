from __future__ import annotations

import json
import os
from typing import Any

import yaml
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

prompt_path = "./prompt.yml"

DEFAULT_PROMPT = """
Eres un especialista AEO. Analiza el resultado bruto de una herramienta de evaluación de visibilidad en motores de IA.

Objetivos:
- Resumir el estado general.
- Identificar fortalezas y debilidades.
- Señalar hallazgos accionables.
- Ser prudente si faltan datos o si la tool devolvió error.

Devuelve SIEMPRE JSON válido con esta forma:
{
  "summary": "...",
  "strengths": ["..."],
  "weaknesses": ["..."],
  "recommendations": ["..."],
  "status": "success|error"
}
""".strip()


def load_especialista_prompt(path: str = "prompt.yml") -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data.get("especialista_aeo") or DEFAULT_PROMPT
    except Exception:
        return DEFAULT_PROMPT


async def especialista_aeo_node(state: dict[str, Any]) -> dict[str, Any]:
    load_dotenv()
    print("TOOL AEO: ESPECIALISTA")


    aeo_data = state.get("aeo_data")
    state["especialista_aeo_output"] = {
        "summary": "No hay datos AEO para analizar.",
        "strengths": [],
        "weaknesses": [],
        "recommendations": [],
        "status": "error",
    }
    state["status"] = "error"
    state["response_msg"] = "No hay `aeo_data` disponible para el especialista."

    if not aeo_data:
        return state

    prompt_text = load_especialista_prompt(prompt_path)
    model_name = os.getenv("LLM_MODEL")

    if not model_name:
        fallback = {
            "summary": aeo_data.get("message", "No hay análisis disponible."),
            "strengths": [],
            "weaknesses": [],
            "recommendations": [
                "Configura la variable de entorno LLM_MODEL para habilitar el especialista AEO."
            ],
            "status": aeo_data.get("status", "error"),
        }

        state["especialista_aeo_output"] = fallback
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
                "Analiza este resultado AEO y devuelve exclusivamente JSON válido.\n\n"
                + json.dumps(aeo_data, ensure_ascii=False, indent=2)
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
            "strengths": [],
            "weaknesses": [],
            "recommendations": [],
            "status": aeo_data.get("status", "success"),
        }   
    
    state["especialista_aeo_output"] = specialist_output
    state["status"] = specialist_output.get("status", aeo_data.get("status", "success"))
    state["response_msg"] = specialist_output.get("summary", "Análisis AEO completado.")

    return state