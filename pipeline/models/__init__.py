"""Typed pipeline models grouped by domain concern.

Best practice here is not "one file per class", but "one module per bounded
context". The package keeps the public import surface flat via re-exports while
the implementation stays separated by pipeline stage.
"""

from pipeline.models.animator import AnimatorInput, AnimatorOutput, ClipManifest, Keyframe, PartNote
from pipeline.models.director import Act, Choice, DirectorInput, DirectorOutput
from pipeline.models.drawing import DrawingInput, DrawingOutput
from pipeline.models.episode import Episode, EpisodeAct, EpisodeChoice, EpisodeClips
from pipeline.models.renderer import RendererInput, RendererOutput, SvgClip
from pipeline.models.shared import (
    OBSTACLE_SLUG_PATTERN,
    ActionType,
    CreativeNote,
    CreativePhrase,
    ExpressionState,
    LinaiPartId,
    ObstacleSlug,
    ValidationResult,
)

__all__ = [
    "ActionType",
    "Act",
    "AnimatorInput",
    "AnimatorOutput",
    "Choice",
    "ClipManifest",
    "CreativeNote",
    "CreativePhrase",
    "DirectorInput",
    "DirectorOutput",
    "DrawingInput",
    "DrawingOutput",
    "Episode",
    "EpisodeAct",
    "EpisodeChoice",
    "EpisodeClips",
    "ExpressionState",
    "Keyframe",
    "LinaiPartId",
    "OBSTACLE_SLUG_PATTERN",
    "ObstacleSlug",
    "PartNote",
    "RendererInput",
    "RendererOutput",
    "SvgClip",
    "ValidationResult",
]
