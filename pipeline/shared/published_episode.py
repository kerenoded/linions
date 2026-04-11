"""Validation helpers for repo-managed published episode artifacts."""

from __future__ import annotations

import re

from pydantic import ValidationError

from pipeline.models.episode import Episode
from pipeline.validators.svg_linter import validate_and_sanitise_svg

PUBLISH_PATH_SEGMENT_PATTERN = r"^[A-Za-z0-9._-]+$"
_PUBLISH_PATH_SEGMENT_RE = re.compile(PUBLISH_PATH_SEGMENT_PATTERN)

# Published clips are rendered full-scene SVGs, so the public viewer expects the
# complete Linai element set plus one embedded obstacle instance in every clip.
PUBLISHED_SCENE_REQUIRED_IDS = {
    "linai",
    "linai-body",
    "linai-eye-left",
    "linai-eye-right",
    "linai-mouth",
    "linai-inner-patterns",
    "linai-particles",
    "linai-trails",
    "obstacle-root",
    "obstacle-main",
    "obstacle-animated-part",
}


def validate_publish_path_segment(value: str, *, field_name: str) -> str:
    """Validate one username/UUID segment used in repo-managed episode paths.

    Args:
        value: Raw path-segment candidate.
        field_name: Human-readable field label used in error messages.

    Returns:
        Stripped path-safe segment.

    Raises:
        ValueError: If the segment is empty or contains unsafe path characters.
    """
    stripped = value.strip()
    if stripped == "":
        msg = f"{field_name} must be non-empty"
        raise ValueError(msg)
    if not _PUBLISH_PATH_SEGMENT_RE.fullmatch(stripped):
        msg = (
            f"{field_name} must contain only letters, numbers, dot, underscore, or hyphen: "
            f"{value!r}"
        )
        raise ValueError(msg)
    return stripped


def validate_published_episode_json(raw_json: str) -> Episode:
    """Validate a published episode JSON payload and every embedded SVG clip.

    Args:
        raw_json: Serialized episode JSON payload.

    Returns:
        Parsed and validated ``Episode`` model.

    Raises:
        TypeError: If ``raw_json`` is ``None``.
        ValueError: If the episode schema, path metadata, or any embedded SVG is invalid.
    """
    if raw_json is None:
        msg = "raw_json cannot be None"
        raise TypeError(msg)

    try:
        episode = Episode.model_validate_json(raw_json)
    except ValidationError as error:
        msg = f"episode JSON failed schema validation: {error}"
        raise ValueError(msg) from error

    validate_publish_path_segment(episode.username, field_name="username")
    validate_publish_path_segment(episode.uuid, field_name="uuid")

    errors: list[str] = []
    for act in episode.acts:
        errors.extend(
            _validate_published_scene_svg(
                svg=act.clips.approach,
                label=f"act {act.act_index} approach clip",
            )
        )
        for choice in act.clips.choices:
            if choice.win_clip is not None:
                errors.extend(
                    _validate_published_scene_svg(
                        svg=choice.win_clip,
                        label=f"act {act.act_index} choice {choice.choice_index} winClip",
                    )
                )
            if choice.fail_clip is not None:
                errors.extend(
                    _validate_published_scene_svg(
                        svg=choice.fail_clip,
                        label=f"act {act.act_index} choice {choice.choice_index} failClip",
                    )
                )

    if errors:
        msg = "; ".join(errors)
        raise ValueError(msg)

    return episode


def _validate_published_scene_svg(*, svg: str, label: str) -> list[str]:
    """Return prefixed SVG validation errors for one published scene clip."""
    validation_result, _ = validate_and_sanitise_svg(
        svg,
        required_ids=PUBLISHED_SCENE_REQUIRED_IDS,
    )
    if validation_result.is_valid:
        return []
    return [f"{label} {error}" for error in validation_result.errors]
