from __future__ import annotations
import re
import json
from typing import Optional, TypedDict, Tuple
import copy
import yaml
from langchain_core.messages import AIMessage, ToolMessage

# =========================
# HELPERS
# =========================

def save_aeo_output(state: dict) -> dict:
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, ToolMessage) and msg.name == "ejecutar_subgrafo_aeo":
            try:
                data = json.loads(msg.content)
                state["especialista_aeo_output"] = data
                state["informacion_informe"] = copy.deepcopy(data)
                state["informe_confirmado"] = False
            except Exception:
                pass
            break

    return state

def update_informacion_informe_from_user(state: dict, user_input: str) -> dict:
    info = state.get("informacion_informe")
    if not info:
        return state

    text = user_input.lower().strip()

    # reset confirmación si el usuario cambia contenido
    modified = False

    if text.startswith("cambia el resumen a:"):
        nuevo = user_input.split(":", 1)[1].strip()
        info["summary"] = nuevo
        modified = True

    elif text.startswith("añade fortaleza:"):
        nuevo = user_input.split(":", 1)[1].strip()
        info.setdefault("strengths", []).append(nuevo)
        modified = True

    elif text.startswith("añade debilidad:"):
        nuevo = user_input.split(":", 1)[1].strip()
        info.setdefault("weaknesses", []).append(nuevo)
        modified = True

    elif text.startswith("añade recomendación:"):
        nuevo = user_input.split(":", 1)[1].strip()
        info.setdefault("recommendations", []).append(nuevo)
        modified = True

    elif text.startswith("borra recomendación:"):
        objetivo = user_input.split(":", 1)[1].strip().lower()
        recomendaciones = info.get("recommendations", [])
        info["recommendations"] = [
            r for r in recomendaciones if r.lower() != objetivo
        ]
        modified = True

    if modified:
        state["informacion_informe"] = info
        state["informe_confirmado"] = False

    return state

def extract_tool_and_agent_messages(
    out: dict,
    tool_name: str,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Devuelve:
      - tool_output: contenido devuelto por la tool
      - agent_message: último mensaje del agente (AIMessage sin tool_calls)
    """
    tool_output = None
    agent_message = None

    for msg in reversed(out.get("messages", [])):
        if tool_output is None and isinstance(msg, ToolMessage) and msg.name == tool_name:
            tool_output = msg.content

        if agent_message is None and isinstance(msg, AIMessage):
            if not msg.tool_calls:
                agent_message = msg.content

        if tool_output is not None and agent_message is not None:
            break

    return tool_output, agent_message

def get_last_assistant_text(messages) -> Optional[str]:
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and not msg.tool_calls:
            content = msg.content
            if isinstance(content, list):
                content = " ".join(
                    block.get("text", "") for block in content if isinstance(block, dict)
                )

            if not isinstance(content, str):
                return content

            content = re.sub(
                r"\s*<estado_informe_json>\s*\{.*?\}\s*</estado_informe_json>\s*",
                "",
                content,
                flags=re.DOTALL,
            ).strip()

            return content
    return None

def load_prompt(path: str = "prompt.yml") -> str:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data["general_prompt"]

def extract_updated_informe_from_ai(messages) -> Optional[dict]:
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and not msg.tool_calls:
            content = msg.content

            if isinstance(content, list):
                content = " ".join(
                    block.get("text", "") for block in content if isinstance(block, dict)
                )

            if not isinstance(content, str):
                continue

            match = re.search(
                r"<estado_informe_json>\s*(\{.*?\})\s*</estado_informe_json>",
                content,
                flags=re.DOTALL,
            )
            if not match:
                continue

            try:
                return json.loads(match.group(1))
            except Exception:
                return None

    return None