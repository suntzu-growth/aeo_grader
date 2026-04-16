from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

REPORT_TEMPLATE_PATH = "./rag/example_report.html"

DEFAULT_SYSTEM_PROMPT = """
Eres un generador experto de informes HTML ejecutivos.

Tu tarea consiste en:
1. Recibir un HTML de ejemplo completo como referencia visual, estructural y estilística.
2. Recibir unos datos estructurados en `informacion_informe`.
3. Devolver un HTML final completo, listo para guardarse como archivo `.html`.

Objetivo:
- Usa el HTML de ejemplo como base de diseño, estructura, tono y nivel de detalle.
- Sustituye el contenido del ejemplo por contenido derivado de `informacion_informe`.
- Mantén una presentación premium, clara, ejecutiva y visualmente sólida.

Reglas obligatorias:
- Devuelve SOLO HTML válido.
- No devuelvas markdown.
- No devuelvas bloques ```html.
- No expliques nada fuera del HTML.
- Conserva el estilo, layout, CSS, secciones principales y enfoque visual del ejemplo siempre que tenga sentido.
- Reescribe títulos, textos, métricas, tablas, bloques de análisis y plan de acción en función de `informacion_informe`.
- No inventes hechos, métricas, competidores, rankings ni resultados no presentes o no inferibles de forma segura desde `informacion_informe`.
- Si faltan datos, adapta el contenido de forma elegante sin dejar placeholders rotos.
- Si una visualización no puede sostenerse con datos reales, simplifícala o elimínala sin romper el diseño general.
- El HTML final debe quedar autocontenido y coherente.
- Respeta el idioma de entrada, salvo que los datos indiquen otra cosa.
- Mantén el JavaScript necesario si el ejemplo incluye gráficos o interactividad, pero actualiza los datos para que sean consistentes con el informe generado.
""".strip()


def load_prompt(path: str = "./prompt.yml") -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data.get("prompt_informes") or DEFAULT_SYSTEM_PROMPT
    except Exception:
        return DEFAULT_SYSTEM_PROMPT


def _load_report_template(path: str = REPORT_TEMPLATE_PATH) -> str:
    template_path = Path(path)
    if not template_path.exists():
        raise FileNotFoundError(
            f"No se encontró el HTML de ejemplo en: {template_path}"
        )
    return template_path.read_text(encoding="utf-8")


def _extract_text_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text")
                if text:
                    parts.append(str(text))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts).strip()

    return str(content).strip()


def _clean_llm_html_output(raw_content: str) -> str:
    """
    Limpia respuestas del LLM cuando por error envuelve el HTML en markdown
    o añade texto extra antes/después.
    """
    content = raw_content.strip()

    # Elimina fences markdown si aparecen
    content = re.sub(r"^```html\s*", "", content, flags=re.IGNORECASE)
    content = re.sub(r"^```\s*", "", content)
    content = re.sub(r"\s*```$", "", content)

    # Si hay texto extra, intenta recortar desde el doctype o el <html>
    doctype_idx = content.lower().find("<!doctype html")
    html_idx = content.lower().find("<html")

    start_idx = -1
    if doctype_idx != -1:
        start_idx = doctype_idx
    elif html_idx != -1:
        start_idx = html_idx

    if start_idx > 0:
        content = content[start_idx:].strip()

    # Intenta cortar al cierre de </html> si hay basura después
    end_match = re.search(r"</html\s*>", content, flags=re.IGNORECASE)
    if end_match:
        content = content[:end_match.end()].strip()

    return content


def _looks_like_html(text: str) -> bool:
    text_lower = text.lower()
    return (
        "<html" in text_lower
        and "</html>" in text_lower
        and "<body" in text_lower
    )


async def crear_informe(input_data: str) -> str:
    load_dotenv()
    print("REALIZANDO INFORME")
    try:
        data = json.loads(input_data)
    except json.JSONDecodeError:
        return json.dumps(
            {
                "status": "error",
                "message": "El `input_data` no es un JSON válido.",
            },
            ensure_ascii=False,
        )

    if not data.get("confirmed"):
        return json.dumps(
            {
                "status": "error",
                "message": "No se puede generar el informe sin confirmación explícita del usuario.",
            },
            ensure_ascii=False,
        )

    informacion_informe = data.get("informacion_informe")
    if not informacion_informe:
        return json.dumps(
            {
                "status": "error",
                "message": "Falta `informacion_informe` para generar el informe.",
            },
            ensure_ascii=False,
        )

    example_html = _load_report_template(REPORT_TEMPLATE_PATH)
    system_prompt = load_prompt()

    model_name = os.getenv("LLM_MODEL_CLAUDE", "claude-sonnet-4-6")
    anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")

    if not anthropic_api_key:
        return json.dumps(
            {
                "status": "error",
                "message": "No se encontró ANTHROPIC_API_KEY en el entorno.",
            },
            ensure_ascii=False,
        )

    llm = ChatAnthropic(
        model=model_name,
        temperature=0,
        anthropic_api_key=anthropic_api_key,
        max_tokens=32000,
    )

    human_prompt = f"""
Genera el HTML final completo del informe.

### DATOS DEL INFORME
{json.dumps(informacion_informe, ensure_ascii=False, indent=2)}

### HTML DE EJEMPLO
Usa este HTML como referencia de estructura, diseño, tono, secciones, estilo visual, tablas, tarjetas, gráficos y layout general.
No lo devuelvas tal cual: reescríbelo con los datos nuevos.

{example_html}

### INSTRUCCIONES FINALES
- Devuelve solo el HTML final.
- Debe ser un documento completo, no fragmentos.
- Debe ser consistente de principio a fin.
- Debe conservar la calidad visual del ejemplo.
- Si cambias gráficos, tablas o bloques de análisis, asegúrate de que los textos y los números coincidan entre sí.
""".strip()

    try:
        response = await llm.ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=human_prompt),
            ]
        )
    except Exception as e:
        return json.dumps(
            {
                "status": "error",
                "message": f"Error invocando el LLM Anthropic: {str(e)}",
            },
            ensure_ascii=False,
        )

    raw_content = _extract_text_content(response.content)
    html_output = _clean_llm_html_output(raw_content)

    if not _looks_like_html(html_output):
        return json.dumps(
            {
                "status": "error",
                "message": "El LLM no devolvió un HTML completo válido.",
                "raw_output_preview": raw_content[:1500],
            },
            ensure_ascii=False,
        )

    output_dir = Path("./informes")
    output_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = output_dir / f"informe_aeo_{timestamp}.html"
    file_path.write_text(html_output, encoding="utf-8")

    return json.dumps(
        {
            "status": "success",
            "html": html_output,
        },
        ensure_ascii=False,
    )