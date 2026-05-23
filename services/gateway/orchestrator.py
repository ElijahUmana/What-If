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

        # If the user provided an explicit anchor, override retrieval's answer
        if anchor_pts_ms is not None and anchor_pts_ms > 0:
            resolved["anchor_pts_ms"] = anchor_pts_ms
            # Recalculate window around user-provided anchor
            resolved["window_start_ms"] = max(0, anchor_pts_ms - 15000)
            resolved["window_end_ms"] = anchor_pts_ms + 10000

        # Gather reference frames from the ring buffer around the anchor.
        # Strategy: pick 3 frames spread across the window --
        #   1. First frame (scene setup / pre-event context)
        #   2. Frame closest to anchor (the moment itself)
        #   3. Last frame (aftermath / post-event state)
        ref_frames_bytes: list[bytes] = []
        if agent:
            anchor = resolved.get("anchor_pts_ms", 0)
            window_start = resolved.get(
                "window_start_ms", max(0, anchor - 15000)
            )
            window_end = resolved.get("window_end_ms", anchor + 10000)
            window = agent.frame_ring.window(window_start, window_end)
            if window:
                # First frame: scene setup
                selected = [window[0]]

                # Closest to anchor: the key moment
                if len(window) > 2:
                    closest_idx = min(
                        range(len(window)),
                        key=lambda i: abs(window[i].get("pts_ms", 0) - anchor),
                    )
                    # Avoid duplicating if closest is also first or last
                    if closest_idx != 0 and closest_idx != len(window) - 1:
                        selected.append(window[closest_idx])
                    elif len(window) > 2:
                        selected.append(window[len(window) // 2])

                # Last frame: aftermath
                if len(window) > 1:
                    selected.append(window[-1])

                ref_frames_bytes = [f["jpeg_bytes"] for f in selected][:3]

        # If no reference frames from the anchor window, try ANY recent
        # frames from the ring buffer. Generating without visual context
        # violates the continuity premise, so fail if still empty.
        if not ref_frames_bytes and agent:
            recent = agent.frame_ring.last_n_seconds(10)
            if recent:
                ref_frames_bytes = [f["jpeg_bytes"] for f in recent[:3]]
        if not ref_frames_bytes:
            raise RuntimeError(
                "Cannot generate counterfactual: no reference frames available. "
                "The live feed may not have buffered enough frames yet."
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
            anchor_event=anchor_event if anchor_event else {"type": "unknown", "description": text},
            window_frames=ref_frames_bytes,
            captions=window_captions if window_captions else [{"text": text}],
            summary=summaries_list[-1] if summaries_list else {"narrative": text},
            match_state=ms if ms else {"home_team": "Home", "away_team": "Away"},
            session_id=session_id,
        )

        if not brief or not isinstance(brief, dict):
            brief = {"counterfactual_delta": {"beat_description": text}, "continuation_beats": [{"duration_s": 8, "description": text}], "scene": {}, "continuity": {}, "real_event": {"description": ""}, "audio": {"crowd": "cheering"}, "camera": {"persona": "broadcast", "movement": "pan"}, "negative": []}

        # ---- Stage 3: Generate ----
        await state.broadcast(
            session_id,
            "query.progress",
            {"query_id": query_id, "stage": "generating"},
        )

        veo_prompt = build_veo_prompt(brief)
        if not veo_prompt:
            veo_prompt = f"A football match scene. {text} Broadcast camera angle, realistic, stadium atmosphere."

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

        # TODO: Continuity validation requires extracting sample frames from
        # the generated MP4 (needs ffmpeg). For now, attempt it gracefully
        # and merge the verdict if it succeeds.
        try:
            continuity_verdict = await validate_continuity(
                reference_frames=ref_frames_bytes,
                clip_sample_frames=ref_frames_bytes,  # placeholder until ffmpeg frame extraction
                continuity_brief=brief.get("continuity", {}),
                session_id=session_id,
            )
            if continuity_verdict.get("verdict") == "reject":
                verdict["verdict"] = "reject"
                verdict.setdefault("verdict_reasons", []).extend(
                    continuity_verdict.get("verdict_reasons", [])
                )
            elif continuity_verdict.get("verdict") == "regenerate" and verdict.get("verdict") == "ok":
                verdict["verdict"] = "regenerate"
                verdict.setdefault("verdict_reasons", []).extend(
                    continuity_verdict.get("verdict_reasons", [])
                )
        except Exception as e:
            logger.warning("Continuity validation skipped: %s", e)

        # One retry on "regenerate" verdict -- re-run Director with feedback
        if verdict.get("verdict") == "regenerate":
            await state.broadcast(
                session_id,
                "query.progress",
                {"query_id": query_id, "stage": "regenerating"},
            )

            # Re-compose the brief with validator feedback so the Director
            # addresses each complaint structurally
            retry_brief = await compose_veo_brief(
                query={"text": text, **resolved},
                anchor_event=anchor_event if anchor_event else {"type": "unknown", "description": text},
                window_frames=ref_frames_bytes,
                captions=window_captions if window_captions else [{"text": text}],
                summary=summaries_list[-1] if summaries_list else {"narrative": text},
                match_state=ms if ms else {"home_team": "Home", "away_team": "Away"},
                validator_feedback=verdict,
                session_id=session_id,
            )
            if retry_brief and isinstance(retry_brief, dict):
                brief = retry_brief

            veo_prompt = build_veo_prompt(brief)
            if not veo_prompt:
                veo_prompt = f"A football match scene. {text} Broadcast camera angle, realistic, stadium atmosphere."

            clip_bytes, gen_meta = await generate_clip(
                veo_prompt, ref_frames_bytes, session_id=session_id
            )
            verdict = await validate_clip(
                clip_bytes=clip_bytes,
                user_prompt=text,
                real_event=anchor_event,
                counterfactual=brief.get("counterfactual_delta", {}),
                session_id=session_id,
            )

        # ---- Stage 5: Store and broadcast ----
        final_verdict = verdict.get("verdict", "ok")

        if final_verdict == "reject":
            # Clip failed validation -- do NOT broadcast as ready
            rejection_reasons = verdict.get("verdict_reasons", ["validation rejected"])
            for q in state.queries.get(session_id, []):
                if q["id"] == query_id:
                    q["status"] = "failed"
                    q["error"] = f"Clip rejected: {'; '.join(str(r) for r in rejection_reasons)}"
                    break
            await state.broadcast(
                session_id,
                "query.progress",
                {
                    "query_id": query_id,
                    "stage": "failed",
                    "error": f"Clip rejected: {'; '.join(str(r) for r in rejection_reasons)}",
                },
            )
        else:
            clip_path = store(session_id, "clips", f"{query_id}.mp4", clip_bytes)

            clip_entry = {
                "id": f"cl_{query_id}",
                "query_id": query_id,
                "storage_uri": clip_path,
                "duration_ms": int(gen_meta.get("latency_s", 8) * 1000),
                "prompt": text,
                "verdict": final_verdict,
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
