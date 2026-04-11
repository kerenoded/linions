"""Drawing-stage models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from pipeline.models.shared import ObstacleSlug


class DrawingInput(BaseModel):
    """Full input package handed to the Drawing agent."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    session_id: str
    obstacle_type: ObstacleSlug
    drawing_prompt: str
    drawing_type: Literal["obstacle", "background"] = "obstacle"


class DrawingOutput(BaseModel):
    """Standalone SVG returned by the Drawing agent."""

    model_config = ConfigDict(extra="forbid")

    svg: str
