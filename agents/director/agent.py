"""DirectorAgent -- composes structured Veo briefs for counterfactual generation."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

from google.genai import types

from agents._lib.gemini import get_client
from agents._lib.trace import trace_span
from agents.director.schema import ReferenceFrame, VeoBrief

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parents[2] / "prompts"
SYSTEM_PROMPT = (_PROMPTS_DIR / "director.system.md").read_text()
VEO_SCHEMA = (_PROMPTS_DIR / "director.veo_schema.md").read_text()
_MODEL = os.environ.get("DIRECTOR_MODEL", "gemini-2.5-flash")


async def compose_veo_brief(
    query: dict,
    anchor_event: dict,
    window_frames: list[ReferenceFrame],
    captions: list[dict],
    summary: dict,
    match_state: dict,
    validator_feedback: dict | None = None,
    session_id: str = "",
) -> VeoBrief:
    """Compose a structured Veo brief from the resolved query and context.

    Args:
        query: Output from RetrievalAgent (anchor_pts_ms, change_type, etc.)
        anchor_event: The structured event at the anchor point.
        window_frames: 4-8 JPEG frames spanning the window (used for count only).
        captions: Per-frame captions for the window.
        summary: Structured summary covering this window.
        match_state: Current match state (score, period, kits, etc.)
        validator_feedback: If regenerating, the validator's complaints.

    Returns:
        Structured Veo brief conforming to director.veo_schema.md
    """
    with trace_span("director", "compose_veo_brief", session_id=session_id) as span:
        frame_metadata = [frame.metadata() for frame in window_frames[:8]]
        context_parts = [
            f"USER_PROMPT: {query.get('user_prompt', query.get('text', ''))}",
            f"ANCHOR_EVENT: {json.dumps(anchor_event)}",
            f"REFERENCE_FRAMES: {json.dumps(frame_metadata)}",
            f"WINDOW_CAPTIONS: {json.dumps(captions)}",
            f"WINDOW_SUMMARY: {json.dumps(summary)}",
            f"MATCH_STATE: {json.dumps(match_state)}",
        ]
        if validator_feedback:
            context_parts.append(
                f"VALIDATOR_FEEDBACK: {json.dumps(validator_feedback)}"
            )
        context_parts.append(f"VEO_SCHEMA:\n{VEO_SCHEMA}")
        context_parts.append(
            "The image parts that follow are the REFERENCE_FRAMES in the same order."
        )
        user_prompt = "\n\n".join(context_parts)

        def _sync_call() -> VeoBrief:
            parts: list[types.Part] = [types.Part(text=user_prompt)]
            for frame in window_frames[:8]:
                parts.extend(
                    [
                        types.Part(
                            text=(
                                f"REFERENCE_FRAME_IMAGE id={frame.id} "
                                f"pts_ms={frame.pts_ms} role_hint={frame.role_hint}"
                            )
                        ),
                        types.Part(
                            inline_data=types.Blob(
                                data=frame.jpeg_bytes,
                                mime_type="image/jpeg",
                            )
                        ),
                    ]
                )

            response = get_client().models.generate_content(
                model=_MODEL,
                contents=[types.Content(parts=parts)],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.4,
                ),
            )
            return VeoBrief.model_validate_json(response.text)

        result = await asyncio.to_thread(_sync_call)
        span["payload"]["model"] = _MODEL
        span["payload"]["frame_ids"] = [frame.id for frame in window_frames[:8]]
        span["payload"]["selected_frame_ids"] = [
            frame.id for frame in result.selected_reference_frames
        ]
        span["payload"]["is_regeneration"] = validator_feedback is not None
        return result
