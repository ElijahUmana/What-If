import asyncio

from fastapi import APIRouter
from pydantic import BaseModel
import ulid

from .. import state
from .. import orchestrator

router = APIRouter()

class CreateSessionRequest(BaseModel):
    source_url: str

class SessionResponse(BaseModel):
    session_id: str
    source_url: str
    ingest_status: str

@router.post("/sessions", response_model=SessionResponse)
async def create_session(req: CreateSessionRequest):
    session_id = f"ss_{ulid.new()}"
    session = {
        "id": session_id,
        "source_url": req.source_url,
        "ingest_status": "starting",
        "match_meta": {},
    }
    state.sessions[session_id] = session
    state.chunks[session_id] = []
    state.frames[session_id] = []
    state.captions[session_id] = []
    state.summaries[session_id] = []
    state.events[session_id] = []
    state.queries[session_id] = []
    state.clips[session_id] = []
    state.traces[session_id] = []
    state.commentary[session_id] = []
    asyncio.create_task(orchestrator.start_session(session_id, req.source_url))
    return SessionResponse(session_id=session_id, source_url=req.source_url, ingest_status="starting")

@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    return state.sessions.get(session_id, {"error": "not found"})
