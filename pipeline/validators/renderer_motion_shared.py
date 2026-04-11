"""Shared helpers for renderer motion validation and repair."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from pipeline import config
from pipeline.models import ClipManifest
from pipeline.validators._xml_utils import local_name

ANIMATION_TAGS = {"animate", "animateTransform", "animateMotion", "set"}
SUPPORTED_LINAI_IDS = {
    "linai",
    "linai-body",
    "linai-eye-left",
    "linai-eye-right",
    "linai-mouth",
    "linai-inner-patterns",
    "linai-particles",
    "linai-trails",
}
INNER_PATTERNS_CHILD_ID_PREFIXES = (
    "linai-inner-patterns-",
    "linai-inner-",
)
MOUTH_CHILD_ID_PREFIXES = ("linai-mouth-",)
TRAVEL_MOTION_IDS = {
    "linai",
    "linai-body",
    "linai-trails",
    "linai-particles",
}
LINAI_BODY_ANCHORED_IDS = {
    "linai-eye-left",
    "linai-eye-right",
    "linai-mouth",
    "linai-inner-patterns",
    "linai-particles",
}
EYE_SOCKET_IDS = {"linai-eye-left", "linai-eye-right"}
EYE_SOCKET_WRAPPER_ATTR = "data-eye-socket-wrapper"
EYE_SOCKET_CLIP_IDS = {
    "linai-eye-left": "cloud-eye-left-clip",
    "linai-eye-right": "cloud-eye-right-clip",
}


def find_element_by_id(root: ET.Element, element_id: str) -> ET.Element | None:
    """Return the first SVG element with the requested id."""
    for element in root.iter():
        if element.attrib.get("id") == element_id:
            return element
    return None


def find_parent(root: ET.Element, target: ET.Element) -> ET.Element | None:
    """Return the direct parent element for one SVG node."""
    for parent in root.iter():
        if target in list(parent):
            return parent
    return None


def is_allowed_dynamic_linai_id(root: ET.Element, element_id: str) -> bool:
    """Return whether one Linai-prefixed id is valid in the v2 SVG contract."""
    if element_id in SUPPORTED_LINAI_IDS:
        return True
    target = find_element_by_id(root, element_id)
    if target is None:
        return False

    if any(element_id.startswith(prefix) for prefix in INNER_PATTERNS_CHILD_ID_PREFIXES):
        return _is_nested_inside_inner_patterns(root, target)

    if any(element_id.startswith(prefix) for prefix in MOUTH_CHILD_ID_PREFIXES):
        return _is_nested_inside(root, target, ancestor_id="linai-mouth")

    return False


def has_animation_for_id(root: ET.Element, element_id: str) -> bool:
    """Return whether one SVG id has inline animation or animation hrefs."""
    target = find_element_by_id(root, element_id)
    if target is None:
        return False
    if any(local_name(descendant.tag) in ANIMATION_TAGS for descendant in target.iter()):
        return True

    target_ref = f"#{element_id}"
    for candidate in root.iter():
        if local_name(candidate.tag) not in ANIMATION_TAGS:
            continue
        href_value = candidate.attrib.get("href") or candidate.attrib.get(
            "{http://www.w3.org/1999/xlink}href"
        )
        if href_value == target_ref:
            return True
    return False


def requires_grounded_locomotion(clip: ClipManifest) -> bool:
    """Return whether a clip should show visible grounded travel motion."""
    grounded_keyframes = [keyframe for keyframe in clip.keyframes if keyframe.is_grounded]
    if len(grounded_keyframes) < 2:
        return False

    grounded_xs = [keyframe.character_x for keyframe in grounded_keyframes]
    return max(grounded_xs) - min(grounded_xs) >= config.RENDERER_GROUNDED_TRAVEL_MIN_PX


def collect_unsupported_linai_ids(root: ET.Element) -> list[str]:
    """Collect Linai-prefixed ids that are not allowed by the v2 contract."""
    present_ids = {element.attrib.get("id") for element in root.iter() if "id" in element.attrib}
    return sorted(
        element_id
        for element_id in present_ids
        if element_id is not None
        and element_id.startswith("linai")
        and not is_allowed_dynamic_linai_id(root, element_id)
    )


def collect_unsupported_linai_animation_targets(root: ET.Element) -> list[str]:
    """Collect invalid Linai ids referenced by animation href targets."""
    invalid_targets: set[str] = set()
    for candidate in root.iter():
        if local_name(candidate.tag) not in ANIMATION_TAGS:
            continue
        href_value = candidate.attrib.get("href") or candidate.attrib.get(
            "{http://www.w3.org/1999/xlink}href"
        )
        if href_value is None or not href_value.startswith("#linai"):
            continue

        target_id = href_value[1:]
        if not is_allowed_dynamic_linai_id(root, target_id):
            invalid_targets.add(target_id)

    return sorted(invalid_targets)


def collect_body_detached_linai_ids(root: ET.Element) -> list[str]:
    """Collect face/effect ids that are no longer nested under linai-body."""
    detached_ids: list[str] = []
    for element_id in sorted(LINAI_BODY_ANCHORED_IDS):
        target = find_element_by_id(root, element_id)
        if target is None:
            continue
        if not _is_nested_inside_body(root, target):
            detached_ids.append(element_id)
    return detached_ids


def collect_eye_socket_translate_targets(root: ET.Element) -> list[str]:
    """Collect eye-group ids whose whole sockets are being translated."""
    invalid_targets: set[str] = set()

    for eye_id in EYE_SOCKET_IDS:
        eye_group = find_element_by_id(root, eye_id)
        if eye_group is None:
            continue
        for child in list(eye_group):
            if (
                local_name(child.tag) == "animateTransform"
                and child.attrib.get("type") == "translate"
            ):
                invalid_targets.add(eye_id)

    for candidate in root.iter():
        if (
            local_name(candidate.tag) != "animateTransform"
            or candidate.attrib.get("type") != "translate"
        ):
            continue
        href_value = candidate.attrib.get("href") or candidate.attrib.get(
            "{http://www.w3.org/1999/xlink}href"
        )
        if href_value in {"#linai-eye-left", "#linai-eye-right"}:
            invalid_targets.add(href_value[1:])

    return sorted(invalid_targets)


def collect_missing_eye_socket_wrappers(root: ET.Element) -> list[str]:
    """Collect eye groups missing the required socket clipping wrapper."""
    missing_ids: list[str] = []
    for eye_id in sorted(EYE_SOCKET_IDS):
        eye_group = find_element_by_id(root, eye_id)
        if eye_group is None:
            continue

        expected_clip_path = f"url(#{EYE_SOCKET_CLIP_IDS[eye_id]})"
        wrapper = next(
            (
                child
                for child in list(eye_group)
                if local_name(child.tag) == "g"
                and child.attrib.get(EYE_SOCKET_WRAPPER_ATTR) == "true"
                and child.attrib.get("clip-path") == expected_clip_path
            ),
            None,
        )
        if wrapper is None:
            missing_ids.append(eye_id)

    return missing_ids


def iter_eye_group_descendants(root: ET.Element, eye_id: str) -> list[ET.Element]:
    """Return all descendants inside one eye group, excluding the group itself."""
    eye_group = find_element_by_id(root, eye_id)
    if eye_group is None:
        return []
    return [element for element in eye_group.iter() if element is not eye_group]


def collect_excessive_eye_motion_targets(root: ET.Element) -> list[str]:
    """Collect eye ids whose inner motion exceeds the subtle-motion limits."""
    invalid_targets: set[str] = set()

    for eye_id in EYE_SOCKET_IDS:
        for element in iter_eye_group_descendants(root, eye_id):
            if local_name(element.tag) == "animateTransform":
                values_text = element.attrib.get("values")
                animation_type = element.attrib.get("type")
                if animation_type == "scale":
                    invalid_targets.add(eye_id)
                    continue
                if not values_text:
                    continue

                if animation_type == "translate":
                    for x_value, y_value in _parse_transform_pairs(values_text):
                        if (
                            abs(x_value) > config.RENDERER_EYE_DRIFT_MAX_X_PX
                            or abs(y_value) > config.RENDERER_EYE_DRIFT_MAX_Y_PX
                        ):
                            invalid_targets.add(eye_id)
                            break

                if animation_type == "rotate":
                    for angle in _parse_rotate_values(values_text):
                        if abs(angle) > config.RENDERER_EYE_ROTATE_MAX_DEGREES:
                            invalid_targets.add(eye_id)
                            break

            if local_name(element.tag) == "animate":
                attribute_name = element.attrib.get("attributeName")
                values_text = element.attrib.get("values")
                parent = find_parent(root, element)
                if values_text is None or parent is None:
                    continue

                if attribute_name == "cx" and "cx" in parent.attrib:
                    base_x = float(parent.attrib["cx"])
                    if any(
                        abs(value - base_x) > config.RENDERER_EYE_DRIFT_MAX_X_PX
                        for value in _parse_numeric_values(values_text)
                    ):
                        invalid_targets.add(eye_id)

                if attribute_name == "cy" and "cy" in parent.attrib:
                    base_y = float(parent.attrib["cy"])
                    if any(
                        abs(value - base_y) > config.RENDERER_EYE_DRIFT_MAX_Y_PX
                        for value in _parse_numeric_values(values_text)
                    ):
                        invalid_targets.add(eye_id)

    return sorted(invalid_targets)


def iter_root_translate_animations(root: ET.Element) -> list[ET.Element]:
    """Return all animateTransform nodes that translate the root linai group."""
    root_translates: list[ET.Element] = []
    linai = find_element_by_id(root, "linai")
    if linai is not None:
        for child in list(linai):
            if (
                local_name(child.tag) == "animateTransform"
                and child.attrib.get("type") == "translate"
            ):
                root_translates.append(child)

    for candidate in root.iter():
        if (
            local_name(candidate.tag) != "animateTransform"
            or candidate.attrib.get("type") != "translate"
        ):
            continue
        href_value = candidate.attrib.get("href") or candidate.attrib.get(
            "{http://www.w3.org/1999/xlink}href"
        )
        if href_value == "#linai" and candidate not in root_translates:
            root_translates.append(candidate)

    return root_translates


def collect_excessive_root_downward_translate_values(
    root: ET.Element, *, max_y_px: int
) -> list[float]:
    """Collect root linai y-translate values that exceed the allowed limit."""
    excessive_values: set[float] = set()

    for animation in iter_root_translate_animations(root):
        values_text = animation.attrib.get("values")
        if not values_text:
            continue

        for pair in values_text.split(";"):
            coords = pair.replace(",", " ").split()
            if len(coords) != 2:
                continue
            try:
                y_value = float(coords[1])
            except ValueError:
                continue
            if y_value > max_y_px:
                excessive_values.add(y_value)

    return sorted(excessive_values)


def iter_body_scale_animations(root: ET.Element) -> list[ET.Element]:
    """Return all animateTransform nodes that scale the linai-body group."""
    scale_animations: list[ET.Element] = []
    body_group = find_element_by_id(root, "linai-body")
    if body_group is not None:
        for child in list(body_group):
            if (
                local_name(child.tag) == "animateTransform"
                and child.attrib.get("type") == "scale"
            ):
                scale_animations.append(child)

    for candidate in root.iter():
        if (
            local_name(candidate.tag) != "animateTransform"
            or candidate.attrib.get("type") != "scale"
        ):
            continue
        href_value = candidate.attrib.get("href") or candidate.attrib.get(
            "{http://www.w3.org/1999/xlink}href"
        )
        if href_value == "#linai-body" and candidate not in scale_animations:
            scale_animations.append(candidate)

    return scale_animations


def collect_excessive_body_scale_values(
    root: ET.Element, *, scale_min: float, scale_max: float
) -> list[tuple[float, float]]:
    """Collect linai-body scale pairs that fall outside the allowed range."""
    excessive_values: set[tuple[float, float]] = set()

    for animation in iter_body_scale_animations(root):
        values_text = animation.attrib.get("values")
        if not values_text:
            continue

        for x_value, y_value in _parse_transform_pairs(values_text):
            if (
                x_value < scale_min
                or x_value > scale_max
                or y_value < scale_min
                or y_value > scale_max
            ):
                excessive_values.add((x_value, y_value))

    return sorted(excessive_values)


def _is_nested_inside(root: ET.Element, element: ET.Element, *, ancestor_id: str) -> bool:
    current = element
    while True:
        parent = find_parent(root, current)
        if parent is None:
            return False
        if parent.attrib.get("id") == ancestor_id:
            return True
        current = parent


def _is_nested_inside_inner_patterns(root: ET.Element, element: ET.Element) -> bool:
    return _is_nested_inside(root, element, ancestor_id="linai-inner-patterns")


def _is_nested_inside_body(root: ET.Element, element: ET.Element) -> bool:
    return _is_nested_inside(root, element, ancestor_id="linai-body")


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
