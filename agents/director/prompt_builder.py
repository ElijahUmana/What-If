"""Converts a structured Veo brief into a natural-language Veo prompt (<=1024 tokens)."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _safe_dict(val, default=None) -> dict:
    """Return val if it's a dict, else default or empty dict."""
    if isinstance(val, dict):
        return val
    return default if default is not None else {}


def _safe_list(val) -> list:
    """Return val if it's a list, else empty list."""
    return val if isinstance(val, list) else []


def _safe_str(val) -> str:
    """Return val if it's a string, else str(val) or empty."""
    if val is None:
        return ""
    return str(val)


def build_veo_prompt(brief: dict) -> str:
    """Convert a structured Veo brief dict into a single natural-language prompt.

    The output concatenates: SCENE, CONTINUITY, WHAT ACTUALLY HAPPENED (negative),
    WHAT IF (positive), CONTINUATION beats, AUDIO, CAMERA, AVOID.
    Kept under ~1024 tokens by being concise in each section.

    If the brief contains a top-level "veo_prompt" key (the Director sometimes
    returns this directly), use it as the base and only append missing sections.
    """
    if not brief or not isinstance(brief, dict):
        return ""

    # If the Director returned a ready-made veo_prompt, use it as the base
    # but still append camera guidance and negative constraints below.
    has_direct_prompt = False
    if brief.get("veo_prompt") and isinstance(brief["veo_prompt"], str):
        direct_prompt = brief["veo_prompt"].strip()
        if len(direct_prompt) > 50:
            has_direct_prompt = True

    sections: list[str] = []

    if has_direct_prompt:
        sections.append(direct_prompt)

    # SCENE
    scene = _safe_dict(brief.get("scene"))
    scene_parts = []
    if _safe_str(scene.get("stadium")):
        scene_parts.append(scene["stadium"])
    if _safe_str(scene.get("weather")):
        scene_parts.append(f"{scene['weather']} weather")
    if _safe_str(scene.get("lighting")):
        scene_parts.append(f"{scene['lighting']} lighting")
    if _safe_str(scene.get("crowd_density")):
        scene_parts.append(f"{scene['crowd_density']} crowd")
    if _safe_str(scene.get("stadium_dressing")):
        scene_parts.append(scene["stadium_dressing"])
    if scene_parts:
        sections.append("Cinematic broadcast shot. " + ", ".join(scene_parts) + ".")

    # CONTINUITY
    cont = _safe_dict(brief.get("continuity"))
    cont_parts = []
    for side in ("home", "away"):
        team = _safe_dict(cont.get(side))
        if team:
            name = _safe_str(team.get("name")) or side.title()
            primary = _safe_str(team.get("kit_color_primary"))
            secondary = _safe_str(team.get("kit_color_secondary"))
            gk = _safe_str(team.get("gk_kit_color"))
            kit_desc = primary if primary else "standard kit"
            if secondary:
                kit_desc += f" with {secondary} trim"
            cont_parts.append(f"{name} wearing {kit_desc} jerseys")
            if gk:
                cont_parts.append(f"{name} goalkeeper in {gk}")
    if _safe_str(cont.get("referee_kit")):
        cont_parts.append(f"referee in {cont['referee_kit']}")
    if _safe_str(cont.get("scoreboard_overlay")):
        cont_parts.append(f"scoreboard: {cont['scoreboard_overlay']}")
    if cont_parts:
        sections.append("Visual continuity: " + ". ".join(cont_parts) + ".")

    # WHAT ACTUALLY HAPPENED (negative -- the model should NOT show this)
    real = _safe_dict(brief.get("real_event"))
    real_desc = _safe_str(real.get("description"))
    if real_desc:
        sections.append(
            f"What actually happened (do NOT show this): {real_desc}"
        )

    # WHAT IF (positive -- the counterfactual the model SHOULD show)
    delta = _safe_dict(brief.get("counterfactual_delta"))
    beat_desc = _safe_str(delta.get("beat_description"))
    user_verbatim = _safe_str(delta.get("user_prompt_verbatim"))
    if beat_desc:
        sections.append(
            f"Instead, show this counterfactual: {beat_desc}"
        )
    elif user_verbatim:
        sections.append(
            f"Instead, show this counterfactual: {user_verbatim}"
        )

    # CONTINUATION BEATS
    beats = _safe_list(brief.get("continuation_beats"))
    if beats:
        beat_lines = []
        for i, beat in enumerate(beats, 1):
            if not isinstance(beat, dict):
                continue
            dur = beat.get("duration_s", "?")
            desc = _safe_str(beat.get("description"))
            if desc:
                beat_lines.append(f"  Beat {i} ({dur}s): {desc}")
        if beat_lines:
            sections.append("The scene unfolds:\n" + "\n".join(beat_lines))

    # AUDIO
    audio = _safe_dict(brief.get("audio"))
    audio_parts = []
    if _safe_str(audio.get("crowd")):
        audio_parts.append(f"Crowd: {audio['crowd']}")
    if _safe_str(audio.get("broadcaster_voiceover")):
        audio_parts.append(f"Voiceover: {audio['broadcaster_voiceover']}")
    if _safe_str(audio.get("ambient")):
        audio_parts.append(f"Ambient: {audio['ambient']}")
    if audio_parts:
        sections.append("Sound design: " + ". ".join(audio_parts) + ".")

    # CAMERA
    camera = _safe_dict(brief.get("camera"))
    cam_parts = []
    if _safe_str(camera.get("persona")):
        cam_parts.append(camera["persona"].replace("_", " "))
    if _safe_str(camera.get("movement")):
        cam_parts.append(camera["movement"])
    if cam_parts:
        sections.append("Camera: " + ", ".join(cam_parts) + ".")
    else:
        # Default camera guidance for Veo
        sections.append("Camera: broadcast wide angle, smooth pan following play.")

    # AVOID (negative constraints)
    negatives = _safe_list(brief.get("negative"))
    if negatives:
        neg_strs = [_safe_str(n) for n in negatives if _safe_str(n)]
        if neg_strs:
            sections.append("Avoid: " + "; ".join(neg_strs) + ".")

    prompt = "\n\n".join(s for s in sections if s)

    if not prompt:
        # Fallback: try to construct something from whatever keys exist
        fallback_parts = []
        for key in ("beat_description", "description", "text", "user_prompt_verbatim"):
            val = brief.get(key) or (delta.get(key) if isinstance(delta, dict) else None)
            if val:
                fallback_parts.append(str(val))
        if fallback_parts:
            prompt = "A football match scene, broadcast camera angle. " + " ".join(fallback_parts)

    # Rough token estimation: ~4 chars per token. Trim if needed.
    max_chars = 1024 * 4
    if len(prompt) > max_chars:
        prompt = prompt[:max_chars].rsplit(" ", 1)[0] + "..."

    return prompt
