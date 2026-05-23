"""ValidatorAgent -- fidelity checking of generated counterfactual clips."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from google import genai
from google.genai import types

from agents._lib.gemini import get_client
from agents._lib.trace import trace_span

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parents[2] / "prompts"
FIDELITY_PROMPT = (_PROMPTS_DIR / "validator.fidelity.md").read_text()
CONTINUITY_PROMPT = (_PROMPTS_DIR / "validator.continuity.md").read_text()

_MODEL = "gemini-2.5-flash"


async def validate_clip(
    clip_bytes: bytes,
    user_prompt: str,
    real_event: dict,
    counterfactual: dict,
    session_id: str = "",
) -> dict:
    """Run fidelity validation on a generated clip.

    Checks whether the counterfactual change actually occurred and
    the real event does NOT appear.

    Returns:
        {real_event_visible_in_clip, counterfactual_delta_present,
         delta_quality, extra_changes_observed, reasoning,
         verdict: "ok"|"regenerate"|"reject", verdict_reasons: [...]}
    """
    def _sync_fidelity():
        context_text = (
            f"USER_PROMPT: {user_prompt}\n\n"
            f"REAL_EVENT: {json.dumps(real_event)}\n\n"
            f"COUNTERFACTUAL_DELTA: {json.dumps(counterfactual)}"
        )

        client = get_client()
        response = client.models.generate_content(
            model=_MODEL,
            contents=[
                types.Content(
                    parts=[
                        types.Part(
                            inline_data=types.Blob(
                                data=clip_bytes, mime_type="video/mp4"
                            )
                        ),
                        types.Part(text=context_text),
                    ]
                )
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                system_instruction=FIDELITY_PROMPT,
                temperature=0.2,
            ),
        )
        return json.loads(response.text)

    with trace_span("validator", "validate_fidelity", session_id=session_id) as span:
        result = await asyncio.to_thread(_sync_fidelity)
        span["payload"]["model"] = _MODEL
        span["payload"]["verdict"] = result.get("verdict")
        return result


async def validate_continuity(
    reference_frames: list[bytes],
    clip_sample_frames: list[bytes],
    continuity_brief: dict,
    session_id: str = "",
) -> dict:
    """Run visual continuity validation comparing generated clip to reference frames.

    Returns:
        {kit_colors_consistent, stadium_consistent, lighting_consistent,
         camera_persona_consistent, scoreboard_consistent,
         player_count_plausible, physical_artifacts,
         reasoning, verdict, verdict_reasons}
    """
    def _sync_continuity():
        parts: list[types.Part] = []

        # Add reference frames
        for fb in reference_frames:
            parts.append(
                types.Part(
                    inline_data=types.Blob(data=fb, mime_type="image/jpeg")
                )
            )

        # Add sampled clip frames
        for fb in clip_sample_frames:
            parts.append(
                types.Part(
                    inline_data=types.Blob(data=fb, mime_type="image/jpeg")
                )
            )

        context_text = (
            f"REFERENCE_FRAMES: {len(reference_frames)} frames above (first group).\n"
            f"SAMPLED_FRAMES_FROM_CLIP: {len(clip_sample_frames)} frames above (second group).\n\n"
            f"CONTINUITY_BRIEF: {json.dumps(continuity_brief)}"
        )
        parts.append(types.Part(text=context_text))

        client = get_client()
        response = client.models.generate_content(
            model=_MODEL,
            contents=[types.Content(parts=parts)],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                system_instruction=CONTINUITY_PROMPT,
                temperature=0.2,
            ),
        )
        return json.loads(response.text)

    with trace_span(
        "validator", "validate_continuity", session_id=session_id
    ) as span:
        result = await asyncio.to_thread(_sync_continuity)
        span["payload"]["model"] = _MODEL
        span["payload"]["verdict"] = result.get("verdict")
        span["payload"]["ref_count"] = len(reference_frames)
        span["payload"]["sample_count"] = len(clip_sample_frames)
        return result
