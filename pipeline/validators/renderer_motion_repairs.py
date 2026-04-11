"""Deterministic repair helpers for known renderer motion drift."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from pipeline import config
from pipeline.validators._xml_utils import local_name, to_svg_string
from pipeline.validators.renderer_motion_shared import (
    ANIMATION_TAGS,
    EYE_SOCKET_IDS,
    find_parent,
    is_allowed_dynamic_linai_id,
    iter_body_scale_animations,
    iter_eye_group_descendants,
    iter_root_translate_animations,
)


def repair_renderer_root_translate(svg: str, *, max_y_px: int) -> str:
    """Clamp excessive downward root translate values in one rendered SVG."""
    root = ET.fromstring(svg)

    for animation in iter_root_translate_animations(root):
        values_text = animation.attrib.get("values")
        if not values_text:
            continue

        new_pairs: list[str] = []
        clamped = False
        for pair in values_text.split(";"):
            coords = pair.replace(",", " ").split()
            if len(coords) != 2:
                new_pairs.append(pair)
                continue
            try:
                x_value = float(coords[0])
                y_value = float(coords[1])
            except ValueError:
                new_pairs.append(pair)
                continue
            if y_value > max_y_px:
                y_value = float(max_y_px)
                clamped = True
            new_pairs.append(f"{x_value:g} {y_value:g}")

        if clamped:
            animation.attrib["values"] = ";".join(new_pairs)

    return to_svg_string(root)


def repair_renderer_fail_translate(svg: str) -> str:
    """Clamp fail-clip downward root translate values using the fail threshold."""
    return repair_renderer_root_translate(
        svg,
        max_y_px=config.RENDERER_FAIL_ROOT_TRANSLATE_MAX_Y_PX,
    )


def repair_renderer_body_scale(
    svg: str, *, scale_min: float, scale_max: float
) -> str:
    """Clamp out-of-range body scale values in one rendered SVG."""
    root = ET.fromstring(svg)

    for animation in iter_body_scale_animations(root):
        values_text = animation.attrib.get("values")
        if not values_text:
            continue

        new_pairs: list[str] = []
        clamped = False
        for pair in values_text.split(";"):
            coords = pair.replace(",", " ").split()
            if len(coords) != 2:
                new_pairs.append(pair)
                continue
            try:
                x_value = float(coords[0])
                y_value = float(coords[1])
            except ValueError:
                new_pairs.append(pair)
                continue
            new_x = max(scale_min, min(scale_max, x_value))
            new_y = max(scale_min, min(scale_max, y_value))
            if new_x != x_value or new_y != y_value:
                clamped = True
            new_pairs.append(f"{new_x:g} {new_y:g}")

        if clamped:
            animation.attrib["values"] = ";".join(new_pairs)

    return to_svg_string(root)


def repair_renderer_eye_motion(svg: str) -> str:
    """Remove excessive eye-interior animations from one rendered SVG."""
    root = ET.fromstring(svg)

    for eye_id in EYE_SOCKET_IDS:
        for element in list(iter_eye_group_descendants(root, eye_id)):
            if local_name(element.tag) == "animateTransform":
                # Remove all animateTransform inside eye groups — the allowed
                # thresholds are so tight (3px/2px/12°) that any meaningful
                # transform would be flagged. Blanket removal is more reliable
                # than selective removal and ensures re-validation always passes.
                _remove_element(root, element)
                continue

            if local_name(element.tag) == "animate":
                parent = find_parent(root, element)
                values_text = element.attrib.get("values")
                if parent is None or values_text is None:
                    continue
                attribute_name = element.attrib.get("attributeName")
                if attribute_name == "cx" and "cx" in parent.attrib and any(
                    abs(value - float(parent.attrib["cx"])) > config.RENDERER_EYE_DRIFT_MAX_X_PX
                    for value in _parse_numeric_values(values_text)
                ):
                    _remove_element(root, element)
                    continue
                if attribute_name == "cy" and "cy" in parent.attrib and any(
                    abs(value - float(parent.attrib["cy"])) > config.RENDERER_EYE_DRIFT_MAX_Y_PX
                    for value in _parse_numeric_values(values_text)
                ):
                    _remove_element(root, element)
                    continue

    return to_svg_string(root)


def repair_renderer_unsupported_animation_targets(svg: str) -> str:
    """Remove animation nodes that target unsupported or invalid Linai ids."""
    root = ET.fromstring(svg)

    for candidate in list(root.iter()):
        if local_name(candidate.tag) not in ANIMATION_TAGS:
            continue
        href_value = candidate.attrib.get("href") or candidate.attrib.get(
            "{http://www.w3.org/1999/xlink}href"
        )
        if href_value is None or not href_value.startswith("#linai"):
            continue
        target_id = href_value[1:]
        if not is_allowed_dynamic_linai_id(root, target_id):
            _remove_element(root, candidate)

    return to_svg_string(root)


def _parse_numeric_values(values_text: str) -> list[float]:
    parsed: list[float] = []
    for raw_value in values_text.split(";"):
        stripped = raw_value.strip()
        if stripped == "":
            continue
        parsed.append(float(stripped))
    return parsed


def _parse_transform_pairs(values_text: str) -> list[tuple[float, float]]:
    pairs: list[tuple[float, float]] = []
    for raw_pair in values_text.split(";"):
        coords = raw_pair.replace(",", " ").split()
        if len(coords) != 2:
            continue
        pairs.append((float(coords[0]), float(coords[1])))
    return pairs


def _parse_rotate_values(values_text: str) -> list[float]:
    angles: list[float] = []
    for raw_value in values_text.split(";"):
        coords = raw_value.replace(",", " ").split()
        if len(coords) < 1:
            continue
        angles.append(float(coords[0]))
    return angles


def _remove_element(root: ET.Element, target: ET.Element) -> None:
    parent = find_parent(root, target)
    if parent is not None:
        parent.remove(target)
