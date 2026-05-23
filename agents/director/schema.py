"""Typed contracts for DirectorAgent and Veo prompt generation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReferenceFrame(BaseModel):
    """A captured frame available to the Director and Veo generator."""

    id: str
    pts_ms: int
    role_hint: str
    jpeg_bytes: bytes = Field(repr=False)

    def metadata(self) -> dict[str, Any]:
        return self.model_dump(exclude={"jpeg_bytes"})


class SelectedReferenceFrame(BaseModel):
    id: str
    role: str
    pts_ms: int | None = None


class SceneBrief(BaseModel):
    stadium: str
    stadium_dressing: str
    weather: str
    lighting: str
    crowd_density: str


class TeamContinuity(BaseModel):
    name: str
    kit_color_primary: str
    kit_color_secondary: str = ""
    gk_kit_color: str = ""


class ContinuityBrief(BaseModel):
    home: TeamContinuity
    away: TeamContinuity
    referee_kit: str = ""
    scoreboard_overlay: str = ""
    broadcaster_chrome: str = ""


class ActorBrief(BaseModel):
    role: str
    team: str = ""
    jersey_number: int | None = None


class RealEventBrief(BaseModel):
    anchor_pts_ms: int
    event_type: str
    actors: list[ActorBrief] = Field(default_factory=list)
    description: str


class CounterfactualDelta(BaseModel):
    moment_of_divergence_ms: int
    user_prompt_verbatim: str
    beat_description: str


class ContinuationBeat(BaseModel):
    duration_s: int
    description: str


class AudioBrief(BaseModel):
    crowd: str
    broadcaster_voiceover: str | None = None
    ambient: str


class CameraBrief(BaseModel):
    persona: str
    movement: str
    no_graphics_overlay: bool = True


class ModelParams(BaseModel):
    duration_s: int = 8
    fps: int = 24
    resolution: str = "720p"
    seed: int | None = None

    @field_validator("duration_s")
    @classmethod
    def require_supported_duration(cls, value: int) -> int:
        if value != 8:
            raise ValueError("duration_s must be 8 for reference-image Veo clips")
        return value


class SelfCritique(BaseModel):
    risks: list[str] = Field(default_factory=list)
    fallback_strategy: str = ""


class VeoBrief(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    selected_reference_frames: list[SelectedReferenceFrame]
    scene: SceneBrief
    continuity: ContinuityBrief
    real_event: RealEventBrief
    counterfactual_delta: CounterfactualDelta
    continuation_beats: list[ContinuationBeat]
    audio: AudioBrief
    camera: CameraBrief
    negative: list[str]
    model_params: ModelParams = Field(default_factory=ModelParams)
    self_critique: SelfCritique = Field(default_factory=SelfCritique)

    @field_validator("selected_reference_frames", mode="before")
    @classmethod
    def coerce_selected_reference_frames(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value

        coerced = []
        for item in value:
            if isinstance(item, dict) and "id" not in item and "uri" in item:
                item = {**item, "id": item["uri"]}
            coerced.append(item)
        return coerced

    @field_validator("selected_reference_frames")
    @classmethod
    def require_selected_reference_frames(
        cls, value: list[SelectedReferenceFrame]
    ) -> list[SelectedReferenceFrame]:
        if not value:
            raise ValueError("selected_reference_frames must include at least one frame")
        return value

    @field_validator("continuation_beats")
    @classmethod
    def require_continuation_beats(
        cls, value: list[ContinuationBeat]
    ) -> list[ContinuationBeat]:
        if not value:
            raise ValueError("continuation_beats must include at least one beat")
        return value
