import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routes import sessions, queries, artifacts, traces
from .ws import router as ws_router

app = FastAPI(title="What If Gateway")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(sessions.router, prefix="/api")
app.include_router(queries.router, prefix="/api")
app.include_router(artifacts.router, prefix="/api")
app.include_router(traces.router, prefix="/api")
app.include_router(ws_router)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/debug/test-caption")
async def test_caption():
    """Test captioner from within the running server process."""
    from . import orchestrator
    errors = []
    results = []
    for sid, agent in orchestrator._ingest_agents.items():
        ring = agent.frame_ring
        latest = ring.latest()
        if latest is None:
            errors.append(f"{sid}: ring empty")
            continue
        try:
            from agents.captioner.agent import caption_frame
            result = await caption_frame(latest["jpeg_bytes"], sid)
            results.append({"session": sid, "caption": result})
        except Exception as e:
            import traceback
            errors.append(f"{sid}: {type(e).__name__}: {e}\n{traceback.format_exc()}")
    return {"results": results, "errors": errors}

@app.get("/debug/errors")
def debug_errors():
    from . import orchestrator
    return {"errors": orchestrator._debug_errors[-20:] if hasattr(orchestrator, '_debug_errors') else []}

@app.get("/debug")
def debug():
    from . import orchestrator, state
    result = {}
    for sid, agent in orchestrator._ingest_agents.items():
        ring = agent.frame_ring
        result[sid] = {
            "ring_size": len(ring),
            "ring_latest_pts": ring.latest()["pts_ms"] if ring.latest() else None,
            "stop_event_set": agent._stop_event.is_set(),
            "ffmpeg_alive": agent._capture.is_alive() if agent._capture else False,
            "frame_counter": agent._frame_counter,
            "session_dir": str(agent.session_dir),
        }
    result["sessions_in_state"] = list(state.sessions.keys())
    result["perception_tasks"] = {k: not v.done() for k, v in orchestrator._perception_tasks.items()}
    for sid in state.sessions:
        result[f"captions_{sid}"] = len(state.captions.get(sid, []))
        result[f"summaries_{sid}"] = len(state.summaries.get(sid, []))
        result[f"events_{sid}"] = len(state.events.get(sid, []))
        result[f"commentary_{sid}"] = len(state.commentary.get(sid, []))
    return result
