import os

from fastapi import APIRouter
from fastapi.responses import FileResponse

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


@router.get("/sessions/{session_id}/prompts")
async def list_prompts(session_id: str):
    return state.prompts.get(session_id, [])


@router.get("/clips/{clip_path:path}")
async def serve_clip(clip_path: str):
    full_path = f"/tmp/whatif_storage/sessions/{clip_path}"
    if os.path.exists(full_path):
        return FileResponse(full_path, media_type="video/mp4")
    return {"error": "not found"}
