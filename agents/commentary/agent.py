"""CommentaryAgent -- live AI co-commentator via gemini-3.5-flash text calls."""

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
PERSONA_PROMPT = (_PROMPTS_DIR / "commentary.persona.md").read_text()

_MODEL = "gemini-3.5-flash"


def _build_feed(
    events: list[dict], summaries: list[dict], match_state: dict
) -> str:
    """Build the commentary feed text from structured inputs."""
    lines: list[str] = []

    # Inject match state
    lines.append(f"state:{json.dumps(match_state)}")

    # Inject latest summary (most recent first)
    for s in summaries[-3:]:
        lines.append(f"summary:{json.dumps(s)}")

    # Inject recent events
    for ev in events[-10:]:
        lines.append(f"event:{json.dumps(ev)}")

    return "\n".join(lines)


async def generate_commentary(
    events: list[dict],
    summaries: list[dict],
    match_state: dict,
    session_id: str = "",
) -> str:
    """Generate a commentary line based on the latest match events.

    Returns a short commentary string (1-3 sentences).
    """
    with trace_span(
        "commentary", "generate_commentary", session_id=session_id
    ) as span:
        feed = _build_feed(events, summaries, match_state)

        client = get_client()
        response = client.models.generate_content(
            model=_MODEL,
            contents=[types.Content(parts=[types.Part(text=feed)])],
            config=types.GenerateContentConfig(
                system_instruction=PERSONA_PROMPT,
                temperature=0.7,
                max_output_tokens=200,
            ),
        )
        text = response.text.strip()
        span["payload"]["model"] = _MODEL
        span["payload"]["commentary_length"] = len(text)
        span["payload"]["event_count"] = len(events)
        return text
