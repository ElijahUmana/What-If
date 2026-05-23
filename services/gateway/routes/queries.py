import asyncio

from fastapi import APIRouter
from pydantic import BaseModel
import ulid

from .. import state
from .. import orchestrator

router = APIRouter()

class SubmitQueryRequest(BaseModel):
    text: str
    anchor_pts_ms: int | None = None

@router.post("/sessions/{session_id}/queries")
async def submit_query(session_id: str, req: SubmitQueryRequest):
    query_id = f"qr_{ulid.new()}"
    query = {
        "id": query_id,
        "session_id": session_id,
        "text": req.text,
        "anchor_pts_ms": req.anchor_pts_ms,
        "status": "received",
    }
    state.queries.setdefault(session_id, []).append(query)
    await state.broadcast(session_id, "query.progress", {"query_id": query_id, "stage": "received"})
    asyncio.create_task(orchestrator.handle_whatif(session_id, query_id, req.text, req.anchor_pts_ms))
    return query

@router.get("/sessions/{session_id}/queries")
async def list_queries(session_id: str):
    return state.queries.get(session_id, [])
