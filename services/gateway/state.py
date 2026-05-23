from dataclasses import dataclass, field
from datetime import datetime
import asyncio

sessions: dict[str, dict] = {}
chunks: dict[str, list[dict]] = {}     # session_id -> list of chunk dicts
frames: dict[str, list[dict]] = {}     # session_id -> list of frame dicts
captions: dict[str, list[dict]] = {}
summaries: dict[str, list[dict]] = {}
events: dict[str, list[dict]] = {}
match_states: dict[str, dict] = {}
queries: dict[str, list[dict]] = {}
prompts: dict[str, list[dict]] = {}
clips: dict[str, list[dict]] = {}
traces: dict[str, list[dict]] = {}
commentary: dict[str, list[dict]] = {}

# Per-session WebSocket subscribers
ws_subscribers: dict[str, list[asyncio.Queue]] = {}

async def broadcast(session_id: str, event_type: str, payload: dict):
    if session_id in ws_subscribers:
        for q in ws_subscribers[session_id]:
            await q.put({"type": event_type, "payload": payload})
