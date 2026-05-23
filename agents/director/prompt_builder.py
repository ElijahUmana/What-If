"""Converts a structured Veo brief into a natural-language Veo prompt (<=1024 tokens)."""

from __future__ import annotations


def build_veo_prompt(brief: dict) -> str:
    """Convert a structured Veo brief dict into a single natural-language prompt.

    The output concatenates: SCENE, CONTINUITY, WHAT ACTUALLY HAPPENED (negative),
    WHAT IF (positive), CONTINUATION beats, AUDIO, CAMERA, AVOID.
    Kept under ~1024 tokens by being concise in each section.
    """
    sections: list[str] = []

    # SCENE
    scene = brief.get("scene", {})
    scene_parts = []
    if scene.get("stadium"):
        scene_parts.append(scene["stadium"])
    if scene.get("weather"):
        scene_parts.append(f"{scene['weather']} weather")
    if scene.get("lighting"):
        scene_parts.append(f"{scene['lighting']} lighting")
    if scene.get("crowd_density"):
        scene_parts.append(f"{scene['crowd_density']} crowd")
    if scene.get("stadium_dressing"):
        scene_parts.append(scene["stadium_dressing"])
    if scene_parts:
        sections.append("SCENE: " + ", ".join(scene_parts) + ".")

    # CONTINUITY
    cont = brief.get("continuity", {})
    cont_parts = []
    for side in ("home", "away"):
        team = cont.get(side, {})
        if team:
            name = team.get("name", side.title())
            primary = team.get("kit_color_primary", "")
            secondary = team.get("kit_color_secondary", "")
            gk = team.get("gk_kit_color", "")
            kit_desc = primary
            if secondary:
                kit_desc += f" with {secondary} trim"
            cont_parts.append(f"{name} in {kit_desc}")
            if gk:
                cont_parts.append(f"{name} GK in {gk}")
    if cont.get("referee_kit"):
        cont_parts.append(f"referee in {cont['referee_kit']}")
    if cont_parts:
        sections.append("CONTINUITY: " + ". ".join(cont_parts) + ".")

    # WHAT ACTUALLY HAPPENED (negative -- the model should NOT show this)
    real = brief.get("real_event", {})
    if real.get("description"):
        sections.append(
            f"WHAT ACTUALLY HAPPENED (do NOT show this): {real['description']}"
        )

    # WHAT IF (positive -- the counterfactual the model SHOULD show)
    delta = brief.get("counterfactual_delta", {})
    if delta.get("beat_description"):
        sections.append(f"WHAT IF (show this instead): {delta['beat_description']}")

    # CONTINUATION BEATS
    beats = brief.get("continuation_beats", [])
    if beats:
        beat_lines = []
        for i, beat in enumerate(beats, 1):
            dur = beat.get("duration_s", "?")
            desc = beat.get("description", "")
            beat_lines.append(f"  Beat {i} ({dur}s): {desc}")
        sections.append("CONTINUATION:\n" + "\n".join(beat_lines))

    # AUDIO
    audio = brief.get("audio", {})
    audio_parts = []
    if audio.get("crowd"):
        audio_parts.append(f"Crowd: {audio['crowd']}")
    if audio.get("broadcaster_voiceover"):
        audio_parts.append(f"Voiceover: {audio['broadcaster_voiceover']}")
    if audio.get("ambient"):
        audio_parts.append(f"Ambient: {audio['ambient']}")
    if audio_parts:
        sections.append("AUDIO: " + ". ".join(audio_parts) + ".")

    # CAMERA
    camera = brief.get("camera", {})
    cam_parts = []
    if camera.get("persona"):
        cam_parts.append(camera["persona"].replace("_", " "))
    if camera.get("movement"):
        cam_parts.append(camera["movement"])
    if cam_parts:
        sections.append("CAMERA: " + ", ".join(cam_parts) + ".")

    # AVOID (negative constraints)
    negatives = brief.get("negative", [])
    if negatives:
        sections.append("AVOID: " + "; ".join(negatives) + ".")

    prompt = "\n\n".join(sections)

    # Rough token estimation: ~4 chars per token. Trim if needed.
    max_chars = 1024 * 4
    if len(prompt) > max_chars:
        prompt = prompt[:max_chars].rsplit(" ", 1)[0] + "..."

    return prompt
