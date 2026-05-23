"""WebSocket protocol types for the What-If real-time layer."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ── Server → Client ─────────────────────────────────────────────────────────


class ServerEventType(str, Enum):
    MATCH_STATE_UPDATE = "match_state.update"
    COMMENTARY_LINE = "commentary.line"
    EVENT_CREATED = "event.created"
    QUERY_PROGRESS = "query.progress"
    CLIP_READY = "clip.ready"
    INGEST_STATUS = "ingest.status"


class ServerEvent(BaseModel):
    type: ServerEventType
    payload: dict[str, Any] = Field(default_factory=dict)


# ── Client → Server ─────────────────────────────────────────────────────────


class ClientEventType(str, Enum):
    QUERY_SUBMIT = "query.submit"
    CLIP_BRANCH = "clip.branch"
    CLIP_PIN = "clip.pin"
    DIRECTORS_CUT_REQUEST = "directors_cut.request"


class ClientEvent(BaseModel):
    type: ClientEventType
    payload: dict[str, Any] = Field(default_factory=dict)
