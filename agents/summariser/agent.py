"""SummariserAgent -- deep video-window summarisation via gemini-3.5-flash."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from google import genai
from google.genai import types

from agents._lib.gemini import get_client
from agents._lib.trace import trace_span

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parents[2] / "prompts"
SYSTEM_PROMPT = (_PROMPTS_DIR / "summariser.system.md").read_text()

_MODEL = "gemini-3.5-flash"


async def summarise_window(
    video_bytes: bytes, match_meta: dict, session_id: str = ""
) -> dict:
    """Summarise a ~30-second MP4 clip with structured event detection.

    Returns:
        {narrative, structured, events, self_critique}
    """
    with trace_span("summariser", "summarise_window", session_id=session_id) as span:
        client = get_client()
        prompt_with_meta = (
            SYSTEM_PROMPT + "\n\nMATCH_META: " + json.dumps(match_meta)
        )
        response = client.models.generate_content(
            model=_MODEL,
            contents=[
                types.Content(
                    parts=[
                        types.Part(
                            inline_data=types.Blob(
                                data=video_bytes, mime_type="video/mp4"
                            )
                        ),
                        types.Part(text=prompt_with_meta),
                    ]
                )
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2,
            ),
        )
        result = json.loads(response.text)
        span["payload"]["model"] = _MODEL
        span["payload"]["event_count"] = len(result.get("events", []))
        span["payload"]["should_expand"] = result.get("self_critique", {}).get(
            "should_expand_window", False
        )
        return result
