from fastapi import APIRouter
from .. import state

router = APIRouter()

@router.get("/sessions/{session_id}/traces")
async def list_traces(session_id: str):
    return state.traces.get(session_id, [])

@router.get("/sessions/{session_id}/traces/{trace_id}")
async def get_trace(session_id: str, trace_id: str):
    for t in state.traces.get(session_id, []):
        if t["id"] == trace_id:
            return t
    return {"error": "not found"}
