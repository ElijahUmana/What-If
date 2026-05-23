from fastapi import APIRouter
from .. import state

router = APIRouter()

@router.get("/sessions/{session_id}/clips")
async def list_clips(session_id: str):
    return state.clips.get(session_id, [])

@router.get("/sessions/{session_id}/events")
async def list_events(session_id: str):
    return state.events.get(session_id, [])

@router.get("/sessions/{session_id}/timeline")
async def get_timeline(session_id: str):
    return {
        "events": state.events.get(session_id, []),
        "summaries": state.summaries.get(session_id, []),
        "match_state": state.match_states.get(session_id, {}),
    }
