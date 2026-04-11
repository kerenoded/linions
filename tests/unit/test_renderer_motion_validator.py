"""Unit tests for deterministic renderer motion validation."""

from __future__ import annotations

import pytest

from pipeline import config
from pipeline.models import ClipManifest, Keyframe
from pipeline.validators.renderer_motion_repairs import (
    repair_renderer_body_scale,
    repair_renderer_eye_motion,
    repair_renderer_fail_translate,
    repair_renderer_root_translate,
    repair_renderer_unsupported_animation_targets,
)
from pipeline.validators.renderer_motion_validator import (
    validate_renderer_motion,
)


def _clip(*, start_x: float, end_x: float, branch: str = "approach") -> ClipManifest:
    return ClipManifest(
        act_index=0,
        obstacle_type="wall",
        branch=branch,
        choice_index=None if branch == "approach" else 0,
        duration_ms=4000,
        obstacle_x=400,
        keyframes=[
            Keyframe(
                time_ms=0,
                character_x=start_x,
                character_y=160,
                support_y=160,
                is_grounded=True,
                expression="calm",
                action="floating in",
            ),
            Keyframe(
                time_ms=4000,
                character_x=end_x,
                character_y=160,
                support_y=160,
                is_grounded=True,
                expression="brave",
                action="steady hover",
            ),
        ],
    )


def _anchored_linai_svg(
    *,
    eye_left_markup: str = '<ellipse cx="92" cy="80" rx="8" ry="10"/>',
    eye_right_markup: str = '<ellipse cx="116" cy="78" rx="9" ry="11"/>',
    mouth_markup: str = '<path d="M104 102 Q112 108 120 103"/>',
    inner_patterns_markup: str = '<path d="M88 84 Q100 74 112 82"/>',
    particles_markup: str = '<circle cx="100" cy="92" r="2"/>',
    trails_markup: str = (
        '<path d="M92 118 Q88 136 84 154"/>'
        '<animateTransform attributeName="transform" type="scale" '
        'values="1 1;1.08 0.94;1 1" dur="1s" repeatCount="indefinite"/>'
    ),
    extra_linai_markup: str = "",
) -> str:
    return (
        '<svg viewBox="0 0 800 200">'
        '<g id="linai">'
        '<g id="linai-body">'
        '<ellipse cx="104" cy="90" rx="34" ry="28"/>'
        '<g id="linai-eye-left">'
        '<g data-eye-socket-wrapper="true" clip-path="url(#cloud-eye-left-clip)">'
        f"{eye_left_markup}"
        "</g>"
        "</g>"
        '<g id="linai-eye-right">'
        '<g data-eye-socket-wrapper="true" clip-path="url(#cloud-eye-right-clip)">'
        f"{eye_right_markup}"
        "</g>"
        "</g>"
        f'<g id="linai-mouth">{mouth_markup}</g>'
        f'<g id="linai-inner-patterns">{inner_patterns_markup}</g>'
        f'<g id="linai-particles">{particles_markup}</g>'
        "</g>"
        f'<g id="linai-trails">{trails_markup}</g>'
        f"{extra_linai_markup}"
        "</g>"
        "</svg>"
    )


def test_validate_renderer_motion_passes_when_grounded_travel_is_small() -> None:
    svg = '<svg viewBox="0 0 800 200"><g id="linai"/></svg>'

    result = validate_renderer_motion(svg=svg, clip=_clip(start_x=300, end_x=310))

    assert result.is_valid is True
    assert result.errors == []


def test_validate_renderer_motion_rejects_removed_v1_humanoid_ids() -> None:
    svg = (
        '<svg viewBox="0 0 800 200">'
        '<g id="linai-leg-left-group"><path id="linai-leg-left" d="M0 0"/>'
        '<path id="linai-feet-left" d="M0 0"/></g>'
        '<g id="linai-leg-right-group"><path id="linai-leg-right" d="M0 0"/>'
        '<path id="linai-feet-right" d="M0 0"/></g>'
        "</svg>"
    )

    result = validate_renderer_motion(svg=svg, clip=_clip(start_x=40, end_x=320))

    assert result.is_valid is False
    assert any("linai-leg-left-group" in error for error in result.errors)
    assert any("linai-leg-right-group" in error for error in result.errors)


def test_validate_renderer_motion_passes_when_grounded_travel_animates_v2_vapor_parts() -> None:
    svg = _anchored_linai_svg()

    result = validate_renderer_motion(svg=svg, clip=_clip(start_x=40, end_x=320))

    assert result.is_valid is True
    assert result.errors == []


def test_validate_renderer_motion_allows_symbol_ids_nested_inside_inner_patterns() -> None:
    svg = _anchored_linai_svg(
        inner_patterns_markup=(
            '<g id="linai-inner-patterns-sparkles">'
            '<path d="M88 84 Q100 74 112 82"/>'
            '<animate attributeName="opacity" values="0;1;0" dur="1s" repeatCount="indefinite"/>'
            "</g>"
            '<g id="linai-inner-patterns-ellipsis">'
            '<circle cx="100" cy="92" r="2"/>'
            "</g>"
        )
    )

    result = validate_renderer_motion(svg=svg, clip=_clip(start_x=40, end_x=320))

    assert result.is_valid is True
    assert result.errors == []


def test_validate_renderer_motion_allows_shorter_inner_symbol_ids_nested_inside_inner_patterns(
) -> None:
    svg = _anchored_linai_svg(
        inner_patterns_markup=(
            '<g id="linai-inner-sparkles">'
            '<path d="M88 84 Q100 74 112 82"/>'
            '<animate attributeName="opacity" values="0;1;0" dur="1s" repeatCount="indefinite"/>'
            "</g>"
            '<g id="linai-inner-exclaim">'
            '<path d="M100 78 L100 92"/>'
            "</g>"
        )
    )

    result = validate_renderer_motion(svg=svg, clip=_clip(start_x=40, end_x=320))

    assert result.is_valid is True
    assert result.errors == []


def test_validate_renderer_motion_allows_mouth_child_ids_nested_inside_mouth() -> None:
    svg = _anchored_linai_svg(
        mouth_markup=(
            '<path id="linai-mouth-path" d="M104 102 Q112 108 120 103">'
            '<animate attributeName="d" '
            'values="M104 102 Q112 108 120 103;M104 102 Q112 111 121 102;'
            'M104 102 Q112 108 120 103" dur="1s" repeatCount="indefinite"/>'
            "</path>"
        )
    )

    result = validate_renderer_motion(svg=svg, clip=_clip(start_x=40, end_x=320))

    assert result.is_valid is True
    assert result.errors == []


def test_validate_renderer_motion_rejects_inner_patterns_prefixed_id_outside_group() -> None:
    svg = _anchored_linai_svg(
        extra_linai_markup='<g id="linai-inner-patterns-sparkles"><path d="M0 0"/></g>'
    )

    result = validate_renderer_motion(svg=svg, clip=_clip(start_x=40, end_x=320))

    assert result.is_valid is False
    assert any("linai-inner-patterns-sparkles" in error for error in result.errors)


def test_validate_renderer_motion_rejects_mouth_prefixed_id_outside_mouth() -> None:
    svg = _anchored_linai_svg(
        extra_linai_markup='<path id="linai-mouth-path" d="M104 102 Q112 108 120 103"/>'
    )

    result = validate_renderer_motion(svg=svg, clip=_clip(start_x=40, end_x=320))

    assert result.is_valid is False
    assert any("linai-mouth-path" in error for error in result.errors)


def test_validate_renderer_motion_rejects_body_detached_face_layers() -> None:
    svg = (
        '<svg viewBox="0 0 800 200">'
        '<g id="linai">'
        '<g id="linai-body"><ellipse cx="104" cy="90" rx="34" ry="28"/></g>'
        '<g id="linai-eye-left"><ellipse cx="92" cy="80" rx="8" ry="10"/></g>'
        '<g id="linai-eye-right"><ellipse cx="116" cy="78" rx="9" ry="11"/></g>'
        '<g id="linai-mouth"><path d="M104 102 Q112 108 120 103"/></g>'
        '<g id="linai-inner-patterns"><path d="M88 84 Q100 74 112 82"/></g>'
        '<g id="linai-particles"><circle cx="100" cy="92" r="2"/></g>'
        '<g id="linai-trails"><path d="M92 118 Q88 136 84 154"/>'
        '<animateTransform attributeName="transform" type="scale" '
        'values="1 1;1.08 0.94;1 1" dur="1s" repeatCount="indefinite"/>'
        "</g>"
        "</g>"
        "</svg>"
    )

    result = validate_renderer_motion(svg=svg, clip=_clip(start_x=40, end_x=320))

    assert result.is_valid is False
    assert any('"linai-eye-left"' in error for error in result.errors)
    assert any('"linai-mouth"' in error for error in result.errors)


def test_validate_renderer_motion_rejects_whole_eye_group_translate() -> None:
    svg = (
        '<svg viewBox="0 0 800 200">'
        '<g id="linai">'
        '<g id="linai-body">'
        '<ellipse cx="104" cy="90" rx="34" ry="28"/>'
        '<g id="linai-eye-left">'
        '<animateTransform attributeName="transform" type="translate" '
        'values="0 0;8 0;0 0" dur="1s" repeatCount="indefinite"/>'
        '<g data-eye-socket-wrapper="true" clip-path="url(#cloud-eye-left-clip)">'
        '<ellipse cx="92" cy="80" rx="8" ry="10"/>'
        "</g>"
        "</g>"
        '<g id="linai-eye-right">'
        '<g data-eye-socket-wrapper="true" clip-path="url(#cloud-eye-right-clip)">'
        '<ellipse cx="116" cy="78" rx="9" ry="11"/>'
        "</g>"
        "</g>"
        '<g id="linai-mouth"><path d="M104 102 Q112 108 120 103"/></g>'
        '<g id="linai-inner-patterns"><path d="M88 84 Q100 74 112 82"/></g>'
        '<g id="linai-particles"><circle cx="100" cy="92" r="2"/></g>'
        "</g>"
        '<g id="linai-trails"><path d="M92 118 Q88 136 84 154"/>'
        '<animateTransform attributeName="transform" type="scale" '
        'values="1 1;1.08 0.94;1 1" dur="1s" repeatCount="indefinite"/>'
        "</g>"
        "</g>"
        "</svg>"
    )

    result = validate_renderer_motion(svg=svg, clip=_clip(start_x=40, end_x=320))

    assert result.is_valid is False
    assert any('eye group id="linai-eye-left"' in error for error in result.errors)


def test_validate_renderer_motion_rejects_excessive_root_downward_translate() -> None:
    svg = _anchored_linai_svg(
        extra_linai_markup=(
            '<animateTransform href="#linai" attributeName="transform" type="translate" '
            'values="40 0;120 18;170 0" dur="1s" repeatCount="indefinite"/>'
        )
    )

    result = validate_renderer_motion(svg=svg, clip=_clip(start_x=40, end_x=320))

    assert result.is_valid is False
    assert any(
        f'past y={config.RENDERER_ROOT_TRANSLATE_MAX_Y_PX}' in error
        for error in result.errors
    )


def test_validate_renderer_motion_rejects_missing_eye_socket_wrapper() -> None:
    svg = (
        '<svg viewBox="0 0 800 200">'
        '<g id="linai">'
        '<g id="linai-body">'
        '<ellipse cx="104" cy="90" rx="34" ry="28"/>'
        '<g id="linai-eye-left" clip-path="url(#cloud-body-clip)">'
        '<g><ellipse cx="92" cy="80" rx="8" ry="10"/><circle cx="94" cy="80" r="3"/></g>'
        "</g>"
        '<g id="linai-eye-right" clip-path="url(#cloud-body-clip)">'
        '<g data-eye-socket-wrapper="true" clip-path="url(#cloud-eye-right-clip)">'
        '<ellipse cx="116" cy="78" rx="9" ry="11"/><circle cx="118" cy="78" r="3"/></g>'
        "</g>"
        '<g id="linai-mouth"><path d="M104 102 Q112 108 120 103"/></g>'
        '<g id="linai-inner-patterns"><path d="M88 84 Q100 74 112 82"/></g>'
        '<g id="linai-particles"><circle cx="100" cy="92" r="2"/></g>'
        "</g>"
        '<g id="linai-trails"><path d="M92 118 Q88 136 84 154"/>'
        '<animateTransform attributeName="transform" type="scale" '
        'values="1 1;1.08 0.94;1 1" dur="1s" repeatCount="indefinite"/>'
        "</g>"
        "</g>"
        "</svg>"
    )

    result = validate_renderer_motion(svg=svg, clip=_clip(start_x=40, end_x=320))

    assert result.is_valid is False
    assert any(
        'clipped eye socket wrapper for id="linai-eye-left"' in error
        for error in result.errors
    )


def test_validate_renderer_motion_rejects_excessive_eye_interior_motion() -> None:
    svg = _anchored_linai_svg(
        eye_left_markup=(
            '<ellipse cx="92" cy="80" rx="8" ry="10"/>'
            '<ellipse cx="97" cy="73" rx="7" ry="8.5">'
            '<animate attributeName="cx" values="97;103;97" dur="1s" repeatCount="indefinite"/>'
            "</ellipse>"
        )
    )

    result = validate_renderer_motion(svg=svg, clip=_clip(start_x=40, end_x=320))

    assert result.is_valid is False
    assert any(
        'eye interior motion subtle for id="linai-eye-left"' in error
        for error in result.errors
    )


def test_repair_renderer_eye_motion_removes_excessive_eye_animation() -> None:
    svg = _anchored_linai_svg(
        eye_left_markup=(
            '<ellipse cx="92" cy="80" rx="8" ry="10"/>'
            '<ellipse cx="97" cy="73" rx="7" ry="8.5">'
            '<animate attributeName="cx" values="97;103;97" dur="1s" repeatCount="indefinite"/>'
            "</ellipse>"
        ),
        eye_right_markup=(
            '<ellipse cx="116" cy="78" rx="9" ry="11"/>'
            '<ellipse cx="121" cy="71" rx="7" ry="8.5">'
            '<animate attributeName="cx" values="121;127;121" dur="1s" repeatCount="indefinite"/>'
            "</ellipse>"
        ),
    )

    repaired = repair_renderer_eye_motion(svg)
    result = validate_renderer_motion(svg=repaired, clip=_clip(start_x=40, end_x=320))

    assert result.is_valid is True
    assert result.errors == []


def test_validate_renderer_motion_rejects_partial_eye_scale_transforms() -> None:
    svg = _anchored_linai_svg(
        eye_left_markup=(
            '<ellipse cx="92" cy="80" rx="8" ry="10">'
            '<animateTransform attributeName="transform" type="scale" '
            'values="1 0.55;1 1.35;1 0.9" dur="1s" repeatCount="indefinite"/>'
            "</ellipse>"
            '<ellipse cx="97" cy="73" rx="7" ry="8.5"/>'
        ),
        eye_right_markup=(
            '<ellipse cx="116" cy="78" rx="9" ry="11">'
            '<animateTransform attributeName="transform" type="scale" '
            'values="1 0.55;1 1.4;1 0.9" dur="1s" repeatCount="indefinite"/>'
            "</ellipse>"
            '<ellipse cx="121" cy="71" rx="7" ry="8.5"/>'
        ),
    )

    result = validate_renderer_motion(svg=svg, clip=_clip(start_x=40, end_x=320))

    assert result.is_valid is False
    assert any(
        'eye interior motion subtle for id="linai-eye-left"' in error
        for error in result.errors
    )
    assert any(
        'eye interior motion subtle for id="linai-eye-right"' in error
        for error in result.errors
    )


def test_repair_renderer_eye_motion_removes_partial_eye_scale_transforms() -> None:
    svg = _anchored_linai_svg(
        eye_left_markup=(
            '<ellipse cx="92" cy="80" rx="8" ry="10">'
            '<animateTransform attributeName="transform" type="scale" '
            'values="1 0.55;1 1.35;1 0.9" dur="1s" repeatCount="indefinite"/>'
            "</ellipse>"
            '<ellipse cx="97" cy="73" rx="7" ry="8.5"/>'
        ),
        eye_right_markup=(
            '<ellipse cx="116" cy="78" rx="9" ry="11">'
            '<animateTransform attributeName="transform" type="scale" '
            'values="1 0.55;1 1.4;1 0.9" dur="1s" repeatCount="indefinite"/>'
            "</ellipse>"
            '<ellipse cx="121" cy="71" rx="7" ry="8.5">'
            '<animateTransform attributeName="transform" type="scale" '
            'values="1 0.55;1 1.35;1 0.9" dur="1s" repeatCount="indefinite"/>'
            "</ellipse>"
        ),
    )

    repaired = repair_renderer_eye_motion(svg)
    result = validate_renderer_motion(svg=repaired, clip=_clip(start_x=40, end_x=320))
    eye_section = repaired[
        repaired.index('<g id="linai-eye-left">') : repaired.index('<g id="linai-mouth">')
    ]

    assert "type=\"scale\"" not in eye_section
    assert result.is_valid is True
    assert result.errors == []


def test_repair_renderer_unsupported_animation_targets_removes_css_selector_hrefs() -> None:
    # The model used a CSS-selector-style href that looks like a Linai ID but
    # isn't a real element ID — e.g. "linai-inner-patterns-x text:nth-child(1)".
    invalid_href = "#linai-inner-patterns-questions text:nth-child(1)"
    svg = _anchored_linai_svg(
        extra_linai_markup=(
            f'<animate href="{invalid_href}" attributeName="opacity" '
            'values="0;1;0" dur="1s" repeatCount="indefinite"/>'
        )
    )
    assert "must not animate unsupported" in validate_renderer_motion(
        svg=svg, clip=_clip(start_x=40, end_x=320)
    ).errors[0]

    repaired = repair_renderer_unsupported_animation_targets(svg)
    result = validate_renderer_motion(svg=repaired, clip=_clip(start_x=40, end_x=320))

    assert result.is_valid is True
    assert result.errors == []


def test_validate_renderer_motion_rejects_excessive_body_scale_swings() -> None:
    svg = _anchored_linai_svg(
        extra_linai_markup=(
            '<animateTransform href="#linai-body" attributeName="transform" type="scale" '
            'values="1 1;1.35 0.55;1 1" dur="1s" repeatCount="indefinite"/>'
        )
    )

    result = validate_renderer_motion(svg=svg, clip=_clip(start_x=40, end_x=320))

    assert result.is_valid is False
    assert any("keep linai-body scale within" in error for error in result.errors)


def test_validate_renderer_motion_allows_larger_downward_translate_for_fail_clip() -> None:
    # y=10 exceeds the normal limit (4) but is within the fail limit (25).
    svg = _anchored_linai_svg(
        extra_linai_markup=(
            '<animateTransform href="#linai" attributeName="transform" type="translate" '
            'values="40 0;120 10;170 0" dur="1s" repeatCount="indefinite"/>'
        )
    )

    result = validate_renderer_motion(svg=svg, clip=_clip(start_x=40, end_x=320, branch="fail"))

    assert result.is_valid is True
    assert result.errors == []


def test_validate_renderer_motion_rejects_extreme_downward_translate_even_for_fail_clip() -> None:
    # y=30 exceeds even the relaxed fail limit (25).
    svg = _anchored_linai_svg(
        extra_linai_markup=(
            '<animateTransform href="#linai" attributeName="transform" type="translate" '
            'values="40 0;120 30;170 0" dur="1s" repeatCount="indefinite"/>'
        )
    )

    result = validate_renderer_motion(svg=svg, clip=_clip(start_x=40, end_x=320, branch="fail"))

    assert result.is_valid is False
    assert any(
        f'past y={config.RENDERER_FAIL_ROOT_TRANSLATE_MAX_Y_PX}' in error
        for error in result.errors
    )


def test_validate_renderer_motion_allows_larger_body_scale_for_fail_clip() -> None:
    # scale=1.35 exceeds the normal max (1.2) but is within the fail max (1.5).
    svg = _anchored_linai_svg(
        extra_linai_markup=(
            '<animateTransform href="#linai-body" attributeName="transform" type="scale" '
            'values="1 1;1.35 1.3;1 1" dur="1s" repeatCount="indefinite"/>'
        )
    )

    result = validate_renderer_motion(svg=svg, clip=_clip(start_x=40, end_x=320, branch="fail"))

    assert result.is_valid is True
    assert result.errors == []


def test_validate_renderer_motion_rejects_extreme_body_scale_even_for_fail_clip() -> None:
    # scale=1.6 exceeds even the relaxed fail max (1.5).
    svg = _anchored_linai_svg(
        extra_linai_markup=(
            '<animateTransform href="#linai-body" attributeName="transform" type="scale" '
            'values="1 1;1.6 1.6;1 1" dur="1s" repeatCount="indefinite"/>'
        )
    )

    result = validate_renderer_motion(svg=svg, clip=_clip(start_x=40, end_x=320, branch="fail"))

    assert result.is_valid is False
    assert any("keep linai-body scale within" in error for error in result.errors)


def test_repair_renderer_fail_translate_clamps_extreme_downward_y() -> None:
    # y=100 far exceeds the fail limit (25); repair should clamp it.
    svg = _anchored_linai_svg(
        extra_linai_markup=(
            '<animateTransform href="#linai" attributeName="transform" type="translate" '
            'values="40 0;120 100;170 0" dur="1s" repeatCount="indefinite"/>'
        )
    )

    repaired = repair_renderer_fail_translate(svg)
    result = validate_renderer_motion(
        svg=repaired, clip=_clip(start_x=40, end_x=320, branch="fail")
    )

    assert result.is_valid is True
    assert result.errors == []


def test_repair_renderer_fail_translate_preserves_acceptable_values() -> None:
    # y=10 is within the fail limit; repair should leave it unchanged.
    svg = _anchored_linai_svg(
        extra_linai_markup=(
            '<animateTransform href="#linai" attributeName="transform" type="translate" '
            'values="40 0;120 10;170 0" dur="1s" repeatCount="indefinite"/>'
        )
    )

    repaired = repair_renderer_fail_translate(svg)

    assert "120 10" in repaired


def test_repair_renderer_root_translate_clamps_approach_clip() -> None:
    # y=30 far exceeds the approach limit (4); repair should clamp it to 4.
    svg = _anchored_linai_svg(
        extra_linai_markup=(
            '<animateTransform href="#linai" attributeName="transform" type="translate" '
            'values="40 0;120 30;170 0" dur="1s" repeatCount="indefinite"/>'
        )
    )

    repaired = repair_renderer_root_translate(
        svg, max_y_px=config.RENDERER_ROOT_TRANSLATE_MAX_Y_PX
    )
    result = validate_renderer_motion(
        svg=repaired, clip=_clip(start_x=40, end_x=170, branch="approach")
    )

    assert result.is_valid is True
    assert result.errors == []


def test_repair_renderer_body_scale_clamps_out_of_range_values() -> None:
    # scale 0.7/1.45 violates the 0.8-1.2 limit; repair should clamp to range.
    svg = _anchored_linai_svg(
        extra_linai_markup=(
            '<animateTransform href="#linai-body" attributeName="transform" type="scale" '
            'values="1 1;0.7 0.7;1.45 1.45;1 1" dur="1s" repeatCount="indefinite"/>'
        )
    )

    repaired = repair_renderer_body_scale(
        svg,
        scale_min=config.RENDERER_BODY_SCALE_MIN,
        scale_max=config.RENDERER_BODY_SCALE_MAX,
    )
    result = validate_renderer_motion(
        svg=repaired, clip=_clip(start_x=40, end_x=170, branch="win")
    )

    assert result.is_valid is True
    assert result.errors == []


def test_repair_renderer_body_scale_preserves_valid_values() -> None:
    # scale 0.9/1.1 is within range; values should be unchanged.
    svg = _anchored_linai_svg(
        extra_linai_markup=(
            '<animateTransform href="#linai-body" attributeName="transform" type="scale" '
            'values="1 1;0.9 0.9;1.1 1.1;1 1" dur="1s" repeatCount="indefinite"/>'
        )
    )

    repaired = repair_renderer_body_scale(
        svg,
        scale_min=config.RENDERER_BODY_SCALE_MIN,
        scale_max=config.RENDERER_BODY_SCALE_MAX,
    )

    assert "0.9 0.9" in repaired
    assert "1.1 1.1" in repaired


# ---------------------------------------------------------------------------
# validate_renderer_motion — None guards and ParseError
# ---------------------------------------------------------------------------


def test_validate_renderer_motion_raises_type_error_for_none_svg() -> None:
    with pytest.raises(TypeError):
        validate_renderer_motion(svg=None, clip=_clip(start_x=40, end_x=170))  # type: ignore[arg-type]


def test_validate_renderer_motion_raises_type_error_for_none_clip() -> None:
    with pytest.raises(TypeError):
        validate_renderer_motion(svg="<svg/>", clip=None)  # type: ignore[arg-type]


def test_validate_renderer_motion_fails_gracefully_for_malformed_xml() -> None:
    result = validate_renderer_motion(svg="<svg>not closed", clip=_clip(start_x=40, end_x=170))

    assert result.is_valid is False
    assert any("malformed svg xml" in err for err in result.errors)


# ---------------------------------------------------------------------------
# repair helpers — edge cases with missing/malformed values attributes
# ---------------------------------------------------------------------------


def test_repair_renderer_root_translate_skips_animation_without_values_attribute() -> None:
    """An animateTransform without a values= attribute should not crash."""
    svg = _anchored_linai_svg(
        extra_linai_markup=(
            '<animateTransform href="#linai" attributeName="transform" type="translate" '
            'from="0 0" to="10 5" dur="1s" repeatCount="indefinite"/>'
        )
    )

    repaired = repair_renderer_root_translate(svg, max_y_px=config.RENDERER_ROOT_TRANSLATE_MAX_Y_PX)

    assert repaired  # should not raise


def test_repair_renderer_root_translate_skips_malformed_pair() -> None:
    """A pair with a non-numeric coordinate should be left unchanged."""
    svg = _anchored_linai_svg(
        extra_linai_markup=(
            '<animateTransform href="#linai" attributeName="transform" type="translate" '
            'values="bad;40 0;120 30" dur="1s" repeatCount="indefinite"/>'
        )
    )

    repaired = repair_renderer_root_translate(svg, max_y_px=config.RENDERER_ROOT_TRANSLATE_MAX_Y_PX)

    assert "bad" in repaired  # the malformed token is left unchanged


def test_repair_renderer_body_scale_skips_animation_without_values_attribute() -> None:
    """An animateTransform without a values= attribute should not crash."""
    svg = _anchored_linai_svg(
        extra_linai_markup=(
            '<animateTransform href="#linai-body" attributeName="transform" type="scale" '
            'from="1 1" to="1.5 1.5" dur="1s" repeatCount="indefinite"/>'
        )
    )

    repaired = repair_renderer_body_scale(
        svg,
        scale_min=config.RENDERER_BODY_SCALE_MIN,
        scale_max=config.RENDERER_BODY_SCALE_MAX,
    )

    assert repaired  # should not raise


def test_repair_renderer_body_scale_skips_malformed_pair() -> None:
    """A non-numeric pair should be left unchanged by body scale repair."""
    svg = _anchored_linai_svg(
        extra_linai_markup=(
            '<animateTransform href="#linai-body" attributeName="transform" type="scale" '
            'values="bad;1 1;2 2" dur="1s" repeatCount="indefinite"/>'
        )
    )

    repaired = repair_renderer_body_scale(
        svg,
        scale_min=config.RENDERER_BODY_SCALE_MIN,
        scale_max=config.RENDERER_BODY_SCALE_MAX,
    )

    assert "bad" in repaired  # malformed token is left unchanged


def test_repair_renderer_eye_motion_removes_excessive_translate_drift() -> None:
    """Eye animateTransform translate exceeding drift limit is removed."""
    eye_with_excessive_drift = (
        '<ellipse cx="92" cy="80" rx="8" ry="10"/>'
        '<animateTransform attributeName="transform" type="translate" '
        f'values="0 0;{config.RENDERER_EYE_DRIFT_MAX_X_PX + 10} 0;0 0" '
        'dur="1s" repeatCount="indefinite"/>'
    )
    svg = _anchored_linai_svg(eye_left_markup=eye_with_excessive_drift)

    repaired = repair_renderer_eye_motion(svg)

    assert "animateTransform" not in repaired.split('id="linai-eye-left"')[1].split(
        'id="linai-eye-right"'
    )[0]


def test_repair_renderer_eye_motion_removes_excessive_rotate() -> None:
    """Eye animateTransform rotate exceeding rotation limit is removed."""
    eye_with_excessive_rotate = (
        '<ellipse cx="92" cy="80" rx="8" ry="10"/>'
        '<animateTransform attributeName="transform" type="rotate" '
        f'values="0;{config.RENDERER_EYE_ROTATE_MAX_DEGREES + 10};0" '
        'dur="1s" repeatCount="indefinite"/>'
    )
    svg = _anchored_linai_svg(eye_left_markup=eye_with_excessive_rotate)

    repaired = repair_renderer_eye_motion(svg)

    assert "animateTransform" not in repaired.split('id="linai-eye-left"')[1].split(
        'id="linai-eye-right"'
    )[0]


def test_repair_renderer_eye_motion_skips_animate_without_values() -> None:
    """An animate element without a values= attribute is left alone."""
    eye_with_valueless_animate = (
        '<ellipse cx="92" cy="80" rx="8" ry="10"/>'
        '<animate attributeName="cx" from="88" to="96" dur="1s" repeatCount="indefinite"/>'
    )
    svg = _anchored_linai_svg(eye_left_markup=eye_with_valueless_animate)

    repaired = repair_renderer_eye_motion(svg)

    assert "animate" in repaired


def test_repair_renderer_root_translate_skips_non_numeric_coordinate_pair() -> None:
    """A pair where coordinates cannot be parsed as float is left unchanged."""
    svg = _anchored_linai_svg(
        extra_linai_markup=(
            '<animateTransform href="#linai" attributeName="transform" type="translate" '
            'values="x y;120 30;170 0" dur="1s" repeatCount="indefinite"/>'
        )
    )

    repaired = repair_renderer_root_translate(svg, max_y_px=config.RENDERER_ROOT_TRANSLATE_MAX_Y_PX)

    assert "x y" in repaired  # non-parseable pair left as-is


def test_repair_renderer_body_scale_skips_non_numeric_coordinate_pair() -> None:
    """A pair where coordinates cannot be parsed as float is left unchanged."""
    svg = _anchored_linai_svg(
        extra_linai_markup=(
            '<animateTransform href="#linai-body" attributeName="transform" type="scale" '
            'values="x y;0.9 0.9;1.5 1.5" dur="1s" repeatCount="indefinite"/>'
        )
    )

    repaired = repair_renderer_body_scale(
        svg,
        scale_min=config.RENDERER_BODY_SCALE_MIN,
        scale_max=config.RENDERER_BODY_SCALE_MAX,
    )

    assert "x y" in repaired  # non-parseable pair left as-is


def test_repair_renderer_eye_motion_skips_animate_transform_without_values() -> None:
    """An animateTransform inside an eye with no values= attribute is left alone."""
    eye_with_valueless_transform = (
        '<ellipse cx="92" cy="80" rx="8" ry="10"/>'
        '<animateTransform attributeName="transform" type="translate" '
        'from="0 0" to="5 3" dur="1s" repeatCount="indefinite"/>'
    )
    svg = _anchored_linai_svg(eye_left_markup=eye_with_valueless_transform)

    repaired = repair_renderer_eye_motion(svg)

    assert "animateTransform" in repaired  # not removed when values is absent


def test_repair_renderer_eye_motion_handles_values_with_empty_segments() -> None:
    """Leading/trailing semicolons in values= attributes are skipped without crashing."""
    # Leading semicolon produces an empty first segment in parse helpers.
    eye_with_leading_semi = (
        '<ellipse cx="92" cy="80" rx="8" ry="10"/>'
        '<animateTransform attributeName="transform" type="translate" '
        'values=";0 0;5 0;0 0" dur="1s" repeatCount="indefinite"/>'
    )
    svg = _anchored_linai_svg(eye_left_markup=eye_with_leading_semi)

    repaired = repair_renderer_eye_motion(svg)

    assert repaired  # should not raise


def test_repair_renderer_eye_motion_handles_rotate_with_empty_segment() -> None:
    """Leading semicolon in rotate values= is skipped without crashing."""
    eye_with_leading_semi = (
        '<ellipse cx="92" cy="80" rx="8" ry="10"/>'
        '<animateTransform attributeName="transform" type="rotate" '
        'values=";0;5;0" dur="1s" repeatCount="indefinite"/>'
    )
    svg = _anchored_linai_svg(eye_left_markup=eye_with_leading_semi)

    repaired = repair_renderer_eye_motion(svg)

    assert repaired  # should not raise


def test_repair_renderer_eye_motion_handles_cy_animate_with_empty_segment() -> None:
    """Leading semicolon in a cy animate values= is skipped without crashing."""
    anchor_cy = 80.0
    # Leading semicolon produces an empty string that _parse_numeric_values must skip.
    eye_with_leading_semi = (
        f'<ellipse cx="92" cy="{anchor_cy}" rx="8" ry="10">'
        f'<animate attributeName="cy" values=";{anchor_cy};{anchor_cy + 1};{anchor_cy}" '
        'dur="1s" repeatCount="indefinite"/>'
        '</ellipse>'
    )
    svg = _anchored_linai_svg(eye_left_markup=eye_with_leading_semi)

    repaired = repair_renderer_eye_motion(svg)

    assert repaired  # should not raise; drift is within bounds so element is preserved
    assert 'attributeName="cy"' in repaired


def test_repair_renderer_eye_motion_removes_excessive_cy_drift() -> None:
    """Eye animate cy that drifts too far from parent cy is removed."""
    anchor_cy = 80.0
    excessive_cy = anchor_cy + config.RENDERER_EYE_DRIFT_MAX_Y_PX + 10
    # The animate must be a child of the element that has the cy attribute
    # so that find_parent returns an element with "cy" in its attrib.
    eye_with_cy_drift = (
        f'<ellipse cx="92" cy="{anchor_cy}" rx="8" ry="10">'
        f'<animate attributeName="cy" '
        f'values="{anchor_cy};{excessive_cy};{anchor_cy}" '
        'dur="1s" repeatCount="indefinite"/>'
        '</ellipse>'
    )
    svg = _anchored_linai_svg(eye_left_markup=eye_with_cy_drift)

    repaired = repair_renderer_eye_motion(svg)

    assert 'attributeName="cy"' not in repaired
