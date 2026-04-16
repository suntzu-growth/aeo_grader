from __future__ import annotations

import os
import json
from typing import Optional, TypedDict
import copy
import yaml
from dotenv import load_dotenv
from langchain_core.tools import StructuredTool
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.agents import create_agent
from langchain_core.messages import SystemMessage
from tools.aeo.subgraph_aeo import create_aeo_subgraph
from tools.ga4.subgraph_ga4 import create_ga4_subgraph
from tools.gsc.subgraph_gsc import create_gsc_subgraph
from tools.informe.crear_informe import crear_informe

from helpers import (
    load_prompt,
    save_aeo_output,
    get_last_assistant_text,
    extract_updated_informe_from_ai
)


# =========================
# STATE AUX
# =========================

class AEOInput(TypedDict, total=False):
    brand_name: Optional[str]
    geography: Optional[str]
    products_services: Optional[str]
    sector_industry: Optional[str]
    aeo_grader_url: Optional[str]
    html_output_path: Optional[str]


class AgentMemory(TypedDict, total=False):
    messages: list
    informe_confirmado: bool
    especialista_aeo_output: Optional[dict]
    informacion_informe: Optional[dict]


# =========================
# TOOL SUBGRAPH AEO
# =========================

async def ejecutar_subgrafo_aeo(input_data: str) -> str:
    """
    Ejecuta el subgrafo AEO completo:
    - tool_aeo
    - especialista_aeo
    """
    subgraph_aeo = create_aeo_subgraph()

    out = await subgraph_aeo.ainvoke(
        {
            "input_data": input_data,
            "aeo_data": None,
            "especialista_aeo_output": None,
            "status": None,
            "response_msg": None,
        }
    )

    return json.dumps(out["especialista_aeo_output"], ensure_ascii=False)


async def ejecutar_subgrafo_ga4(input_data: str) -> str:
    subgraph_ga4 = create_ga4_subgraph()

    out = await subgraph_ga4.ainvoke(
        {
            "input_data": input_data,
            "ga4_data": None,
            "especialista_ga4_output": None,
            "status": None,
            "response_msg": None,
        }
    )

    response = out.get("especialista_ga4_output", out)
    return json.dumps(response, ensure_ascii=False)


async def ejecutar_subgrafo_gsc(input_data: str) -> str:
    subgraph_gsc = create_gsc_subgraph()

    out = await subgraph_gsc.ainvoke(
        {
            "input_data": input_data,
            "gsc_data": None,
            "especialista_gsc_output": None,
            "status": None,
            "response_msg": None,
        }
    )

    response = out.get("especialista_gsc_output", out)
    return json.dumps(response, ensure_ascii=False)


# =========================
# TOOL INFORME
# =========================

async def ejecutar_crear_informe(input_data: str) -> str:
    """
    Genera el informe HTML final a partir de `informacion_informe`.
    Requiere confirmación explícita del usuario.
    """
    out = await crear_informe(input_data)
    data = json.loads(out)
    html = data["html"]
    status = data["status"]
    return status


# =========================
# EXPONER TOOLS
# =========================

ejecutar_subgrafo_aeo_tool = StructuredTool.from_function(
    func=None,
    coroutine=ejecutar_subgrafo_aeo,
    name="ejecutar_subgrafo_aeo",
    description=(
        "Ejecuta el flujo completo de análisis AEO. "
        "Recibe un único parámetro `input_data`, que debe ser un JSON string con: "
        "brand_name, geography, products_services, sector_industry, "
        "y opcionalmente aeo_grader_url."
    ),
    return_direct=False,
)

ejecutar_crear_informe_tool = StructuredTool.from_function(
    func=None,
    coroutine=ejecutar_crear_informe,
    name="crear_informe",
    description=(
        "Genera el informe HTML final usando los datos actuales de `informacion_informe` "
        "y la plantilla base ubicada en ./rag/example_report.html. "
        "Solo debe usarse si el usuario ha confirmado explícitamente que quiere generar el informe. "
        "Recibe un único parámetro `input_data` como JSON string con: "
        "`confirmed` (bool) e `informacion_informe` (objeto con los datos refinados del informe)."
    ),
    return_direct=False,
)

"""
ejecutar_subgrafo_ga4_tool = StructuredTool.from_function(
    func=None,
    coroutine=ejecutar_subgrafo_ga4,
    name="ejecutar_subgrafo_ga4",
    description=(
        "Ejecuta el flujo completo de análisis GA4 sobre tráfico procedente de motores y asistentes de IA. "
        "Recibe un único parámetro `input_data`, que debe ser un JSON string con: "
        "property_id (opcional, por defecto usa la propiedad GA4 preconfigurada), "
        "days_ago (opcional, recomendado; ejemplo: 28), "
        "start_date (opcional, formato 'YYYY-MM-DD'), "
        "end_date (opcional, formato 'YYYY-MM-DD'), "
        "row_limit (opcional, entero, por defecto 20)."
    ),
    return_direct=False,
)

ejecutar_subgrafo_gsc_tool = StructuredTool.from_function(
    func=None,
    coroutine=ejecutar_subgrafo_gsc,
    name="ejecutar_subgrafo_gsc",
    description=(
        "Analiza datos de Google Search Console (clicks, impresiones, CTR, posición). "
        "Recibe `input_data` como JSON string con: "
        "site_url (requerido), start_date, end_date, dimensions, row_limit."
    ),
    return_direct=False,
)
"""


# =========================
# GRAPH / AGENT ORQUESTADOR
# =========================

def create_graph():
    load_dotenv()

    llm = ChatGoogleGenerativeAI(
        model=os.getenv("LLM_MODEL"),
        temperature=0,
    )

    general_prompt = load_prompt("prompt.yml")

    agent = create_agent(
        model=llm,
        tools=[
            ejecutar_subgrafo_aeo_tool,
            ejecutar_crear_informe_tool,
        ],
        system_prompt=general_prompt,
    )

    return agent


# =========================
# CHAT SERVICE
# =========================

class ChatService:
    def __init__(self):
        self.graph = create_graph()
        self.state: AgentMemory = {
            "messages": [],
            "especialista_aeo_output": None,
            "informacion_informe": None,
            "informe_confirmado": False,
        }

    async def chat(self, user_input: str):
        user_input = (user_input or "").strip()
        if not user_input:
            return "(mensaje vacío)"

        self.state["messages"].append(("user", user_input))

        out = await self.graph.ainvoke(self.state)

        self.state["messages"] = out["messages"]
        self.state = save_aeo_output(self.state)

        estado_informe = extract_updated_informe_from_ai(self.state["messages"])
        if estado_informe:
            if "informacion_informe" in estado_informe:
                self.state["informacion_informe"] = estado_informe["informacion_informe"]
            if "informe_confirmado" in estado_informe:
                self.state["informe_confirmado"] = estado_informe["informe_confirmado"]

        reply = get_last_assistant_text(self.state["messages"]) or "(sin respuesta)"
        return reply

# =========================
# EXAMPLE
# =========================

import asyncio

if __name__ == "__main__":
    chat = ChatService()

    print("Agente Emilio orquestador listo. Escribe 'exit' para salir.\n")

    async def main():
        while True:
            user_input = input("Tú: ")

            if user_input.lower() in ["exit", "quit"]:
                break

            reply = await chat.chat(user_input)
            print(f"\nAgente: {reply}\n")

    asyncio.run(main())