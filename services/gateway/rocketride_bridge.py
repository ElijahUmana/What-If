"""Bridge between our gateway and the RocketRide engine.

Routes what-if reasoning through RocketRide's agent_rocketride + llm_gmi_cloud
pipeline. Falls back to direct API calls when the engine isn't available.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

PIPELINES_DIR = Path(__file__).parents[2] / "pipelines"
ENGINE_KEY = os.environ.get("ROCKETRIDE_API_KEY", "local")

_client = None
_engine_available = False
_director_token = None


def _detect_engine_port() -> str:
    try:
        out = subprocess.run(
            ["lsof", "-i", "-P", "-n"], capture_output=True, text=True, timeout=5,
        ).stdout
        for line in out.splitlines():
            if "engine" in line and "LISTEN" in line:
                port = line.split(":")[-1].split()[0]
                return f"ws://localhost:{port}"
    except Exception:
        pass
    return os.environ.get("ROCKETRIDE_ENGINE_URI", "ws://localhost:5565")


async def init_rocketride() -> bool:
    global _client, _engine_available, _director_token
    try:
        from rocketride import RocketRideClient

        uri = _detect_engine_port()
        _client = RocketRideClient(uri=uri)
        await _client.connect(ENGINE_KEY)
        logger.info("RocketRide engine connected at %s", uri)

        pipe_path = PIPELINES_DIR / "whatif-director.pipe"
        if pipe_path.exists():
            with open(pipe_path) as f:
                pipe_config = json.load(f)
            # Substitute GMI key
            gmi_key = os.environ.get("GMI_API_KEY", "")
            for comp in pipe_config.get("components", []):
                cfg = comp.get("config", {})
                if cfg.get("apikey") == "${ROCKETRIDE_GMI_KEY}":
                    cfg["apikey"] = gmi_key
            result = await _client.use(pipeline=pipe_config)
            _director_token = result.get("token")
            logger.info("RocketRide director pipeline loaded: %s", _director_token)

        _engine_available = True
        return True
    except Exception as e:
        logger.warning("RocketRide engine not available: %s. Direct API fallback.", e)
        _engine_available = False
        return False


def is_engine_available() -> bool:
    return _engine_available


async def reason_via_rocketride(prompt: str) -> dict:
    """Send a what-if query through the RocketRide agent pipeline."""
    if not _engine_available or _client is None or _director_token is None:
        return await _fallback_reason(prompt)
    try:
        from rocketride import Question
        q = Question(text=prompt)
        resp = await _client.chat(token=_director_token, question=q)
        answer = resp.get("answers", ["{}"])[0] if isinstance(resp, dict) else str(resp)
        try:
            return json.loads(answer)
        except (json.JSONDecodeError, TypeError):
            return {"raw": answer}
    except Exception as e:
        logger.warning("RocketRide query failed: %s. Falling back.", e)
        return await _fallback_reason(prompt)


async def _fallback_reason(prompt: str) -> dict:
    from agents._lib.gmi import reason
    return await asyncio.to_thread(reason, "You are a football analyst.", prompt)
