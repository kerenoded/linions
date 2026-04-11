"""Episode artifact models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pipeline.models.shared import ObstacleSlug


class EpisodeChoice(BaseModel):
    """One choice branch as stored in the episode JSON file."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    choice_index: int = Field(alias="choiceIndex")
    label: str
    is_winning: bool = Field(alias="isWinning")
    outcome_text: str = Field(alias="outcomeText")
    win_clip: str | None = Field(alias="winClip")
    fail_clip: str | None = Field(alias="failClip")

    @model_validator(mode="after")
    def validate_clip_nullability(self) -> EpisodeChoice:
        """Enforce that win/fail clip presence matches the winning flag."""
        if self.is_winning:
            if self.win_clip is None:
                msg = "Winning choice must include winClip"
                raise ValueError(msg)
            if self.fail_clip is not None:
                msg = "Winning choice must set failClip to null"
                raise ValueError(msg)
        else:
            if self.fail_clip is None:
                msg = "Losing choice must include failClip"
                raise ValueError(msg)
            if self.win_clip is not None:
                msg = "Losing choice must set winClip to null"
                raise ValueError(msg)
        return self


class EpisodeClips(BaseModel):
    """SVG clip container for one act in the episode JSON."""

    model_config = ConfigDict(extra="forbid")

    approach: str
    choices: list[EpisodeChoice]


class EpisodeAct(BaseModel):
    """One act as stored in the episode JSON file."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    act_index: int = Field(alias="actIndex")
    obstacle_type: ObstacleSlug = Field(alias="obstacleType")
    approach_text: str = Field(alias="approachText")
    clips: EpisodeClips


class Episode(BaseModel):
    """Root schema for a complete episode JSON file."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: Literal["1.0"] = Field(alias="schemaVersion")
    uuid: str
    username: str
    title: str
    description: str
    generated_at: str = Field(alias="generatedAt")
    content_hash: str = Field(alias="contentHash")
    act_count: int = Field(alias="actCount")
    acts: list[EpisodeAct]

    @model_validator(mode="after")
    def validate_username_non_empty(self) -> Episode:
        """Ensure username is present and non-empty."""
        if self.username.strip() == "":
            msg = "username must be non-empty"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def validate_act_count_matches_acts(self) -> Episode:
        """Ensure the act-count metadata matches the acts array length."""
        if self.act_count != len(self.acts):
            msg = f"actCount ({self.act_count}) does not match number of acts ({len(self.acts)})"
            raise ValueError(msg)
        return self
