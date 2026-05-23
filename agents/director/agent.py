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
        # Build maximally detailed text context (GMI has no vision -- captions
        # are our ONLY visual signal, so include every single one verbatim)

        user_prompt_text = query.get("user_prompt", query.get("text", ""))

        # --- Concatenate ALL caption texts so the LLM sees every visual detail ---
        caption_texts: list[str] = []
        for i, cap in enumerate(captions):
            pts = cap.get("pts_ms", "?")
            txt = cap.get("text", "")
            if txt:
                caption_texts.append(f"  [{i+1}] @{pts}ms: {txt}")
        captions_block = "\n".join(caption_texts) if caption_texts else "(no captions available)"

        # --- Extract rich summary narrative ---
        summary_narrative = ""
        if isinstance(summary, dict):
            summary_narrative = summary.get("narrative", "")
            structured = summary.get("structured", {})
            events_in_summary = summary.get("events", [])
        else:
            structured = {}
            events_in_summary = []

        # --- Extract match state details for explicit inclusion ---
        home_team = match_state.get("home_team", "Home")
        away_team = match_state.get("away_team", "Away")
        home_kit = match_state.get("home_kit", match_state.get("home_kit_color_primary", "unknown"))
        away_kit = match_state.get("away_kit", match_state.get("away_kit_color_primary", "unknown"))
        score_home = match_state.get("score", {}).get("home", "?") if isinstance(match_state.get("score"), dict) else "?"
        score_away = match_state.get("score", {}).get("away", "?") if isinstance(match_state.get("score"), dict) else "?"
        period = match_state.get("period", "unknown")

        # --- Anchor event details ---
        anchor_type = anchor_event.get("type", "unknown")
        anchor_desc = anchor_event.get("description", user_prompt_text)
        anchor_pts = anchor_event.get("pts_ms", query.get("anchor_pts_ms", 0))
        anchor_confidence = anchor_event.get("confidence", "N/A")

        context_parts = [
            f"USER_PROMPT: {user_prompt_text}",

            "MATCH STATE:\n"
            f"  Home team: {home_team} (kit: {home_kit})\n"
            f"  Away team: {away_team} (kit: {away_kit})\n"
            f"  Score: {home_team} {score_home} - {score_away} {away_team}\n"
            f"  Period: {period}",

            f"ANCHOR_EVENT:\n"
            f"  Type: {anchor_type}\n"
            f"  Description: {anchor_desc}\n"
            f"  Timestamp: {anchor_pts}ms\n"
            f"  Confidence: {anchor_confidence}\n"
            f"  Full data: {json.dumps(anchor_event)}",

            f"REFERENCE_FRAME_COUNT: {len(window_frames[:8])}",

            f"FRAME-BY-FRAME CAPTIONS (these are your ONLY visual reference — "
            f"use them to determine camera angle, player positions, jersey colours, "
            f"ball location, crowd state, stadium details, lighting, and weather):\n"
            f"{captions_block}",

            f"WINDOW_SUMMARY_NARRATIVE:\n{summary_narrative}" if summary_narrative else "",

            f"WINDOW_SUMMARY_STRUCTURED: {json.dumps(structured)}" if structured else "",

            f"EVENTS_IN_WINDOW: {json.dumps(events_in_summary)}" if events_in_summary else "",
        ]

        if validator_feedback:
            feedback_reasons = validator_feedback.get("verdict_reasons", [])
            feedback_reasoning = validator_feedback.get("reasoning", "")
            context_parts.append(
                f"VALIDATOR_FEEDBACK (you MUST address each complaint):\n"
                f"  Reasons: {json.dumps(feedback_reasons)}\n"
                f"  Detail: {feedback_reasoning}\n"
                f"  Full: {json.dumps(validator_feedback)}"
            )

        context_parts.append(
            "IMPORTANT INSTRUCTIONS FOR VEO PROMPT CONSTRUCTION:\n"
            "- You cannot see the frames. The captions above are your ONLY visual info.\n"
            "- Extract SPECIFIC details from captions: exact jersey colors, camera angle "
            "(wide/tight/overhead), ball position, player formations, pitch markings, "
            "stadium signage, weather/lighting conditions, crowd density.\n"
            "- The Veo prompt MUST describe the visual scene in precise cinematic detail "
            "so the video matches the real broadcast footage.\n"
            "- Include jersey numbers and player positions when mentioned in captions.\n"
            "- Describe the camera movement (static, panning left/right, tracking).\n"
            "- Specify the exact moment of divergence from reality."
        )

        context_parts.append(f"VEO_SCHEMA:\n{VEO_SCHEMA}")

        # Filter out empty parts
        user_prompt = "\n\n".join(p for p in context_parts if p)

        result = await asyncio.to_thread(gmi_reason, SYSTEM_PROMPT, user_prompt)
        span["payload"]["model"] = "deepseek-ai/DeepSeek-V4-Flash"
        span["payload"]["frame_count"] = len(window_frames[:8])
        span["payload"]["caption_count"] = len(captions)
        span["payload"]["is_regeneration"] = validator_feedback is not None
        return result
