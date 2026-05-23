"""FrameCaptionerAgent -- fast per-frame captioning via gemini-3.1-flash-lite."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from google import genai
from google.genai import types

from agents._lib.gemini import get_client
from agents._lib.trace import trace_span

logger = logging.getLogger(__name__)

# Load system prompt once at module level
_PROMPTS_DIR = Path(__file__).parents[2] / "prompts"
SYSTEM_PROMPT = (_PROMPTS_DIR / "captioner.system.md").read_text()

_MODEL = "gemini-3.1-flash-lite"


async def caption_frame(frame_bytes: bytes, session_id: str = "") -> dict:
    """Caption a single JPEG frame and return structured tags."""
    import asyncio

    def _sync_call():
        client = get_client()
        response = client.models.generate_content(
            model=_MODEL,
            contents=[
                types.Content(
                    parts=[
                        types.Part(
                            inline_data=types.Blob(
                                data=frame_bytes, mime_type="image/jpeg"
                            )
                        ),
                        types.Part(text=SYSTEM_PROMPT),
                    ]
                )
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2,
            ),
        )
        return json.loads(response.text)

    with trace_span("captioner", "caption_frame", session_id=session_id) as span:
        result = await asyncio.to_thread(_sync_call)
        span["payload"]["model"] = _MODEL
        span["payload"]["scene_type"] = result.get("scene_type")
        return result
