from __future__ import annotations

import os
import uuid
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, HTMLResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from storage_utils import list_informes_from_gcs
from emilio import ChatService
from google_auth_oauthlib.flow import Flow

load_dotenv()

app = FastAPI(title="AEO Grader API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory session store
sessions: dict[str, ChatService] = {}

# Permite OAuth sobre HTTP en local
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

# GA4 OAuth
GA4_SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]
GA4_CLIENT_SECRETS = os.path.join(os.path.dirname(__file__), "ga4_client_secrets.json")
GA4_REDIRECT_URI = os.getenv("GA4_REDIRECT_URI", "http://localhost:8000/auth/ga4/callback")
ga4_credentials = None
ga4_flow_instance = None

# GSC OAuth
GSC_SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
GSC_CLIENT_SECRETS = os.path.join(os.path.dirname(__file__), "gsc_client_secrets.json")
GSC_REDIRECT_URI = os.getenv("GSC_REDIRECT_URI", "http://localhost:8000/auth/gsc/callback")
gsc_credentials = None
gsc_flow_instance = None


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    session_id: str


@app.get("/")
def health_check():
    return {"status": "ok", "service": "aeo-grader"}

@app.get("/informes")
def get_informes():
    try:
        return list_informes_from_gcs()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    session_id = request.session_id or str(uuid.uuid4())

    if session_id not in sessions:
        sessions[session_id] = ChatService()

    service = sessions[session_id]

    try:
        reply = await service.chat(request.message, session_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return ChatResponse(reply=reply, session_id=session_id)


@app.delete("/session/{session_id}")
def delete_session(session_id: str):
    if session_id in sessions:
        del sessions[session_id]
        return {"status": "deleted", "session_id": session_id}
    raise HTTPException(status_code=404, detail="Session not found")


# ── GA4 OAUTH ──

@app.get("/auth/ga4")
def auth_ga4():
    global ga4_flow_instance
    ga4_flow_instance = Flow.from_client_secrets_file(
        GA4_CLIENT_SECRETS,
        scopes=GA4_SCOPES,
        redirect_uri=GA4_REDIRECT_URI,
    )
    auth_url, _ = ga4_flow_instance.authorization_url(
        access_type="offline",
        prompt="consent",
    )
    return RedirectResponse(auth_url)


@app.get("/auth/ga4/callback")
def auth_ga4_callback(code: str):
    global ga4_credentials, ga4_flow_instance
    if ga4_flow_instance is None:
        raise HTTPException(status_code=400, detail="No hay flujo OAuth iniciado")
    ga4_flow_instance.fetch_token(code=code)
    ga4_credentials = ga4_flow_instance.credentials
    ga4_flow_instance = None
    return HTMLResponse("""
        <html><head><title>GA4 conectado</title></head>
        <body style="font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;background:#f8f9fb;">
          <div style="text-align:center;gap:12px;display:flex;flex-direction:column;align-items:center;">
            <div style="font-size:2.5rem;">✓</div>
            <div style="font-weight:700;font-size:1.1rem;">GA4 conectado</div>
            <div style="color:#6b7280;font-size:.9rem;">Puedes cerrar esta ventana.</div>
          </div>
          <script>setTimeout(() => window.close(), 1500);</script>
        </body></html>
    """)


@app.get("/auth/ga4/status")
def auth_ga4_status():
    connected = ga4_credentials is not None and bool(ga4_credentials.refresh_token)
    return {"connected": connected}


@app.delete("/auth/ga4")
def disconnect_ga4():
    global ga4_credentials, ga4_flow_instance
    ga4_credentials = None
    ga4_flow_instance = None
    return {"connected": False}


# ── GSC OAUTH ──

@app.get("/auth/gsc")
def auth_gsc():
    global gsc_flow_instance
    gsc_flow_instance = Flow.from_client_secrets_file(
        GSC_CLIENT_SECRETS,
        scopes=GSC_SCOPES,
        redirect_uri=GSC_REDIRECT_URI,
    )
    auth_url, _ = gsc_flow_instance.authorization_url(
        access_type="offline",
        prompt="consent",
    )
    return RedirectResponse(auth_url)


@app.get("/auth/gsc/callback")
def auth_gsc_callback(code: str):
    global gsc_credentials, gsc_flow_instance
    if gsc_flow_instance is None:
        raise HTTPException(status_code=400, detail="No hay flujo OAuth iniciado")
    gsc_flow_instance.fetch_token(code=code)
    gsc_credentials = gsc_flow_instance.credentials
    gsc_flow_instance = None
    return HTMLResponse("""
        <html><head><title>GSC conectado</title></head>
        <body style="font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;background:#f8f9fb;">
          <div style="text-align:center;gap:12px;display:flex;flex-direction:column;align-items:center;">
            <div style="font-size:2.5rem;">✓</div>
            <div style="font-weight:700;font-size:1.1rem;">Search Console conectado</div>
            <div style="color:#6b7280;font-size:.9rem;">Puedes cerrar esta ventana.</div>
          </div>
          <script>setTimeout(() => window.close(), 1500);</script>
        </body></html>
    """)


@app.get("/auth/gsc/status")
def auth_gsc_status():
    connected = gsc_credentials is not None and bool(gsc_credentials.refresh_token)
    return {"connected": connected}


@app.delete("/auth/gsc")
def disconnect_gsc():
    global gsc_credentials, gsc_flow_instance
    gsc_credentials = None
    gsc_flow_instance = None
    return {"connected": False}
