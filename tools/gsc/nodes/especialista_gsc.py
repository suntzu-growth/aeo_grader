from __future__ import annotations

import json
import os
from typing import Any

import yaml
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI


DEFAULT_PROMPT = """
Eres un especialista en Google Search Console centrado en analizar rendimiento SEO.

Devuelve SIEMPRE JSON válido con esta forma:

{
  "summary": "...",
  "top_queries": ["..."],
  "insights": ["..."],
  "recommendations": ["..."],
  "status": "success|error"
}
""".strip()


def load_especialista_prompt(path: str = "prompt.yml") -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data.get("especialista_gsc") or DEFAULT_PROMPT
    except Exception:
        return DEFAULT_PROMPT


async def especialista_gsc_node(state: dict[str, Any]) -> dict[str, Any]:
    load_dotenv()
    print("TOOL GSC: ESPECIALISTA")

    gsc_data = state.get("gsc_data")

    # fallback
    state["especialista_gsc_output"] = {
        "summary": "No hay datos GSC para analizar.",
        "top_queries": [],
        "insights": [],
        "recommendations": [],
        "status": "error",
    }
    state["status"] = "error"
    state["response_msg"] = "No hay `gsc_data` disponible."

    if not gsc_data:
        return state

    prompt_text = load_especialista_prompt()
    model_name = os.getenv("LLM_MODEL")

    if not model_name:
        fallback = {
            "summary": gsc_data.get("message", "No hay datos disponibles."),
            "top_queries": [],
            "insights": [],
            "recommendations": [],
            "status": gsc_data.get("status", "error"),
        }

        state["especialista_gsc_output"] = fallback
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
                "Analiza este resultado GSC y devuelve JSON válido.\n\n"
                + json.dumps(gsc_data, ensure_ascii=False, indent=2)
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
            "top_queries": [],
            "insights": [],
            "recommendations": [],
            "status": gsc_data.get("status", "success"),
        }

    state["especialista_gsc_output"] = specialist_output
    state["status"] = specialist_output.get("status", "success")
    state["response_msg"] = specialist_output.get("summary", "")

    return state