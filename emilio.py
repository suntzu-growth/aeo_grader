from __future__ import annotations

import os
import json
from datetime import date
from typing import Any, Optional, TypedDict, Annotated

import yaml
from dotenv import load_dotenv
import json
from urllib.parse import urlencode
from steel import Steel
from playwright.async_api import async_playwright

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    AIMessage,
    ToolMessage,
    SystemMessage,
)
from langchain_core.tools import StructuredTool
from langgraph.graph import StateGraph, END
from tools.gsc_tool import buscar_gsc
from tools.ga4_tool import buscar_ga4
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode


# =========================
# STATE
# =========================

class AEOInput(TypedDict, total=False):
    brand_name: Optional[str]
    geography: Optional[str]
    products_services: Optional[str]
    sector_industry: Optional[str]
    aeo_grader_url: Optional[str]
    html_output_path: Optional[str]


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    flag_html: bool
    data_aeo: Optional[dict]
    aeo_input: AEOInput


def create_initial_state() -> AgentState:
    return {
        "messages": [],
        "flag_html": False,
        "aeo_input": {
            "brand_name": None,
            "geography": None,
            "products_services": None,
            "sector_industry": None,
            "aeo_grader_url": None,
            "html_output_path": None,
        },
        "data_aeo": None,
    }


# =========================
# HELPERS
# =========================

REQUIRED_FIELDS = [
    "brand_name",
    "geography",
    "products_services",
    "sector_industry",
]

def get_last_assistant_text(messages):
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            content = msg.content

            # Gemini devuelve lista de bloques
            if isinstance(content, list):
                return " ".join(
                    block.get("text", "") for block in content if isinstance(block, dict)
                )

            return content

    return None

def load_prompt(path: str = "prompt.yml") -> str:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["general_prompt"]


def get_missing_fields(state: AgentState) -> list[str]:
    required = [
        "brand_name",
        "geography",
        "products_services",
        "sector_industry",
    ]

    aeo_input = state.get("aeo_input", {})
    missing = [
        key for key in required
        if not aeo_input.get(key)
    ]

    return missing


def update_state_from_tool_messages(state: AgentState) -> AgentState:
    """
    Busca el último ToolMessage de buscar_aeo y lo guarda en data_aeo.
    """
    new_data_aeo = state["data_aeo"]

    for msg in reversed(state["messages"]):
        if isinstance(msg, ToolMessage) and getattr(msg, "name", None) == "buscar_aeo":
            try:
                new_data_aeo = json.loads(msg.content)
            except json.JSONDecodeError:
                new_data_aeo = {"raw_output": msg.content}
            break

    return {
        **state,
        "data_aeo": new_data_aeo,
    }


def build_system_message(state: AgentState, prompt_text: str) -> SystemMessage:
    missing = get_missing_fields(state)

    state_view = {
        "aeo_input": state.get("aeo_input", {}),
        "missing_fields": missing,
        "has_data_aeo": state.get("data_aeo") is not None,
    }

    content = f"""
        {prompt_text}

        ========================
        CONTEXTO TEMPORAL
        ========================
        Fecha actual: {date.today().strftime('%Y-%m-%d')}
        Hoy es: {date.today().strftime('%A, %d de %B de %Y')}

        ========================
        ESTADO ACTUAL (FUENTE DE VERDAD)
        ========================
        {json.dumps(state_view, ensure_ascii=False, indent=2)}

        Reglas:
        - Usa `aeo_input` como memoria estructurada
        - NO inventes valores que no estén en `aeo_input` o confirmados por el usuario
        - Si el usuario proporciona nuevos datos, intégralos mentalmente en `aeo_input`
        - Cuando tengas todos los campos obligatorios, construye un JSON completo y llama a la tool
        """
    return SystemMessage(content=content)

# =========================
# TOOL
# =========================

def parse_input_data(input_data: str) -> dict:
    data = json.loads(input_data)

    required = ["brand_name", "geography", "sector_industry", "products_services"]
    for field in required:
        if not data.get(field):
            raise ValueError(f"Campo requerido faltante: {field}")

    if not data.get("aeo_grader_url"):
        params = {
            "companyName": data["brand_name"],
            "geography": data["geography"],
            "productsServices": data["products_services"],
            "industry": data["sector_industry"],
        }
        data["aeo_grader_url"] = (
            "https://www.hubspot.com/aeo-grader/results?" + urlencode(params)
        )

    return data

async def buscar_aeo(input_data: str) -> str:
    try:
        data = parse_input_data(input_data)

        brand_name = data["brand_name"]
        geography = data["geography"]
        sector_industry = data["sector_industry"]
        products_services = data["products_services"]
        aeo_grader_url = data["aeo_grader_url"]

        page_data = {}

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            try:
                await page.goto(
                    aeo_grader_url,
                    wait_until="domcontentloaded",
                    timeout=30000,
                )

                await page.wait_for_timeout(2000)

                # Dismiss cookie consent if present
                try:
                    accept_btn = page.locator("#hs-eu-confirmation-button")
                    if await accept_btn.is_visible(timeout=4000):
                        await accept_btn.click()
                        await page.wait_for_timeout(1500)
                except Exception:
                    pass  # No cookie banner, proceed

                # Wait for AEO results to render
                try:
                    await page.wait_for_selector("text=ChatGPT", timeout=60000)
                    await page.wait_for_timeout(3000)
                except Exception:
                    await page.wait_for_timeout(8000)  # fallback wait

                # EXTRAEMOS SCORES REALES
                page_data = await page.evaluate("""() => {
                    const getScoreBlocks = () => {
                        const blocks = [];
                        const providers = document.querySelectorAll("h3, h2");

                        providers.forEach(el => {
                            const text = el.innerText || "";

                            if (
                                text.includes("ChatGPT") ||
                                text.includes("Perplexity") ||
                                text.includes("Gemini")
                            ) {
                                const parent = el.closest("div");
                                if (!parent) return;

                                const scoreEl = parent.querySelector("div");
                                const scoreText = parent.innerText;

                                const match = scoreText.match(/\\b(\\d{2})\\b/);

                                blocks.push({
                                    provider: text,
                                    score: match ? parseInt(match[1]) : null,
                                    raw: scoreText.slice(0, 200)
                                });
                            }
                        });

                        return blocks;
                    };

                    return {
                        url: window.location.href,
                        title: document.title,
                        scores: getScoreBlocks(),
                        body: document.body.innerText.slice(0, 5000)
                    };
                }""")

            except Exception as e:
                page_data = {
                    "error": f"Error cargando resultados: {str(e)}"
                }

            await browser.close()

        if "error" in page_data:
            return json.dumps(
                {
                    "input_data": data,
                    "message": f"No se pudo completar el análisis AEO: {page_data['error']}",
                    "status": "error",
                    "page_data": page_data,
                },
                ensure_ascii=False,
            )

        return json.dumps(
            {
                "input_data": data,
                "message": f"Análisis AEO ejecutado correctamente para {brand_name}",
                "status": "success",
                "page_data": page_data,
            },
            ensure_ascii=False,
        )

    except Exception as e:
        return json.dumps(
            {
                "input_data": input_data,
                "message": f"Error en buscar_aeo: {str(e)}",
                "status": "error",
            },
            ensure_ascii=False,
        )


buscar_aeo_tool = StructuredTool.from_function(
    func=None,
    coroutine=buscar_aeo,
    name="buscar_aeo",
    description=(
        "Ejecuta un análisis AEO. "
        "Recibe un único parámetro `input_data`, que debe ser un JSON string con: "
        "brand_name, geography, products_services, sector_industry, "
        "y opcionalmente aeo_grader_url."
    ),
    return_direct=False,
)

buscar_ga4_tool = StructuredTool.from_function(
    func=None,
    coroutine=buscar_ga4,
    name="buscar_ga4",
    description=(
        "Consulta Google Analytics 4 para obtener datos de tráfico y comportamiento. "
        "Recibe un único parámetro `input_data`, que debe ser un JSON string con: "
        "property_id (requerido, solo el número, ej: '123456789'), "
        "start_date (opcional, 'YYYY-MM-DD'), "
        "end_date (opcional, 'YYYY-MM-DD'), "
        "metrics (opcional, lista, ej: ['sessions', 'activeUsers', 'screenPageViews']), "
        "dimensions (opcional, lista, ej: ['pagePath', 'sessionSource']), "
        "row_limit (opcional, int, default 10)."
    ),
    return_direct=False,
)

buscar_gsc_tool = StructuredTool.from_function(
    func=None,
    coroutine=buscar_gsc,
    name="buscar_gsc",
    description=(
        "Consulta Google Search Console para obtener datos de rendimiento SEO. "
        "Recibe un único parámetro `input_data`, que debe ser un JSON string con: "
        "site_url (requerido, ej: 'https://www.ejemplo.com/'), "
        "start_date (opcional, 'YYYY-MM-DD'), "
        "end_date (opcional, 'YYYY-MM-DD'), "
        "dimensions (opcional, lista: ['query', 'page', 'country', 'device']), "
        "row_limit (opcional, int, default 10)."
    ),
    return_direct=False,
)

# =========================
# NODES
# =========================

def make_agent_node(llm, prompt_text: str):
    llm_with_tools = llm.bind_tools([buscar_aeo_tool, buscar_ga4_tool, buscar_gsc_tool])

    async def agent_node(state: AgentState) -> dict:
        system_msg = build_system_message(state, prompt_text)
        response = await llm_with_tools.ainvoke([system_msg] + state["messages"])
        return {"messages": [response]}

    return agent_node


def route_after_agent(state: AgentState) -> str:
    last_message = state["messages"][-1]

    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"

    return END


def save_tool_output_node(state: AgentState) -> dict:
    new_data_aeo = state.get("data_aeo")
    new_aeo_input = state.get("aeo_input", {})

    for msg in reversed(state["messages"]):
        if isinstance(msg, ToolMessage) and msg.name == "buscar_aeo":
            try:
                tool_output = json.loads(msg.content)

                # Guardar resultado
                new_data_aeo = tool_output

                # guardar también el input usado
                if "input_data" in tool_output:
                    new_aeo_input = tool_output["input_data"]

            except Exception:
                new_data_aeo = {"raw_output": msg.content}
            break

    return {
        "data_aeo": new_data_aeo,
        "aeo_input": new_aeo_input,
    }
from langgraph.checkpoint.memory import MemorySaver

# =========================
# GRAPH
# =========================

def create_graph():
    load_dotenv()

    llm = ChatGoogleGenerativeAI(
        model=os.getenv("LLM_MODEL"),
        temperature=0,
    )

    prompt_text = load_prompt("prompt.yml")

    graph = StateGraph(AgentState)

    agent_node = make_agent_node(llm, prompt_text)
    tool_node = ToolNode([buscar_aeo_tool, buscar_ga4_tool, buscar_gsc_tool])

    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.add_node("save_tool_output", save_tool_output_node)

    graph.set_entry_point("agent")

    graph.add_conditional_edges(
        "agent",
        route_after_agent,
        {
            "tools": "tools",
            END: END,
        },
    )

    graph.add_edge("tools", "save_tool_output")
    graph.add_edge("save_tool_output", "agent")

    # Añadimos checkpointer para memoria persistente e hilos en LangSmith
    memory = MemorySaver()
    return graph.compile(checkpointer=memory)


# =========================
# EXAMPLE / SERVICE
# =========================
class ChatService:
    def __init__(self):
        self.graph = create_graph()
        # El estado inicial ya no se guarda manualmente aquí, 
        # se gestionará por el checkpointer usando el thread_id.

    async def chat(self, user_input: str, session_id: str):
        config = {"configurable": {"thread_id": session_id}}
        
        # Enviamos el mensaje
        input_msg = HumanMessage(content=user_input)
        
        # Ejecutamos el grafo con el config (hilos)
        # LangGraph se encarga de recuperar/guardar los mensajes previos
        out = await self.graph.ainvoke({"messages": [input_msg]}, config=config)
        
        # Guardamos el estado para referencia (opcional, el checkpointer ya lo tiene)
        last_messages = out.get("messages", [])
        
        # LOG PARA DEPURACIÓN
        print(f"DEBUG: Ultimo mensaje de la IA para session {session_id}: {last_messages[-1] if last_messages else 'None'}")

        reply = get_last_assistant_text(last_messages) or "(sin respuesta técnica)"

        return reply

import asyncio

if __name__ == "__main__":
    chat = ChatService()

    print("Agente AEO listo. Escribe 'exit' para salir.\n")

    async def main():
        while True:
            user_input = input("👤 Tú: ")

            if user_input.lower() in ["exit", "quit"]:
                break

            reply = await chat.chat(user_input)

            print(f"\n Agente: {reply}\n")

    asyncio.run(main())
