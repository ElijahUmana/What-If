# Veo brief schema (the structured prompt body)

```json
{
  "selected_reference_frames": [
    { "id": "rf_001_1452045", "role": "pre_change_frame", "pts_ms": 1452045 },
    { "id": "rf_002_1452545", "role": "camera_angle_lock", "pts_ms": 1452545 },
    { "id": "rf_000_1451045", "role": "stadium_lighting_ref", "pts_ms": 1451045 }
  ],

  "scene": {
    "stadium": "string",
    "stadium_dressing": "string — visible signage, sponsor boards",
    "weather": "clear | overcast | rain | floodlights_only | indoor",
    "lighting": "daylight | dusk | floodlights | mixed",
    "crowd_density": "full | mostly_full | half | sparse"
  },

  "continuity": {
    "home": { "name": "string", "kit_color_primary": "string", "kit_color_secondary": "string", "gk_kit_color": "string" },
    "away": { "name": "string", "kit_color_primary": "string", "kit_color_secondary": "string", "gk_kit_color": "string" },
    "referee_kit": "string",
    "scoreboard_overlay": "string — describe its position and style as seen in reference frames",
    "broadcaster_chrome": "string — lower-third style or absence"
  },

  "real_event": {
    "anchor_pts_ms": 1452045,
    "event_type": "string from event enum",
    "actors": [ { "role": "string", "team": "home|away", "jersey_number": "integer_or_null" } ],
    "description": "string — directable language"
  },

  "counterfactual_delta": {
    "moment_of_divergence_ms": 1452045,
    "user_prompt_verbatim": "string",
    "beat_description": "string — one sentence in directable language"
  },

  "continuation_beats": [
    { "duration_s": 2, "description": "string" },
    { "duration_s": 3, "description": "string" },
    { "duration_s": 3, "description": "string" }
  ],

  "audio": {
    "crowd": "string",
    "broadcaster_voiceover": "string_or_null — only with confirmed player names",
    "ambient": "string"
  },

  "camera": {
    "persona": "broadcast_wide_angle | tight_follow | overhead | replay_slow_mo",
    "movement": "string",
    "no_graphics_overlay": true
  },

  "negative": [
    "do not change kit colours",
    "do not change player positions before the divergence moment",
    "do not introduce graphical overlays different from the reference",
    "do not show celebrations for events that did not happen",
    "no replay-style slow motion"
  ],

  "model_params": {
    "duration_s": 8,
    "fps": 24,
    "resolution": "1280x720",
    "seed": null
  },

  "self_critique": {
    "risks": ["string"],
    "fallback_strategy": "string"
  }
}
```
