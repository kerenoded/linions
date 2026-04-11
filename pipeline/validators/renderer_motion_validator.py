"""Deterministic motion checks for rendered SVG clips.

These checks catch stale v1 humanoid targets and ensure grounded ecto-cloud
travel still shows visible body motion instead of a frozen character.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from pipeline import config
from pipeline.models import ClipManifest, ValidationResult
from pipeline.validators.renderer_motion_shared import (
    TRAVEL_MOTION_IDS,
    collect_body_detached_linai_ids,
    collect_excessive_body_scale_values,
    collect_excessive_eye_motion_targets,
    collect_excessive_root_downward_translate_values,
    collect_eye_socket_translate_targets,
    collect_missing_eye_socket_wrappers,
    collect_unsupported_linai_animation_targets,
    collect_unsupported_linai_ids,
    has_animation_for_id,
    requires_grounded_locomotion,
)


def validate_renderer_motion(*, svg: str, clip: ClipManifest) -> ValidationResult:
    """Validate that rendered motion matches the ecto-cloud Linai model.

    Args:
        svg: One rendered scene SVG.
        clip: The matching clip manifest that describes expected movement.

    Returns:
        ``ValidationResult`` describing whether the motion checks passed.
    """
    if svg is None:
        msg = "svg cannot be None"
        raise TypeError(msg)
    if clip is None:
        msg = "clip cannot be None"
        raise TypeError(msg)

    try:
        root = ET.fromstring(svg)
    except ET.ParseError as exc:
        return ValidationResult(is_valid=False, errors=[f"malformed svg xml: {exc}"])

    errors: list[str] = []

    # Rule: rendered scene SVGs may only contain the supported v2 Linai ids so
    # stale humanoid parts are rejected immediately.
    for invalid_id in collect_unsupported_linai_ids(root):
        errors.append(f'renderer svg must not include unsupported Linai element id="{invalid_id}"')

    # Rule: animation href targets must also stay within the supported v2 ids,
    # otherwise the renderer may still be trying to animate removed body parts.
    for invalid_target in collect_unsupported_linai_animation_targets(root):
        errors.append(
            f'renderer svg must not animate unsupported Linai element id="{invalid_target}"'
        )

    # Rule: the expressive face and internal effects must live under
    # `linai-body` so any body squash/stretch keeps the face anchored.
    for detached_id in collect_body_detached_linai_ids(root):
        errors.append(
            f'renderer svg must keep "{detached_id}" nested inside "linai-body"'
        )

    # Rule: eye sockets themselves must stay planted on the face. Gaze acting
    # can move inner shapes, but translating the whole eye group detaches it.
    for eye_id in collect_eye_socket_translate_targets(root):
        errors.append(f'renderer svg must not translate eye group id="{eye_id}"')

    # Rule: eye contents must stay clipped to the eye socket wrapper so dark
    # iris and pupil shapes cannot visibly spill outside the whites.
    for eye_id in collect_missing_eye_socket_wrappers(root):
        errors.append(
            f'renderer svg must keep clipped eye socket wrapper for id="{eye_id}"'
        )

    # Rule: inner eye acting should stay subtle. Large drifts, spins, or
    # per-shape scale transforms make the socket layers read as detached.
    for eye_id in collect_excessive_eye_motion_targets(root):
        errors.append(
            f'renderer svg must keep eye interior motion subtle for id="{eye_id}"'
        )

    # Rule: the whole character may rise for airborne beats, but downward root
    # translate must stay bounded or Linai sinks below the 200px scene.
    # Fail clips allow a larger dip for a dramatic collision reaction.
    root_translate_max_y = (
        config.RENDERER_FAIL_ROOT_TRANSLATE_MAX_Y_PX
        if clip.branch == "fail"
        else config.RENDERER_ROOT_TRANSLATE_MAX_Y_PX
    )
    for y_value in collect_excessive_root_downward_translate_values(
        root, max_y_px=root_translate_max_y
    ):
        errors.append(
            "renderer svg must not translate #linai downward past "
            f"y={root_translate_max_y}: {y_value:g}"
        )

    # Rule: Linai may squash or stretch a little, but large body scale swings
    # make her silhouette reform too aggressively between beats.
    # Fail clips allow a larger stretch ceiling for a dramatic impact reaction.
    body_scale_max = (
        config.RENDERER_FAIL_BODY_SCALE_MAX
        if clip.branch == "fail"
        else config.RENDERER_BODY_SCALE_MAX
    )
    for x_value, y_value in collect_excessive_body_scale_values(
        root, scale_min=config.RENDERER_BODY_SCALE_MIN, scale_max=body_scale_max
    ):
        errors.append(
            "renderer svg must keep linai-body scale within "
            f"{config.RENDERER_BODY_SCALE_MIN:g}-{body_scale_max:g}: "
            f"{x_value:g} {y_value:g}"
        )

    # Rule: meaningful grounded travel must visibly move the ecto-cloud body or
    # its vapor mass, rather than reading as a frozen character.
    if requires_grounded_locomotion(clip) and not any(
        has_animation_for_id(root, element_id) for element_id in TRAVEL_MOTION_IDS
    ):
        errors.append(
            "grounded travel clip must visibly animate linai, linai-body, "
            "linai-trails, or linai-particles"
        )

    return ValidationResult(is_valid=not errors, errors=errors)
