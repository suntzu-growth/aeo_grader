from __future__ import annotations

import os
import uuid
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from storage_utils import list_informes_from_gcs
from emilio import ChatService

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
