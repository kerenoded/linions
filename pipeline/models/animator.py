"""Animator-stage models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from pipeline.models.director import Act
from pipeline.models.shared import (
    ActionType,
    CreativeNote,
    ExpressionState,
    LinaiPartId,
    ObstacleSlug,
)


class AnimatorInput(BaseModel):
    """Full input package handed to the Animator agent."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    session_id: str
    acts: list[Act]
    walk_duration_seconds: int
    canvas_width: int
    canvas_height: int
    ground_line_y: int
    handoff_character_x: int
    requires_handoff_in: bool = False
    requires_handoff_out: bool = False


class Keyframe(BaseModel):
    """A single timestamped pose snapshot within a clip."""

    model_config = ConfigDict(extra="forbid")

    time_ms: int
    character_x: float
    character_y: float
    support_y: float
    is_grounded: bool
    is_handoff_pose: bool = False
    expression: ExpressionState
    action: ActionType
    motion_note: CreativeNote | None = None
    part_notes: list[PartNote] = Field(default_factory=list)


class PartNote(BaseModel):
    """One expressive note targeted at a specific Linai SVG element id."""

    model_config = ConfigDict(extra="forbid")

    target_id: LinaiPartId
    note: CreativeNote


class ClipManifest(BaseModel):
    """Animator's specification for one animated clip segment."""

    model_config = ConfigDict(extra="forbid")

    act_index: int
    obstacle_type: ObstacleSlug
    branch: Literal["approach", "win", "fail"]
    choice_index: int | None
    duration_ms: int
    keyframes: list[Keyframe]
    obstacle_x: float
    obstacle_svg_override: str | None = None
    background_svg: str | None = None  # Full-canvas background SVG, populated by orchestrator
    background_slug: str | None = None  # Background library slug or generated id


class AnimatorOutput(BaseModel):
    """Full keyframe choreography for all clips in the episode."""

    model_config = ConfigDict(extra="forbid")

    clips: list[ClipManifest]
