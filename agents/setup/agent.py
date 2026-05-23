"""SetupAgent -- identifies the match from YouTube metadata + first frames."""

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
SYSTEM_PROMPT = (_PROMPTS_DIR / "setup.match_meta.md").read_text()

_MODEL = "gemini-2.5-flash"


async def identify_match(
    video_title: str,
    first_frames: list[bytes],
    video_description: str = "",
    session_id: str = "",
) -> dict:
    """Identify the match from YouTube title/description and opening frames.

    Returns:
        {home_team, away_team, competition, kickoff_at_utc, broadcaster,
         home_kit_color_primary, home_kit_color_secondary, home_gk_kit_color,
         away_kit_color_primary, away_kit_color_secondary, away_gk_kit_color,
         stadium, confidence, unknown}
    """
    with trace_span("setup", "identify_match", session_id=session_id) as span:
        context_text = (
            f"VIDEO_TITLE: {video_title}\n\n"
            f"VIDEO_DESCRIPTION: {video_description[:500]}"
        )

        # Build content: frames as images + text context
        parts: list[types.Part] = []
        for frame_bytes in first_frames[:6]:
            parts.append(
                types.Part(
                    inline_data=types.Blob(
                        data=frame_bytes, mime_type="image/jpeg"
                    )
                )
            )
        parts.append(types.Part(text=context_text))

        client = get_client()
        response = client.models.generate_content(
            model=_MODEL,
            contents=[types.Content(parts=parts)],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                system_instruction=SYSTEM_PROMPT,
                temperature=0.2,
            ),
        )
        result = json.loads(response.text)
        span["payload"]["model"] = _MODEL
        span["payload"]["confidence"] = result.get("confidence")
        span["payload"]["unknown"] = result.get("unknown", False)
        span["payload"]["frame_count"] = len(first_frames[:6])
        logger.info(
            "Match identified: %s vs %s (%s) confidence=%.2f",
            result.get("home_team", "?"),
            result.get("away_team", "?"),
            result.get("competition", "?"),
            result.get("confidence", 0),
        )
        return result
