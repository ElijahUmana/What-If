"""What-If domain models — every table/shape from the architecture."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

import ulid


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ulid() -> str:
    return ulid.new().str


# ── Ingest layer ─────────────────────────────────────────────────────────────


class Session(BaseModel):
    id: str = Field(default_factory=lambda: f"ses_{ulid.new().str}")
    created_at: datetime = Field(default_factory=_now)
    owner_user_id: str
    source_url: str
    source_kind: str
    ingest_started_at: Optional[datetime] = None
    ingest_status: str = "pending"
    last_chunk_id: Optional[str] = None
    match_meta: dict = Field(default_factory=dict)
    visibility: str = "private"


class Chunk(BaseModel):
    id: str = Field(default_factory=lambda: f"chk_{ulid.new().str}")
    session_id: str
    sequence: int
    start_pts_ms: int
    end_pts_ms: int
    duration_ms: int
    storage_uri: str
    storage_bytes: int
    created_at: datetime = Field(default_factory=_now)
    codec: str = "h264"
    resolution: str = "1280x720"
    content_sha256: str = ""


class Frame(BaseModel):
    id: str = Field(default_factory=lambda: f"frm_{ulid.new().str}")
    session_id: str
    chunk_id: str
    pts_ms: int
    sampled_at_ms: int
    storage_uri: str
    width: int
    height: int
    sha256: str = ""


# ── Perception layer ─────────────────────────────────────────────────────────


class Caption(BaseModel):
    id: str = Field(default_factory=lambda: f"cap_{ulid.new().str}")
    session_id: str
    frame_id: str
    pts_ms: int
    text: str
    entities: dict = Field(default_factory=dict)
    model_id: str = ""
    latency_ms: int = 0
    trace_id: str = ""


class Summary(BaseModel):
    id: str = Field(default_factory=lambda: f"sum_{ulid.new().str}")
    session_id: str
    start_pts_ms: int
    end_pts_ms: int
    frame_ids: list[str] = Field(default_factory=list)
    caption_ids: list[str] = Field(default_factory=list)
    narrative: str = ""
    structured: dict = Field(default_factory=dict)
    model_id: str = ""
    trace_id: str = ""


class MatchEvent(BaseModel):
    id: str = Field(default_factory=lambda: f"evt_{ulid.new().str}")
    session_id: str
    type: str
    start_pts_ms: int
    end_pts_ms: int
    anchor_frame_id: str = ""
    actors: list[dict] = Field(default_factory=list)
    description: str = ""
    confidence: float = 0.0
    summary_id: str = ""
    trace_id: str = ""


class MatchState(BaseModel):
    id: str = Field(default_factory=lambda: f"mst_{ulid.new().str}")
    session_id: str
    as_of_pts_ms: int
    score: dict = Field(default_factory=dict)
    period: str = ""
    period_clock_ms: int = 0
    home: dict = Field(default_factory=dict)
    away: dict = Field(default_factory=dict)
    momentum: dict = Field(default_factory=dict)
    trace_id: str = ""


# ── Query & generation layer ─────────────────────────────────────────────────


class Query(BaseModel):
    id: str = Field(default_factory=lambda: f"qry_{ulid.new().str}")
    session_id: str
    user_id: str
    text: str
    parsed: Optional[dict] = None
    status: str = "pending"
    resolved_anchor_pts_ms: Optional[int] = None
    resolved_window_start_ms: Optional[int] = None
    resolved_window_end_ms: Optional[int] = None
    parent_clip_id: Optional[str] = None
    created_at: datetime = Field(default_factory=_now)
    trace_id: str = ""


class Prompt(BaseModel):
    id: str = Field(default_factory=lambda: f"pmt_{ulid.new().str}")
    query_id: str
    kind: str
    body: dict = Field(default_factory=dict)
    model_id: str = ""
    created_at: datetime = Field(default_factory=_now)


class Generation(BaseModel):
    id: str = Field(default_factory=lambda: f"gen_{ulid.new().str}")
    prompt_id: str
    status: str = "pending"
    started_at: datetime = Field(default_factory=_now)
    finished_at: Optional[datetime] = None
    latency_ms: Optional[int] = None
    storage_uri: Optional[str] = None
    metadata: Optional[dict] = None
    validator_verdict: Optional[str] = None
    validator_reasons: Optional[list[dict]] = None


class Clip(BaseModel):
    id: str = Field(default_factory=lambda: f"clp_{ulid.new().str}")
    query_id: str
    generation_id: str
    storage_uri: str
    duration_ms: int
    labels: dict = Field(default_factory=dict)


# ── Sharing & observability ──────────────────────────────────────────────────


class Artifact(BaseModel):
    id: str = Field(default_factory=lambda: f"art_{ulid.new().str}")
    session_id: str
    kind: str
    storage_uri: str
    short_code: str = ""
    created_at: datetime = Field(default_factory=_now)
    revoked_at: Optional[datetime] = None


class TraceEvent(BaseModel):
    id: str = Field(default_factory=lambda: f"tr_{ulid.new().str}")
    session_id: str
    agent: str
    kind: str
    parent_id: Optional[str] = None
    started_at: datetime = Field(default_factory=_now)
    ended_at: Optional[datetime] = None
    input_ref: Optional[dict] = None
    output_ref: Optional[dict] = None
    model_id: Optional[str] = None
    latency_ms: Optional[int] = None
    status: str = "ok"
    payload: Optional[dict] = None


# ── Public API ───────────────────────────────────────────────────────────────

__all__ = [
    "Session",
    "Chunk",
    "Frame",
    "Caption",
    "Summary",
    "MatchEvent",
    "MatchState",
    "Query",
    "Prompt",
    "Generation",
    "Clip",
    "Artifact",
    "TraceEvent",
]
