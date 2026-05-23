"""Orchestrator -- wires ingest, perception, and what-if pipelines together."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parents[2] / ".env")

from agents.ingest.agent import IngestAgent
from agents.captioner.agent import caption_frame
from agents.summariser.agent import summarise_window
from agents.retrieval.agent import resolve_query
from agents.director.agent import compose_veo_brief
from agents.director.prompt_builder import build_veo_prompt
from agents.director.schema import ReferenceFrame, VeoBrief
from agents.videogen.agent import generate_clip
from agents.validator.agent import validate_clip, validate_continuity
from agents.commentary.agent import generate_commentary
from agents.setup.agent import identify_match
from agents._lib.storage import store
from services.gateway import state

logger = logging.getLogger(__name__)

# Active ingest agents per session
_ingest_agents: dict[str, IngestAgent] = {}
_perception_tasks: dict[str, asyncio.Task] = {}
_debug_errors: list[str] = []

WORK_DIR = os.environ.get("WORK_DIR", "/tmp/whatif")


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------


async def start_session(session_id: str, source_url: str) -> None:
    """Called when POST /api/sessions creates a new session."""
    work_dir = f"{WORK_DIR}/sessions/{session_id}"
    os.makedirs(work_dir, exist_ok=True)

    # Start ingest
    agent = IngestAgent(
        session_id=session_id, youtube_url=source_url, work_dir=WORK_DIR
    )
    _ingest_agents[session_id] = agent

    state.sessions[session_id]["ingest_status"] = "starting"
    await state.broadcast(session_id, "ingest.status", {"status": "starting"})

    _perception_tasks[session_id] = asyncio.create_task(
        _run_ingest(session_id, agent)
    )


async def stop_session(session_id: str) -> None:
    """Gracefully tear down ingest + perception for a session."""
    agent = _ingest_agents.pop(session_id, None)
    if agent is not None:
        agent.stop()

    task = _perception_tasks.pop(session_id, None)
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# Ingest orchestration
# ---------------------------------------------------------------------------


async def _run_ingest(session_id: str, agent: IngestAgent) -> None:
    """Background: run ingest, identify match, then start perception loop."""
    try:
        # Start ingest capture in its own task
        ingest_task = asyncio.create_task(_ingest_loop(session_id, agent))

        # Wait for first frames to land in the ring buffer
        waited = 0
        while len(agent.frame_ring) < 5 and waited < 30:
            await asyncio.sleep(1)
            waited += 1

        # ----- Setup: identify match from title + opening frames -----
        ring = agent.frame_ring
        first_frames = [f["jpeg_bytes"] for f in ring.last_n_seconds(10)][:5]
        if first_frames:
            title = state.sessions[session_id].get("source_url", "")
            try:
                match_meta = await identify_match(
                    title, first_frames, session_id=session_id
                )
                state.sessions[session_id]["match_meta"] = match_meta
                state.match_states[session_id] = {
                    "score": {"home": 0, "away": 0},
                    "period": "1st_half",
                    "home_team": match_meta.get("home_team", "Home"),
                    "away_team": match_meta.get("away_team", "Away"),
                    "home_kit": match_meta.get(
                        "home_kit_color_primary", "white"
                    ),
                    "away_kit": match_meta.get(
                        "away_kit_color_primary", "blue"
                    ),
                }
                await state.broadcast(
                    session_id,
                    "match_state.update",
                    state.match_states[session_id],
                )
            except Exception as e:
                logger.error("Setup agent error for %s: %s", session_id, e)

        state.sessions[session_id]["ingest_status"] = "live"
        await state.broadcast(
            session_id, "ingest.status", {"status": "live"}
        )

        # Start perception loop (blocks until agent stops)
        await _perception_loop(session_id, agent)

    except asyncio.CancelledError:
        logger.info("Ingest cancelled for %s", session_id)
        raise
    except Exception as e:
        logger.error("Ingest error for %s: %s", session_id, e)
        state.sessions[session_id]["ingest_status"] = "errored"
        await state.broadcast(
            session_id,
            "ingest.status",
            {"status": "errored", "error": str(e)},
        )


async def _ingest_loop(session_id: str, agent: IngestAgent) -> None:
    """Run the IngestAgent (captures video until stopped)."""
    try:
        await agent.run()
    except Exception as e:
        logger.error("Ingest agent died for %s: %s", session_id, e)


# ---------------------------------------------------------------------------
# Perception loop
# ---------------------------------------------------------------------------


async def _perception_loop(session_id: str, agent: IngestAgent) -> None:
    """Continuously caption frames and summarise 30-second windows."""
    ring = agent.frame_ring
    last_caption_pts = 0
    last_summary_time = time.time()
    frame_counter = 0

    while not agent._stop_event.is_set():
        await asyncio.sleep(0.5)

        latest = ring.latest()
        if latest is None:
            continue

        current_pts = latest["pts_ms"]

        # --- Caption new frames (every 3rd to stay under rate limits) ---
        if current_pts > last_caption_pts:
            frame_counter += 1
            if frame_counter % 10 == 0:
                try:
                    caption = await caption_frame(
                        latest["jpeg_bytes"], session_id
                    )
                    caption_entry = {
                        "pts_ms": current_pts,
                        "text": caption.get("caption", ""),
                        "entities": caption,
                        "timestamp": time.time(),
                    }
                    state.captions.setdefault(session_id, []).append(
                        caption_entry
                    )
                    await state.broadcast(
                        session_id, "caption.created", caption_entry
                    )
                except Exception as e:
                    import traceback
                    err = f"Caption error: {type(e).__name__}: {e}\n{traceback.format_exc()}"
                    logger.warning(err)
                    _debug_errors.append(err)
            last_caption_pts = current_pts

        # --- Summarise every 45 seconds (fire-and-forget, doesn't block captions) ---
        if time.time() - last_summary_time >= 45:
            last_summary_time = time.time()
            asyncio.create_task(_run_summary(session_id, agent, current_pts))


async def _run_summary(session_id: str, agent: IngestAgent, current_pts: int) -> None:
    """Run one summary cycle as a background task (doesn't block captions)."""
    try:
        ring = agent.frame_ring
        window_frames = ring.last_n_seconds(30)
        if len(window_frames) < 5:
            return

        match_meta = state.sessions[session_id].get("match_meta", {})
        chunks_dir = agent.session_dir / "chunks"
        if not chunks_dir.is_dir():
            return

        chunk_files = sorted(chunks_dir.glob("*.ts"))
        recent_chunks = chunk_files[-15:]
        if not recent_chunks:
            return

        concat_path = f"/tmp/whatif_window_{session_id}.mp4"
        concat_input = "|".join(str(c) for c in recent_chunks)
        proc = await asyncio.to_thread(
            lambda: subprocess.run(
                ["ffmpeg", "-y", "-i", f"concat:{concat_input}",
                 "-t", "30", "-c:v", "libx264", "-preset", "ultrafast",
                 "-c:a", "aac", concat_path],
                capture_output=True, timeout=30,
            )
        )
        if proc.returncode != 0 or not os.path.exists(concat_path):
            _debug_errors.append(f"ffmpeg concat failed: {proc.stderr.decode(errors='replace')[:300]}")
            return

        with open(concat_path, "rb") as f:
            video_bytes = f.read()

        summary = await summarise_window(video_bytes, match_meta, session_id=session_id)
        summary_entry = {
            "narrative": summary.get("narrative", ""),
            "structured": summary.get("structured", {}),
            "events": summary.get("events", []),
            "timestamp": time.time(),
        }
        state.summaries.setdefault(session_id, []).append(summary_entry)
        await state.broadcast(session_id, "summary.created", summary_entry)

        for ev in summary.get("events", []):
            event_entry = {
                "type": ev.get("type", "unknown"),
                "description": ev.get("description", ""),
                "confidence": ev.get("confidence", 0),
                "pts_ms": current_pts,
                "timestamp": time.time(),
            }
            state.events.setdefault(session_id, []).append(event_entry)
            await state.broadcast(session_id, "event.created", event_entry)

        try:
            events_list = state.events.get(session_id, [])
            summaries_list = state.summaries.get(session_id, [])
            ms = state.match_states.get(session_id, {})
            line = await generate_commentary(events_list[-5:], summaries_list[-3:], ms, session_id=session_id)
            commentary_entry = {"text": line, "timestamp": time.time()}
            state.commentary.setdefault(session_id, []).append(commentary_entry)
            await state.broadcast(session_id, "commentary.line", commentary_entry)
        except Exception as e:
            _debug_errors.append(f"Commentary error: {e}")

        try:
            os.remove(concat_path)
        except OSError:
            pass

    except Exception as e:
        import traceback
        _debug_errors.append(f"Summary error: {type(e).__name__}: {e}\n{traceback.format_exc()}")


# ---------------------------------------------------------------------------
# What-if pipeline
# ---------------------------------------------------------------------------


def _manual_resolution(query_text: str, anchor_pts_ms: int) -> dict:
    return {
        "anchor_id": f"manual_{anchor_pts_ms}",
        "anchor_pts_ms": anchor_pts_ms,
        "window_start_ms": max(0, anchor_pts_ms - 15000),
        "window_end_ms": anchor_pts_ms + 10000,
        "change_type": "explicit_anchor",
        "entities_referenced": [],
        "intent_clarity": "anchored",
        "reasoning": "User supplied anchor_pts_ms; retrieval was bypassed.",
        "user_prompt": query_text,
    }


def _reference_role_hint(pts_ms: int, anchor_pts_ms: int, index: int) -> str:
    if index == 0:
        return "stadium_lighting_ref"
    if abs(pts_ms - anchor_pts_ms) <= 1000:
        return "divergence_frame_camera_lock"
    if pts_ms < anchor_pts_ms:
        return "pre_change_frame"
    return "continuation_context"


def _build_reference_frames(
    window: list[dict], anchor_pts_ms: int, max_frames: int = 8
) -> list[ReferenceFrame]:
    if not window:
        return []

    def closest(target_pts_ms: int) -> dict:
        return min(
            window,
            key=lambda frame: abs(frame.get("pts_ms", 0) - target_pts_ms),
        )

    targets = [
        window[0],
        closest(max(0, anchor_pts_ms - 1000)),
        closest(anchor_pts_ms),
        closest(anchor_pts_ms + 2000),
        window[-1],
    ]

    step = max(1, len(window) // max(1, max_frames))
    targets.extend(window[i] for i in range(0, len(window), step))

    unique: list[dict] = []
    seen_pts: set[int] = set()
    for frame in targets:
        pts_ms = int(frame.get("pts_ms", 0))
        if pts_ms in seen_pts:
            continue
        seen_pts.add(pts_ms)
        unique.append(frame)
        if len(unique) >= max_frames:
            break

    return [
        ReferenceFrame(
            id=f"rf_{index:03d}_{int(frame.get('pts_ms', 0))}",
            pts_ms=int(frame.get("pts_ms", 0)),
            role_hint=_reference_role_hint(
                int(frame.get("pts_ms", 0)), anchor_pts_ms, index
            ),
            jpeg_bytes=frame["jpeg_bytes"],
        )
        for index, frame in enumerate(unique)
    ]


def _selected_reference_frames(
    frames: list[ReferenceFrame], brief: VeoBrief, max_frames: int = 3
) -> tuple[list[bytes], list[dict]]:
    by_id = {frame.id: frame for frame in frames}
    selected: list[ReferenceFrame] = []
    selected_roles: dict[str, str] = {}
    seen: set[str] = set()

    for selection in brief.selected_reference_frames:
        frame = by_id.get(selection.id)
        if frame is None or frame.id in seen:
            continue
        selected.append(frame)
        selected_roles[frame.id] = selection.role
        seen.add(frame.id)
        if len(selected) >= max_frames:
            break

    for frame in frames:
        if len(selected) >= max_frames:
            break
        if frame.id in seen:
            continue
        selected.append(frame)
        selected_roles[frame.id] = "fallback_reference"
        seen.add(frame.id)

    metadata = [
        {**frame.metadata(), "selected_role": selected_roles.get(frame.id, "")}
        for frame in selected
    ]
    return [frame.jpeg_bytes for frame in selected], metadata


def _store_prompt_artifact(
    session_id: str,
    query_id: str,
    attempt: int,
    user_prompt: str,
    resolved: dict,
    brief: VeoBrief,
    veo_prompt: str,
    reference_frames: list[ReferenceFrame],
    selected_reference_frame_metadata: list[dict],
) -> str:
    payload = {
        "query_id": query_id,
        "attempt": attempt,
        "user_prompt": user_prompt,
        "resolved": resolved,
        "brief": brief.model_dump(),
        "veo_prompt": veo_prompt,
        "reference_frames": [frame.metadata() for frame in reference_frames],
        "selected_reference_frames": selected_reference_frame_metadata,
    }
    filename = f"{query_id}_attempt_{attempt}.json"
    uri = store(
        session_id,
        "prompts",
        filename,
        json.dumps(payload, indent=2).encode("utf-8"),
    )
    state.prompts.setdefault(session_id, []).append(
        {
            "query_id": query_id,
            "attempt": attempt,
            "storage_uri": uri,
            "selected_reference_frames": selected_reference_frame_metadata,
            "prompt_preview": veo_prompt[:300],
            "timestamp": time.time(),
        }
    )
    return uri


def _sample_clip_frames(clip_bytes: bytes, max_frames: int = 3) -> list[bytes]:
    timestamps = [0.5, 3.5, 6.5][:max_frames]
    frames: list[bytes] = []
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        clip_path = temp_path / "clip.mp4"
        clip_path.write_bytes(clip_bytes)

        for index, timestamp in enumerate(timestamps):
            out_path = temp_path / f"frame_{index}.jpg"
            proc = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-ss",
                    str(timestamp),
                    "-i",
                    str(clip_path),
                    "-frames:v",
                    "1",
                    str(out_path),
                ],
                capture_output=True,
                timeout=20,
            )
            if proc.returncode == 0 and out_path.exists():
                frames.append(out_path.read_bytes())
            else:
                _debug_errors.append(
                    "ffmpeg validation frame sample failed: "
                    + proc.stderr.decode(errors="replace")[:300]
                )
    return frames


def _combine_validation_verdicts(
    fidelity: dict,
    continuity: dict | None,
    warnings: list[str],
) -> dict:
    severity = {"ok": 0, "regenerate": 1, "reject": 2}
    verdict = fidelity.get("verdict", "ok")
    reasons = list(fidelity.get("verdict_reasons", []))

    if continuity is not None:
        continuity_verdict = continuity.get("verdict", "ok")
        if severity.get(continuity_verdict, 0) > severity.get(verdict, 0):
            verdict = continuity_verdict
        reasons.extend(continuity.get("verdict_reasons", []))

    combined = {
        **fidelity,
        "verdict": verdict,
        "verdict_reasons": reasons,
        "fidelity": fidelity,
        "continuity": continuity,
    }
    if warnings:
        combined["validation_warnings"] = warnings
    return combined


async def _validate_clip_suite(
    clip_bytes: bytes,
    user_prompt: str,
    real_event: dict,
    brief: VeoBrief,
    reference_frame_bytes: list[bytes],
    session_id: str,
) -> dict:
    fidelity_task = asyncio.create_task(
        validate_clip(
            clip_bytes=clip_bytes,
            user_prompt=user_prompt,
            real_event=real_event,
            counterfactual=brief.counterfactual_delta.model_dump(),
            session_id=session_id,
        )
    )

    sample_frames = await asyncio.to_thread(_sample_clip_frames, clip_bytes)
    warnings: list[str] = []
    continuity_result: dict | None = None
    if sample_frames and reference_frame_bytes:
        continuity_result = await validate_continuity(
            reference_frames=reference_frame_bytes,
            clip_sample_frames=sample_frames,
            continuity_brief=brief.continuity.model_dump(),
            session_id=session_id,
        )
    else:
        warnings.append("continuity validation skipped: no sampled clip frames")

    fidelity_result = await fidelity_task
    return _combine_validation_verdicts(
        fidelity_result, continuity_result, warnings
    )


async def handle_whatif(
    session_id: str,
    query_id: str,
    text: str,
    anchor_pts_ms: int | None = None,
) -> None:
    """Run the full counterfactual pipeline for a what-if query."""
    try:
        # ---- Stage 1: Resolve ----
        await state.broadcast(
            session_id,
            "query.progress",
            {"query_id": query_id, "stage": "resolving"},
        )

        events_list = state.events.get(session_id, [])
        summaries_list = state.summaries.get(session_id, [])
        ms = state.match_states.get(session_id, {})

        # Determine live PTS
        agent = _ingest_agents.get(session_id)
        live_pts = 0
        if agent:
            latest = agent.frame_ring.latest()
            if latest:
                live_pts = latest["pts_ms"]

        if anchor_pts_ms is not None:
            resolved = _manual_resolution(text, anchor_pts_ms)
        else:
            resolved = await resolve_query(
                text,
                events_list,
                summaries_list,
                ms,
                live_now_pts_ms=live_pts,
                session_id=session_id,
            )

        # Update the query record
        for q in state.queries.get(session_id, []):
            if q["id"] == query_id:
                q["status"] = "resolved"
                q["resolved_anchor_pts_ms"] = resolved.get("anchor_pts_ms")
                break

        # ---- Stage 2: Direct ----
        await state.broadcast(
            session_id,
            "query.progress",
            {"query_id": query_id, "stage": "directing"},
        )

        # Gather reference frames from the ring buffer around the anchor
        reference_frames: list[ReferenceFrame] = []
        if agent:
            anchor = resolved.get("anchor_pts_ms", 0)
            window_start = resolved.get(
                "window_start_ms", max(0, anchor - 15000)
            )
            window_end = resolved.get("window_end_ms", anchor + 10000)
            window = agent.frame_ring.window(window_start, window_end)
            if window:
                reference_frames = _build_reference_frames(window, anchor)

        if not reference_frames:
            raise RuntimeError(
                "No reference frames available for Veo generation; refusing blind text-to-video fallback."
            )

        # Find the anchor event
        anchor_event: dict = {}
        anchor_pts = resolved.get("anchor_pts_ms", 0)
        for ev in events_list:
            if abs(ev.get("pts_ms", 0) - anchor_pts) < 5000:
                anchor_event = ev
                break

        # Window captions
        captions = state.captions.get(session_id, [])
        window_start = resolved.get("window_start_ms", 0)
        window_end = resolved.get("window_end_ms", 0)
        window_captions = [
            c
            for c in captions
            if window_start <= c.get("pts_ms", 0) <= window_end
        ]

        brief = await compose_veo_brief(
            query={"text": text, **resolved},
            anchor_event=(
                anchor_event
                if anchor_event
                else {"type": "unknown", "description": text}
            ),
            window_frames=reference_frames,
            captions=window_captions if window_captions else [{"text": text}],
            summary=summaries_list[-1] if summaries_list else {"narrative": text},
            match_state=ms if ms else {"home_team": "Home", "away_team": "Away"},
            session_id=session_id,
        )

        # ---- Stage 3: Generate ----
        await state.broadcast(
            session_id,
            "query.progress",
            {"query_id": query_id, "stage": "generating"},
        )

        veo_prompt = build_veo_prompt(brief)
        (
            generation_reference_bytes,
            selected_reference_frame_metadata,
        ) = _selected_reference_frames(reference_frames, brief)
        prompt_artifact_uri = _store_prompt_artifact(
            session_id=session_id,
            query_id=query_id,
            attempt=1,
            user_prompt=text,
            resolved=resolved,
            brief=brief,
            veo_prompt=veo_prompt,
            reference_frames=reference_frames,
            selected_reference_frame_metadata=selected_reference_frame_metadata,
        )

        clip_bytes, gen_meta = await generate_clip(
            veo_prompt,
            generation_reference_bytes,
            duration_s=brief.model_params.duration_s,
            resolution=brief.model_params.resolution,
            seed=brief.model_params.seed,
            session_id=session_id,
        )

        # ---- Stage 4: Validate ----
        await state.broadcast(
            session_id,
            "query.progress",
            {"query_id": query_id, "stage": "validating"},
        )

        verdict = await _validate_clip_suite(
            clip_bytes=clip_bytes,
            user_prompt=text,
            real_event=anchor_event,
            brief=brief,
            reference_frame_bytes=generation_reference_bytes,
            session_id=session_id,
        )

        # One retry on "regenerate" verdict
        if verdict.get("verdict") == "regenerate":
            await state.broadcast(
                session_id,
                "query.progress",
                {"query_id": query_id, "stage": "regenerating"},
            )
            brief = await compose_veo_brief(
                query={"text": text, **resolved},
                anchor_event=(
                    anchor_event
                    if anchor_event
                    else {"type": "unknown", "description": text}
                ),
                window_frames=reference_frames,
                captions=window_captions if window_captions else [{"text": text}],
                summary=summaries_list[-1] if summaries_list else {"narrative": text},
                match_state=ms if ms else {"home_team": "Home", "away_team": "Away"},
                validator_feedback=verdict,
                session_id=session_id,
            )
            veo_prompt = build_veo_prompt(brief)
            (
                generation_reference_bytes,
                selected_reference_frame_metadata,
            ) = _selected_reference_frames(reference_frames, brief)
            prompt_artifact_uri = _store_prompt_artifact(
                session_id=session_id,
                query_id=query_id,
                attempt=2,
                user_prompt=text,
                resolved=resolved,
                brief=brief,
                veo_prompt=veo_prompt,
                reference_frames=reference_frames,
                selected_reference_frame_metadata=selected_reference_frame_metadata,
            )
            clip_bytes, gen_meta = await generate_clip(
                veo_prompt,
                generation_reference_bytes,
                duration_s=brief.model_params.duration_s,
                resolution=brief.model_params.resolution,
                seed=brief.model_params.seed,
                session_id=session_id,
            )
            verdict = await _validate_clip_suite(
                clip_bytes=clip_bytes,
                user_prompt=text,
                real_event=anchor_event,
                brief=brief,
                reference_frame_bytes=generation_reference_bytes,
                session_id=session_id,
            )

        # ---- Stage 5: Store and broadcast ----
        clip_path = store(session_id, "clips", f"{query_id}.mp4", clip_bytes)

        clip_entry = {
            "id": f"cl_{query_id}",
            "query_id": query_id,
            "storage_uri": clip_path,
            "duration_ms": int(
                gen_meta.get("duration_s", brief.model_params.duration_s) * 1000
            ),
            "prompt": text,
            "prompt_text": text,
            "prompt_artifact_uri": prompt_artifact_uri,
            "selected_reference_frames": selected_reference_frame_metadata,
            "verdict": verdict.get("verdict", "ok"),
            "validation": verdict,
            "status": "ready",
        }
        state.clips.setdefault(session_id, []).append(clip_entry)

        for q in state.queries.get(session_id, []):
            if q["id"] == query_id:
                q["status"] = "ready"
                break

        await state.broadcast(
            session_id,
            "query.progress",
            {"query_id": query_id, "stage": "ready"},
        )
        await state.broadcast(session_id, "clip.ready", clip_entry)

    except Exception as e:
        logger.error(
            "What-if pipeline error for %s/%s: %s", session_id, query_id, e,
            exc_info=True,
        )
        for q in state.queries.get(session_id, []):
            if q["id"] == query_id:
                q["status"] = "failed"
                q["error"] = str(e)
                break
        await state.broadcast(
            session_id,
            "query.progress",
            {"query_id": query_id, "stage": "failed", "error": str(e)},
        )
