from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from typing import Any
from playwright.async_api import async_playwright


DEBUG_HOLD_ON_ERROR_MS = int(os.environ.get("AEO_DEBUG_HOLD_ON_ERROR_MS", "60000"))


def dbg(msg: str) -> None:
    #print(f"[AEO DEBUG] {msg}", flush=True)
    return None

def debug_artifact_paths(prefix: str = "aeo_debug") -> tuple[Path, Path]:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path("debug")
    out_dir.mkdir(exist_ok=True)
    html_path = out_dir / f"{prefix}_{ts}.html"
    png_path = out_dir / f"{prefix}_{ts}.png"
    return html_path, png_path


async def dump_debug_artifacts(page, prefix: str = "aeo_debug") -> dict:
    html_path, png_path = debug_artifact_paths(prefix)

    try:
        html = await page.content()
        html_path.write_text(html, encoding="utf-8")
        dbg(f"HTML guardado en: {html_path}")
    except Exception as e:
        dbg(f"No se pudo guardar HTML: {e}")

    try:
        await page.screenshot(path=str(png_path), full_page=True)
        dbg(f"Screenshot guardado en: {png_path}")
    except Exception as e:
        dbg(f"No se pudo guardar screenshot: {e}")

    return {
        "html_path": str(html_path),
        "screenshot_path": str(png_path),
    }


async def reject_cookies_if_present(page) -> dict:
    info = {
        "banner_found": False,
        "rejected": False,
    }

    try:
        banner = page.locator("#hs-eu-cookie-confirmation")
        if await banner.count() > 0:
            info["banner_found"] = True
            dbg("Cookie banner detectado")

            reject_btn = page.locator("#hs-eu-decline-button")
            if await reject_btn.count() > 0:
                dbg("Click en 'Rechazar todas'")
                await reject_btn.first.click(timeout=5000)
                await page.wait_for_timeout(1500)
                info["rejected"] = True
                dbg("Cookies rechazadas")
            else:
                dbg("No se encontró #hs-eu-decline-button")
    except Exception as e:
        dbg(f"Error gestionando cookies: {e}")

    return info


async def snapshot_step_state(page, label: str) -> None:
    try:
        form = page.locator("form.msf")
        if await form.count() == 0:
            dbg(f"{label} | no existe form.msf")
            return

        step = await form.get_attribute("data-step")
        last_step = await form.get_attribute("data-last-step")
        dbg(f"{label} | data-step={step} data-last-step={last_step}")

        active_step = page.locator("form.msf li.msf-step[data-active='true']")
        if await active_step.count() == 0:
            dbg(f"{label} | no hay active step")
            return

        fields = active_step.locator("input, select")
        count = await fields.count()
        dbg(f"{label} | active_fields={count}")

        for i in range(count):
            field = fields.nth(i)
            tag = await field.evaluate("(el) => el.tagName.toLowerCase()")
            name = await field.get_attribute("name")
            typ = await field.get_attribute("type")
            readonly = await field.get_attribute("readonly")
            disabled = await field.get_attribute("disabled")

            try:
                value = await field.input_value()
            except Exception:
                value = None

            dbg(
                f"{label} | field[{i}] tag={tag} name={name} type={typ} "
                f"value={value!r} readonly={readonly} disabled={disabled}"
            )

        next_btn = page.locator("form.msf button.msf-next")
        submit_btn = page.locator("form.msf button.msf-submit")

        if await next_btn.count() > 0:
            dbg(f"{label} | next_disabled={await next_btn.first.is_disabled()}")
        if await submit_btn.count() > 0:
            dbg(f"{label} | submit_disabled={await submit_btn.first.is_disabled()}")

    except Exception as e:
        dbg(f"{label} | snapshot error: {e}")


async def robust_fill_input(field, value: str, name: str, page) -> None:
    dbg(f"Rellenando input {name}={value!r}")

    await field.wait_for(state="visible", timeout=10000)
    await field.scroll_into_view_if_needed()
    await field.click()

    try:
        await field.fill("")
    except Exception:
        try:
            await field.press("Control+A")
            await field.press("Backspace")
        except Exception:
            pass

    await field.fill(str(value))

    await field.evaluate(
        """(el, value) => {
            const proto = el.tagName.toLowerCase() === 'input'
              ? window.HTMLInputElement.prototype
              : window.HTMLTextAreaElement.prototype;

            const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
            setter.call(el, value);

            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.dispatchEvent(new Event('blur', { bubbles: true }));
        }""",
        str(value),
    )

    try:
        await field.press("Tab")
    except Exception:
        pass

    await page.wait_for_timeout(700)

    try:
        current_value = await field.input_value()
        dbg(f"{name} tras fill/dispatch={current_value!r}")
    except Exception:
        pass


async def fill_active_step_from_payload(
    page,
    payload: dict,
    skip_names: set[str] | None = None,
) -> list[str]:
    filled = []
    skip_names = skip_names or set()

    active_step = page.locator("form.msf li.msf-step[data-active='true']")
    fields = active_step.locator("input, select")
    count = await fields.count()

    dbg(f"fill_active_step_from_payload | fields={count}")

    for i in range(count):
        field = fields.nth(i)
        tag = await field.evaluate("(el) => el.tagName.toLowerCase()")
        name = await field.get_attribute("name")
        typ = await field.get_attribute("type")
        readonly = await field.get_attribute("readonly")
        disabled = await field.get_attribute("disabled")

        if not name or name in skip_names:
            continue
        if readonly is not None or disabled is not None:
            dbg(f"Saltando field name={name} readonly/disabled")
            continue
        if name not in payload:
            dbg(f"Sin valor en payload para name={name}")
            continue

        value = payload[name]

        if tag == "input":
            if typ == "checkbox":
                if bool(value):
                    dbg(f"Marcando checkbox {name}")
                    await field.check()
                    filled.append(name)
            else:
                await robust_fill_input(field, str(value), name, page)
                filled.append(name)

        elif tag == "select":
            dbg(f"Seleccionando select {name}={value}")
            await field.select_option(value=str(value))
            filled.append(name)

    return filled


async def open_aeo_modal_and_wait_email_step(page) -> None:
    dbg("Buscando CTA para abrir modal")
    trigger = page.locator("button[data-cl-modal='llm-grader-form-modal']").first
    await trigger.wait_for(state="visible", timeout=15000)
    await trigger.click()

    dbg("Esperando modal")
    await page.locator("#multi-step-form").wait_for(state="visible", timeout=15000)

    dbg("Esperando step 1 con email")
    email_input = page.locator(
        "form.msf li.msf-step[data-active='true'] input[name='email']"
    ).first
    await email_input.wait_for(state="visible", timeout=15000)

    await page.wait_for_timeout(800)


async def fill_email_and_advance(page, email: str) -> None:
    email_input = page.locator(
        "form.msf li.msf-step[data-active='true'] input[name='email']"
    ).first
    next_btn = page.locator("form.msf button.msf-next").first

    await email_input.wait_for(state="visible", timeout=15000)
    await email_input.scroll_into_view_if_needed()
    await email_input.click()

    await email_input.fill("")
    await page.wait_for_timeout(150)

    await email_input.type(email, delay=80)
    await email_input.dispatch_event("input")
    await page.wait_for_timeout(150)
    await email_input.dispatch_event("change")
    await page.wait_for_timeout(150)

    try:
        await email_input.press("Tab")
    except Exception:
        pass

    for i in range(20):
        try:
            disabled = await next_btn.is_disabled()
            value = await email_input.input_value()
            dbg(f"email_step wait[{i}] value={value!r} next_disabled={disabled}")
            if not disabled:
                break
        except Exception as e:
            dbg(f"email_step wait[{i}] error={e}")
        await page.wait_for_timeout(300)

    if await next_btn.is_disabled():
        await email_input.evaluate(
            """(el) => {
                el.focus();
                el.blur();
                el.dispatchEvent(new FocusEvent('blur', { bubbles: true }));
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
            }"""
        )

        for i in range(10):
            disabled = await next_btn.is_disabled()
            dbg(f"email_step retry[{i}] next_disabled={disabled}")
            if not disabled:
                break
            await page.wait_for_timeout(300)

    if await next_btn.is_disabled():
        raise RuntimeError("El botón Siguiente sigue deshabilitado tras rellenar el email.")

    dbg("Click en Siguiente tras email")
    await next_btn.click()
    await page.wait_for_timeout(1500)


async def unlock_full_aeo_content(page, payload: dict) -> dict:
    result = {
        "modal_opened": False,
        "steps_completed": [],
        "submitted": False,
        "unlock_detected": False,
    }

    await open_aeo_modal_and_wait_email_step(page)
    result["modal_opened"] = True
    dbg("Modal abierto desde CTA")

    await snapshot_step_state(page, "before_email_step")
    await fill_email_and_advance(page, payload["email"])
    result["steps_completed"].append("next_step_1_email")

    max_loops = 8
    for loop_idx in range(max_loops):
        dbg(f"Loop post-email #{loop_idx + 1}")
        await snapshot_step_state(page, f"post_email_loop_{loop_idx+1}_before")

        form = page.locator("form.msf")
        await form.wait_for(timeout=15000)

        step = await form.get_attribute("data-step")
        last_step = await form.get_attribute("data-last-step")
        dbg(f"Paso actual={step} last_step={last_step}")

        filled_names = await fill_active_step_from_payload(
            page,
            payload,
            skip_names={"email"},
        )
        dbg(f"Campos rellenados en este step: {filled_names}")

        talk_checkbox = page.locator("#talk-to-sales-checkbox")
        if payload.get("talk_to_sales") and await talk_checkbox.count() > 0:
            if not await talk_checkbox.is_checked():
                dbg("Marcando talk-to-sales-checkbox")
                await talk_checkbox.check()

        next_btn = page.locator("form.msf button.msf-next")
        submit_btn = page.locator("form.msf button.msf-submit")

        for _ in range(12):
            next_disabled = True
            submit_disabled = True

            if await next_btn.count() > 0:
                next_disabled = await next_btn.first.is_disabled()
            if await submit_btn.count() > 0:
                submit_disabled = await submit_btn.first.is_disabled()

            dbg(
                f"post-fill wait | step={step} "
                f"next_disabled={next_disabled} submit_disabled={submit_disabled}"
            )

            if not next_disabled or not submit_disabled:
                break

            await page.wait_for_timeout(400)

        await snapshot_step_state(page, f"post_email_loop_{loop_idx+1}_after_fill")

        can_submit = (
            await submit_btn.count() > 0
            and not await submit_btn.first.is_disabled()
            and last_step == "true"
        )
        if can_submit:
            dbg("Submit disponible y habilitado. Click en Descargar ahora")
            await submit_btn.first.click()
            result["submitted"] = True
            result["steps_completed"].append(f"submit_step_{step}")
            break

        can_next = (
            await next_btn.count() > 0
            and not await next_btn.first.is_disabled()
        )
        if can_next:
            dbg("Next disponible y habilitado. Avanzando")
            await next_btn.first.click()
            result["steps_completed"].append(f"next_step_{step}")
            await page.wait_for_timeout(1800)
            continue

        await snapshot_step_state(page, f"post_email_loop_{loop_idx+1}_stalled")
        raise RuntimeError(
            f"No se puede avanzar ni enviar en el step {step} después del email."
        )

    dbg("Esperando desbloqueo tras submit")
    await page.wait_for_timeout(5000)

    modal_visible = False
    try:
        modal_visible = await page.locator("#multi-step-form").is_visible()
    except Exception:
        modal_visible = False

    body_len = len(await page.locator("body").inner_text())
    dbg(f"Post-submit | modal_visible={modal_visible} body_len={body_len}")

    result["unlock_detected"] = not modal_visible
    return result


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
            "https://www.hubspot.es/aeo-grader/results?" + urlencode(params)
        )

    return data


async def buscar_aeo(input_data: str) -> str:
    try:
        dbg(f"input_data raw={input_data}")

        data = parse_input_data(input_data)
        dbg(f"input_data parsed={json.dumps(data, ensure_ascii=False)}")

        brand_name = data["brand_name"]
        geography = data["geography"]
        aeo_grader_url = data["aeo_grader_url"]

        unlock_payload = {
            "email": "tech@suntzu-growth.com",
            "firstname": "Oscar",
            "lastname": "Cordero",
            "phone": "698124789",
            "website": "https://www.suntzu-growth.com",
            "employees__c": "4",
            "talk_to_sales": False,
            "reject_cookies": True,
        }

        dbg(f"unlock_payload={json.dumps(unlock_payload, ensure_ascii=False)}")

        page_data = {}

        async with async_playwright() as p:
            dbg("Lanzando navegador Playwright...")
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            try:
                dbg(f"Abriendo URL: {aeo_grader_url}")
                await page.goto(
                    aeo_grader_url,
                    wait_until="domcontentloaded",
                    timeout=60000,
                )

                dbg(f"URL final cargada: {page.url}")
                dbg(f"Título página: {await page.title()}")

                await page.wait_for_timeout(3000)

                cookie_info = {}
                if unlock_payload.get("reject_cookies"):
                    cookie_info = await reject_cookies_if_present(page)
                dbg(f"cookie_info={json.dumps(cookie_info, ensure_ascii=False)}")

                await page.wait_for_timeout(2500)

                before_body = await page.locator("body").inner_text()
                before_len = len(before_body)
                dbg(f"body_length_before_unlock={before_len}")

                unlock_info = await unlock_full_aeo_content(page, unlock_payload)
                dbg(f"unlock_info={json.dumps(unlock_info, ensure_ascii=False)}")

                await page.wait_for_timeout(5000)

                after_body = await page.locator("body").inner_text()
                after_len = len(after_body)
                dbg(f"body_length_after_unlock={after_len}")

                unlock_detected = (
                    unlock_info.get("unlock_detected", False)
                    or after_len > before_len + 1500
                )
                dbg(f"unlock_detected={unlock_detected}")

                page_data = await page.evaluate("""() => {
                    const collectTexts = (selector) =>
                        Array.from(document.querySelectorAll(selector))
                            .map(el => (el.innerText || "").trim())
                            .filter(Boolean);

                    const bodyText = document.body?.innerText || "";

                    const extractGlobalScoresFromBody = (text) => {
                        const providers = [
                            { label: "ChatGPT", marker: "El potente modelo de ChatGPT" },
                            { label: "Perplexity", marker: "Respuestas con IA en tiempo real" },
                            { label: "Gemini", marker: "Usa los resultados de búsqueda de Google" }
                        ];

                        const results = [];

                        for (const provider of providers) {
                            const idx = text.indexOf(provider.marker);
                            if (idx === -1) continue;

                            const chunk = text.slice(idx, idx + 500);
                            const scoreMatch = chunk.match(/Calificación global:?\\s*(\\d{2,3})|\\b(\\d{2,3})\\b/);

                            let score = null;
                            if (scoreMatch) {
                                score = parseInt(scoreMatch[1] || scoreMatch[2], 10);
                            }

                            results.push({
                                provider: provider.label,
                                score,
                                raw: chunk.slice(0, 300)
                            });
                        }

                        return results;
                    };

                    const extractDimensionFractions = (text) => {
                        const dimensionLabels = [
                            "Reconocimiento de la marca",
                            "Posición en el mercado",
                            "Calidad de la presencia",
                            "Percepción de la marca",
                            "Cuota de participación"
                        ];

                        return dimensionLabels.map(label => {
                            const idx = text.indexOf(label);
                            if (idx === -1) {
                                return { dimension: label, values: [] };
                            }

                            const chunk = text.slice(idx, idx + 350);
                            const matches = [...chunk.matchAll(/(\\d+\\/\\d+)/g)].map(m => m[1]);

                            return {
                                dimension: label,
                                values: matches,
                                raw: chunk.slice(0, 250)
                            };
                        });
                    };

                    return {
                        url: window.location.href,
                        title: document.title,
                        h1: collectTexts("h1"),
                        h2: collectTexts("h2"),
                        h3: collectTexts("h3"),
                        paragraphs: collectTexts("p").slice(0, 120),
                        body: bodyText.slice(0, 30000),
                        global_scores: extractGlobalScoresFromBody(bodyText),
                        dimension_scores: extractDimensionFractions(bodyText)
                    };
                }""")

                dbg(
                    "global_scores="
                    + json.dumps(page_data.get("global_scores", []), ensure_ascii=False)
                )
                dbg(
                    "dimension_scores="
                    + json.dumps(page_data.get("dimension_scores", []), ensure_ascii=False)
                )

                page_data["cookie_info"] = cookie_info
                page_data["unlock_info"] = unlock_info
                page_data["unlock_detected"] = unlock_detected
                page_data["body_length_before_unlock"] = before_len
                page_data["body_length_after_unlock"] = after_len

            except Exception as e:
                dbg(f"EXCEPCIÓN INTERNA EN PLAYWRIGHT: {repr(e)}")
                
            finally:
                if page_data.get("error"):
                    dbg(
                        f"Error detectado: mantengo navegador abierto "
                        f"{DEBUG_HOLD_ON_ERROR_MS} ms para inspección manual..."
                    )
                    try:
                        await page.wait_for_timeout(DEBUG_HOLD_ON_ERROR_MS)
                    except Exception:
                        pass

                dbg("Cerrando navegador...")
                await browser.close()

        if "error" in page_data:
            dbg("Resultado final: ERROR")
            return json.dumps(
                {
                    "input_data": data,
                    "message": f"No se pudo completar el análisis AEO: {page_data['error']}",
                    "status": "error",
                    "page_data": page_data,
                },
                ensure_ascii=False,
            )

        if not page_data.get("unlock_detected"):
            dbg("Resultado final: ERROR unlock no detectado")
            return json.dumps(
                {
                    "input_data": data,
                    "message": (
                        f"Se cargó la página de resultados para {brand_name}, "
                        f"pero no se pudo confirmar el desbloqueo completo del contenido."
                    ),
                    "status": "error",
                    "page_data": page_data,
                },
                ensure_ascii=False,
            )

        dbg("Resultado final: SUCCESS")
        return json.dumps(
            {
                "input_data": data,
                "message": (
                    f"Análisis AEO ejecutado correctamente para {brand_name} "
                    f"en {geography}. Contenido completo desbloqueado en la misma URL."
                ),
                "status": "success",
                "page_data": page_data,
            },
            ensure_ascii=False,
        )

    except Exception as e:
        dbg(f"EXCEPCIÓN OUTER buscar_aeo: {repr(e)}")
        return json.dumps(
            {
                "input_data": input_data,
                "message": f"Error en buscar_aeo: {str(e)}",
                "status": "error",
            },
            ensure_ascii=False,
        )
    
async def tool_aeo_node(state: dict[str, Any]) -> dict[str, Any]:
    print("TOOL AEO: LLAMADA API")

    input_data = state.get("input_data")

    if not input_data:
        return {
            "status": "error",
            "response_msg": "Falta `input_data` en el subestado AEO.",
            "aeo_data": None,
        }

    raw_result = await buscar_aeo(input_data)

    try:
        aeo_data = json.loads(raw_result)
    except Exception:
        aeo_data = {
            "status": "error",
            "message": "La tool AEO devolvió una respuesta no parseable.",
            "raw_output": raw_result,
        }

    state["aeo_data"] = aeo_data
    state["status"] = aeo_data.get("status", "error")
    state["response_msg"] = aeo_data.get("message")

    return state