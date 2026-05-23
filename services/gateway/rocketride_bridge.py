"""Bridge between our FastAPI gateway and RocketRide engine pipelines.

This module manages the RocketRide engine connection and delegates
AI workloads to RocketRide pipelines when the engine is available,
falling back to direct API calls when it isn't.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

PIPELINES_DIR = Path(__file__).parents[2] / "pipelines"
ENGINE_URI = os.environ.get("ROCKETRIDE_ENGINE_URI", "ws://localhost:5565")
ENGINE_KEY = os.environ.get("ROCKETRIDE_API_KEY", "")

_client = None
_engine_available = False


async def init_rocketride() -> bool:
    """Try to connect to the RocketRide engine. Returns True if available."""
    global _client, _engine_available
    try:
        from rocketride import RocketRideClient
        _client = RocketRideClient(uri=ENGINE_URI)
        await asyncio.to_thread(_client.connect, ENGINE_KEY)
        _engine_available = True
        logger.info("RocketRide engine connected at %s", ENGINE_URI)
        return True
    except Exception as e:
        logger.warning("RocketRide engine not available: %s. Using direct API fallback.", e)
        _engine_available = False
        return False


def is_engine_available() -> bool:
    return _engine_available


async def run_perception_pipeline(video_path: str) -> dict:
    """Run the perception pipeline on a local video file.

    Uses RocketRide's frame_grabber + llm_vision_gemini + agent_rocketride
    if the engine is available; falls back to direct Gemini calls otherwise.
    """
    if not _engine_available or _client is None:
        return await _fallback_perception(video_path)

    try:
        pipe_path = str(PIPELINES_DIR / "perception.pipe")
        token = await asyncio.to_thread(_client.use, filepath=pipe_path)

        with open(video_path, "rb") as f:
            video_data = f.read()

        result = await asyncio.to_thread(
            _client.send, token, video_data, "match_video.mp4", "video/mp4"
        )

        status = await asyncio.to_thread(_client.get_task_status, token)
        logger.info("Perception pipeline completed: %s", status)

        return result if isinstance(result, dict) else {"raw": str(result)}

    except Exception as e:
        logger.error("RocketRide perception failed: %s. Falling back.", e)
        return await _fallback_perception(video_path)


async def run_whatif_pipeline(query: str, context: dict) -> dict:
    """Run the what-if director pipeline via RocketRide.

    Uses agent_rocketride (Wave agent) with GMI Cloud DeepSeek as LLM,
    tool_python for timeline search and brief composition.
    """
    if not _engine_available or _client is None:
        return await _fallback_whatif(query, context)

    try:
        pipe_path = str(PIPELINES_DIR / "whatif-director.pipe")
        token = await asyncio.to_thread(_client.use, filepath=pipe_path)

        prompt = f"Match context:\n{json.dumps(context, indent=2)}\n\nUser question: {query}"
        result = await asyncio.to_thread(
            _client.send, token, prompt, "query.txt", "text/plain"
        )

        return result if isinstance(result, dict) else {"raw": str(result)}

    except Exception as e:
        logger.error("RocketRide what-if failed: %s. Falling back.", e)
        return await _fallback_whatif(query, context)


async def _fallback_perception(video_path: str) -> dict:
    """Direct API fallback when RocketRide engine is unavailable."""
    from agents.summariser.agent import summarise_window
    with open(video_path, "rb") as f:
        video_bytes = f.read()
    return await summarise_window(video_bytes, {})


async def _fallback_whatif(query: str, context: dict) -> dict:
    """Direct API fallback when RocketRide engine is unavailable."""
    from agents.director.agent import compose_veo_brief
    return await compose_veo_brief(
        query={"text": query},
        anchor_event=context.get("anchor_event", {}),
        window_frames=[],
        captions=context.get("captions", []),
        summary=context.get("summary", {}),
        match_state=context.get("match_state", {}),
    )
