from __future__ import annotations

import unittest

from agents.director.prompt_builder import build_veo_prompt
from agents.director.schema import VeoBrief


def sample_brief_payload() -> dict:
    return {
        "selected_reference_frames": [
            {"id": "rf_001_1000", "role": "pre_change_frame", "pts_ms": 1000},
            {"id": "rf_002_2000", "role": "camera_angle_lock", "pts_ms": 2000},
            {"id": "rf_003_3000", "role": "stadium_lighting_ref", "pts_ms": 3000},
        ],
        "scene": {
            "stadium": "North Stand",
            "stadium_dressing": "blue sponsor boards",
            "weather": "clear",
            "lighting": "floodlights",
            "crowd_density": "mostly_full",
        },
        "continuity": {
            "home": {
                "name": "Home",
                "kit_color_primary": "red",
                "kit_color_secondary": "white",
                "gk_kit_color": "green",
            },
            "away": {
                "name": "Away",
                "kit_color_primary": "blue",
                "kit_color_secondary": "black",
                "gk_kit_color": "yellow",
            },
            "referee_kit": "black",
            "scoreboard_overlay": "small top-left clock",
            "broadcaster_chrome": "no lower third",
        },
        "real_event": {
            "anchor_pts_ms": 2000,
            "event_type": "shot",
            "actors": [{"role": "striker", "team": "home", "jersey_number": 9}],
            "description": "The striker shoots low and the keeper saves.",
        },
        "counterfactual_delta": {
            "moment_of_divergence_ms": 2000,
            "user_prompt_verbatim": "What if that shot went in?",
            "beat_description": "The striker shoots higher and the ball beats the keeper.",
        },
        "continuation_beats": [
            {"duration_s": 2, "description": "The ball hits the net."},
            {"duration_s": 3, "description": "The striker turns toward the corner."},
            {"duration_s": 3, "description": "Teammates run in from midfield."},
        ],
        "audio": {
            "crowd": "home crowd erupts",
            "broadcaster_voiceover": None,
            "ambient": "stadium ambience",
        },
        "camera": {
            "persona": "broadcast_wide_angle",
            "movement": "pan with the attack",
            "no_graphics_overlay": True,
        },
        "negative": [
            "do not change kit colours",
            "do not change player positions before the divergence moment",
        ],
        "model_params": {
            "duration_s": 8,
            "fps": 24,
            "resolution": "720p",
            "seed": None,
        },
        "self_critique": {
            "risks": ["keeper motion may drift"],
            "fallback_strategy": "strengthen the shot trajectory description",
        },
    }


class VeoPromptContractTest(unittest.TestCase):
    def test_typed_brief_builds_directable_prompt(self) -> None:
        brief = VeoBrief.model_validate(sample_brief_payload())

        prompt = build_veo_prompt(brief)

        self.assertIn("SCENE:", prompt)
        self.assertIn("CONTINUITY:", prompt)
        self.assertIn("WHAT ACTUALLY HAPPENED (do NOT show this):", prompt)
        self.assertIn("WHAT IF (show this instead):", prompt)
        self.assertIn("AVOID:", prompt)
        self.assertLessEqual(len(prompt), 4099)

    def test_legacy_selected_frame_uri_is_coerced_to_id(self) -> None:
        payload = sample_brief_payload()
        payload["selected_reference_frames"] = [
            {"uri": "rf_001_1000", "role": "pre_change_frame", "pts_ms": 1000}
        ]

        brief = VeoBrief.model_validate(payload)

        self.assertEqual(brief.selected_reference_frames[0].id, "rf_001_1000")


if __name__ == "__main__":
    unittest.main()
