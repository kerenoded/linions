"""Renderer-stage models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from pipeline.models.animator import ClipManifest


class RendererInput(BaseModel):
    """Full input package handed to the Renderer agent."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    session_id: str
    clips: list[ClipManifest]
    character_template_id: str = "linai-v2"


class SvgClip(BaseModel):
    """One rendered SVG animation clip produced by the Renderer."""

    model_config = ConfigDict(extra="forbid")

    act_index: int
    branch: Literal["approach", "win", "fail"]
    choice_index: int | None
    svg: str
    duration_ms: int


class RendererOutput(BaseModel):
    """Full set of rendered SVG clips for the episode."""

    model_config = ConfigDict(extra="forbid")

    clips: list[SvgClip]
