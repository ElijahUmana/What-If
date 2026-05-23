"""DirectorAgent -- composes structured Veo briefs for counterfactual generation."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from agents._lib.gmi import reason as gmi_reason
from agents._lib.trace import trace_span

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parents[2] / "prompts"
SYSTEM_PROMPT = (_PROMPTS_DIR / "director.system.md").read_text()
VEO_SCHEMA = (_PROMPTS_DIR / "director.veo_schema.md").read_text()


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
        window_frames: 4-8 JPEG frames spanning the window (used for count only).
        captions: Per-frame captions for the window.
        summary: Structured summary covering this window.
        match_state: Current match state (score, period, kits, etc.)
        validator_feedback: If regenerating, the validator's complaints.

    Returns:
        Structured Veo brief JSON conforming to director.veo_schema.md
    """
    with trace_span("director", "compose_veo_brief", session_id=session_id) as span:
        # Build the text context (GMI has no vision -- use captions as text context)
        context_parts = [
            f"USER_PROMPT: {query.get('user_prompt', query.get('text', ''))}",
            f"ANCHOR_EVENT: {json.dumps(anchor_event)}",
            f"WINDOW_CAPTIONS: {json.dumps(captions)}",
            f"WINDOW_SUMMARY: {json.dumps(summary)}",
            f"MATCH_STATE: {json.dumps(match_state)}",
            f"REFERENCE_FRAME_COUNT: {len(window_frames[:8])}",
        ]
        if validator_feedback:
            context_parts.append(
                f"VALIDATOR_FEEDBACK: {json.dumps(validator_feedback)}"
            )
        context_parts.append(f"VEO_SCHEMA:\n{VEO_SCHEMA}")
        user_prompt = "\n\n".join(context_parts)

        result = await asyncio.to_thread(gmi_reason, SYSTEM_PROMPT, user_prompt)
        span["payload"]["model"] = "deepseek-ai/DeepSeek-V4-Flash"
        span["payload"]["frame_count"] = len(window_frames[:8])
        span["payload"]["is_regeneration"] = validator_feedback is not None
        return result
