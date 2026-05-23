"""Bridge between our gateway and the RocketRide engine.

Routes GMI Cloud and Gemini API calls through RocketRide's LLM nodes
when the engine is available. Falls back to direct API calls when not.
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
_director_token = None


async def init_rocketride() -> bool:
    """Connect to the RocketRide engine on startup."""
    global _client, _engine_available, _director_token
    try:
        from rocketride import RocketRideClient
        _client = RocketRideClient(uri=ENGINE_URI)
        await _client.connect(ENGINE_KEY)
        _engine_available = True
        logger.info("RocketRide engine connected at %s", ENGINE_URI)

        # Load the what-if director pipeline
        pipe_path = str(PIPELINES_DIR / "whatif-director.pipe")
        if os.path.exists(pipe_path):
            _director_token = await _client.use(filepath=pipe_path)
            logger.info("Loaded whatif-director pipeline: token=%s", _director_token)

        return True
    except Exception as e:
        logger.warning("RocketRide engine not available (%s). Using direct API fallback.", e)
        _engine_available = False
        return False


def is_engine_available() -> bool:
    return _engine_available


async def reason_via_rocketride(system_prompt: str, user_prompt: str) -> dict:
    """Route a reasoning call through RocketRide's agent pipeline.

    When the engine is available, sends the prompt to the whatif-director
    pipeline which uses agent_rocketride (Wave planning) with llm_openai_api
    pointed at GMI Cloud DeepSeek V4 Flash.

    Falls back to direct GMI API call when engine isn't available.
    """
    if not _engine_available or _client is None or _director_token is None:
        return await _fallback_reason(system_prompt, user_prompt)

    try:
        prompt = f"System: {system_prompt}\n\nUser: {user_prompt}"
        result = await _client.send(
            _director_token,
            prompt,
            "query.txt",
            "text/plain",
        )
        if isinstance(result, dict):
            return result
        if isinstance(result, str):
            return json.loads(result)
        return {"raw": str(result)}
    except Exception as e:
        logger.warning("RocketRide reason failed (%s), falling back to direct API", e)
        return await _fallback_reason(system_prompt, user_prompt)


async def chat_via_rocketride(system_prompt: str, user_prompt: str) -> str:
    """Route a chat call through RocketRide. Falls back to GMI direct."""
    if not _engine_available or _client is None:
        return await _fallback_chat(system_prompt, user_prompt)

    try:
        prompt = f"System: {system_prompt}\n\nUser: {user_prompt}"
        result = await _client.chat(_director_token, prompt)
        return str(result)
    except Exception as e:
        logger.warning("RocketRide chat failed (%s), falling back", e)
        return await _fallback_chat(system_prompt, user_prompt)


async def _fallback_reason(system_prompt: str, user_prompt: str) -> dict:
    from agents._lib.gmi import reason
    return await asyncio.to_thread(reason, system_prompt, user_prompt)


async def _fallback_chat(system_prompt: str, user_prompt: str) -> str:
    from agents._lib.gmi import chat
    return await asyncio.to_thread(chat, system_prompt, user_prompt)
