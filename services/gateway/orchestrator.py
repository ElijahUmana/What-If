"""Orchestrator -- wires ingest, perception, and what-if pipelines together."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
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
from agents.videogen.agent import generate_clip
from agents.validator.agent import validate_clip
from agents.commentary.agent import generate_commentary
from agents.setup.agent import identify_match
from agents._lib.storage import store
from services.gateway import state

logger = logging.getLogger(__name__)

# Active ingest agents per session
_ingest_agents: dict[str, IngestAgent] = {}
_perception_tasks: dict[str, asyncio.Task] = {}

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
                    logger.warning("Caption error for %s: %s", session_id, e)
            last_caption_pts = current_pts

        # --- Summarise every 30 seconds of wall-clock time ---
        if time.time() - last_summary_time < 45:
            continue
        last_summary_time = time.time()

        try:
            window_frames = ring.last_n_seconds(30)
            if len(window_frames) < 5:
                continue

            match_meta = state.sessions[session_id].get("match_meta", {})

            # Build a mini video from recent .ts chunks
            chunks_dir = agent.session_dir / "chunks"
            if not chunks_dir.is_dir():
                continue

            chunk_files = sorted(chunks_dir.glob("*.ts"))
            # ~15 chunks at 2s each = 30s
            recent_chunks = chunk_files[-15:]
            if not recent_chunks:
                continue

            concat_path = f"/tmp/whatif_window_{session_id}.mp4"
            concat_input = "|".join(str(c) for c in recent_chunks)
            proc = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    f"concat:{concat_input}",
                    "-t",
                    "30",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "ultrafast",
                    "-c:a",
                    "aac",
                    concat_path,
                ],
                capture_output=True,
                timeout=15,
            )
            if proc.returncode != 0 or not os.path.exists(concat_path):
                logger.warning(
                    "ffmpeg concat failed for %s: %s",
                    session_id,
                    proc.stderr.decode(errors="replace")[:200],
                )
                continue

            with open(concat_path, "rb") as f:
                video_bytes = f.read()

            summary = await summarise_window(
                video_bytes, match_meta, session_id=session_id
            )
            summary_entry = {
                "narrative": summary.get("narrative", ""),
                "structured": summary.get("structured", {}),
                "events": summary.get("events", []),
                "timestamp": time.time(),
            }
            state.summaries.setdefault(session_id, []).append(summary_entry)
            await state.broadcast(
                session_id, "summary.created", summary_entry
            )

            # Extract and broadcast events
            for ev in summary.get("events", []):
                event_entry = {
                    "type": ev.get("type", "unknown"),
                    "description": ev.get("description", ""),
                    "confidence": ev.get("confidence", 0),
                    "pts_ms": current_pts,
                    "timestamp": time.time(),
                }
                state.events.setdefault(session_id, []).append(event_entry)
                await state.broadcast(
                    session_id, "event.created", event_entry
                )

                # Update match_state on goal events
                if ev.get("type") == "goal" and ev.get("confidence", 0) > 0.7:
                    ms = state.match_states.get(session_id, {})
                    team = ev.get("team", "").lower()
                    if "home" in team:
                        ms.setdefault("score", {"home": 0, "away": 0})[
                            "home"
                        ] += 1
                    elif "away" in team:
                        ms.setdefault("score", {"home": 0, "away": 0})[
                            "away"
                        ] += 1
                    state.match_states[session_id] = ms
                    await state.broadcast(
                        session_id, "match_state.update", ms
                    )

            # Commentary
            try:
                events_list = state.events.get(session_id, [])
                summaries_list = state.summaries.get(session_id, [])
                ms = state.match_states.get(session_id, {})
                line = await generate_commentary(
                    events_list[-5:],
                    summaries_list[-3:],
                    ms,
                    session_id=session_id,
                )
                commentary_entry = {"text": line, "timestamp": time.time()}
                state.commentary.setdefault(session_id, []).append(
                    commentary_entry
                )
                await state.broadcast(
                    session_id, "commentary.line", commentary_entry
                )
            except Exception as e:
                logger.warning(
                    "Commentary error for %s: %s", session_id, e
                )

            # Clean up temp file
            try:
                os.remove(concat_path)
            except OSError:
                pass

        except Exception as e:
            logger.error("Summary loop error for %s: %s", session_id, e)


# ---------------------------------------------------------------------------
# What-if pipeline
# ---------------------------------------------------------------------------


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
        ref_frames_bytes: list[bytes] = []
        if agent:
            anchor = resolved.get("anchor_pts_ms", 0)
            window_start = resolved.get(
                "window_start_ms", max(0, anchor - 15000)
            )
            window_end = resolved.get("window_end_ms", anchor + 10000)
            window = agent.frame_ring.window(window_start, window_end)
            if window:
                step = max(1, len(window) // 4)
                ref_frames_bytes = [
                    window[i]["jpeg_bytes"]
                    for i in range(0, len(window), step)
                ][:4]

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
            anchor_event=anchor_event,
            window_frames=ref_frames_bytes,
            captions=window_captions,
            summary=summaries_list[-1] if summaries_list else {},
            match_state=ms,
            session_id=session_id,
        )

        # ---- Stage 3: Generate ----
        await state.broadcast(
            session_id,
            "query.progress",
            {"query_id": query_id, "stage": "generating"},
        )

        veo_prompt = build_veo_prompt(brief)
        clip_bytes, gen_meta = await generate_clip(
            veo_prompt, ref_frames_bytes, session_id=session_id
        )

        # ---- Stage 4: Validate ----
        await state.broadcast(
            session_id,
            "query.progress",
            {"query_id": query_id, "stage": "validating"},
        )

        verdict = await validate_clip(
            clip_bytes=clip_bytes,
            user_prompt=text,
            real_event=anchor_event,
            counterfactual=brief.get("counterfactual_delta", {}),
            session_id=session_id,
        )

        # One retry on "regenerate" verdict
        if verdict.get("verdict") == "regenerate":
            await state.broadcast(
                session_id,
                "query.progress",
                {"query_id": query_id, "stage": "regenerating"},
            )
            feedback_text = "; ".join(
                verdict.get("verdict_reasons", ["improve quality"])
            )
            retry_prompt = veo_prompt + "\nFEEDBACK: " + feedback_text
            clip_bytes, gen_meta = await generate_clip(
                retry_prompt, ref_frames_bytes, session_id=session_id
            )
            verdict = await validate_clip(
                clip_bytes=clip_bytes,
                user_prompt=text,
                real_event=anchor_event,
                counterfactual=brief.get("counterfactual_delta", {}),
                session_id=session_id,
            )

        # ---- Stage 5: Store and broadcast ----
        clip_path = store(session_id, "clips", f"{query_id}.mp4", clip_bytes)

        clip_entry = {
            "id": f"cl_{query_id}",
            "query_id": query_id,
            "storage_uri": clip_path,
            "duration_ms": int(gen_meta.get("latency_s", 8) * 1000),
            "prompt": text,
            "verdict": verdict.get("verdict", "ok"),
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
