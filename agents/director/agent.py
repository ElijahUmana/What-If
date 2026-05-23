"""DirectorAgent -- composes structured Veo briefs for counterfactual generation."""

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
SYSTEM_PROMPT = (_PROMPTS_DIR / "director.system.md").read_text()
VEO_SCHEMA = (_PROMPTS_DIR / "director.veo_schema.md").read_text()

_MODEL = "gemini-3.5-flash"


async def compose_veo_brief(
    query: dict,
    anchor_event: dict,
    window_frames: list[bytes],
    captions: list[dict],
    summary: dict,
    match_state: dict,
    validator_feedback: dict | None = None,
    session_id: str = "",
) -> dict:
    """Compose a structured Veo brief from the resolved query and context.

    Args:
        query: Output from RetrievalAgent (anchor_pts_ms, change_type, etc.)
        anchor_event: The structured event at the anchor point.
        window_frames: 4-8 JPEG frames spanning the window.
        captions: Per-frame captions for the window.
        summary: Structured summary covering this window.
        match_state: Current match state (score, period, kits, etc.)
        validator_feedback: If regenerating, the validator's complaints.

    Returns:
        Structured Veo brief JSON conforming to director.veo_schema.md
    """
    with trace_span("director", "compose_veo_brief", session_id=session_id) as span:
        # Build the text context
        context_parts = [
            f"USER_PROMPT: {query.get('user_prompt', query.get('query_text', ''))}",
            f"ANCHOR_EVENT: {json.dumps(anchor_event)}",
            f"WINDOW_CAPTIONS: {json.dumps(captions)}",
            f"WINDOW_SUMMARY: {json.dumps(summary)}",
            f"MATCH_STATE: {json.dumps(match_state)}",
        ]
        if validator_feedback:
            context_parts.append(
                f"VALIDATOR_FEEDBACK: {json.dumps(validator_feedback)}"
            )
        context_parts.append(f"VEO_SCHEMA:\n{VEO_SCHEMA}")
        context_text = "\n\n".join(context_parts)

        # Build content parts: reference frames as images + text context
        parts: list[types.Part] = []
        for i, frame_bytes in enumerate(window_frames[:8]):
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
                temperature=0.4,
            ),
        )
        result = json.loads(response.text)
        span["payload"]["model"] = _MODEL
        span["payload"]["frame_count"] = len(window_frames[:8])
        span["payload"]["is_regeneration"] = validator_feedback is not None
        return result
