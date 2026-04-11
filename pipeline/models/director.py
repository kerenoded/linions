"""Director-stage models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from pipeline.models.shared import ObstacleSlug


class Choice(BaseModel):
    """One choice button presented to the viewer at an obstacle."""

    model_config = ConfigDict(extra="forbid")

    label: str
    is_winning: bool
    outcome_description: str


class Act(BaseModel):
    """One obstacle act in an episode script."""

    model_config = ConfigDict(extra="forbid")

    act_index: int
    obstacle_type: ObstacleSlug
    approach_description: str
    choices: list[Choice]
    drawing_prompt: str | None = None
    background_drawing_prompt: str


class DirectorInput(BaseModel):
    """Full input package handed to the Director agent."""

    model_config = ConfigDict(extra="forbid")

    prompt: str
    username: str
    job_id: str
    session_id: str
    rag_context: str
    preferred_obstacle_library_names: list[str]


class DirectorOutput(BaseModel):
    """Story script produced by the Director agent."""

    model_config = ConfigDict(extra="forbid")

    title: str
    description: str
    acts: list[Act]
