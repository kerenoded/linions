"""Shared model types and validator result models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from pydantic import StringConstraints

OBSTACLE_SLUG_PATTERN = r"^[a-z0-9-]+$"
ObstacleSlug = Annotated[str, StringConstraints(min_length=1, pattern=OBSTACLE_SLUG_PATTERN)]
CreativePhrase = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
]
CreativeNote = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=240),
]
LinaiPartId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
]

ExpressionState = CreativePhrase
ActionType = CreativePhrase


@dataclass
class ValidationResult:
    """Outcome of a deterministic validator call."""

    is_valid: bool
    errors: list[str]
