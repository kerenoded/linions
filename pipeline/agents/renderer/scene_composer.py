"""Deterministic scene-layer composition for Renderer SVG output."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from pipeline import config
from pipeline.models import ClipManifest
from pipeline.validators._xml_utils import local_name, to_svg_string

_OBSTACLE_LAYER_IDS = {"obstacle-root", "obstacle-main", "obstacle-animated-part"}
_BACKGROUND_LAYER_IDS = {"background-root", "background-main", "background-animated-part"}
_LINAI_INTERNAL_CLIP_ID = "cloud-body-clip"
_LINAI_EYE_SOCKET_CLIP_IDS = {
    "linai-eye-left": "cloud-eye-left-clip",
    "linai-eye-right": "cloud-eye-right-clip",
}
_LINAI_INTERNAL_CLIP_PATH = (
    "M55 95 Q45 60 70 38 Q85 28 105 25 Q130 22 148 38 "
    "Q165 55 160 80 Q158 100 150 120 Q140 142 120 148 "
    "Q100 155 80 148 Q60 140 55 120 Z"
)
_EYE_SOCKET_WRAPPER_ATTR = "data-eye-socket-wrapper"
_LINAI_BODY_CONTENT_WRAPPER_ATTR = "data-linai-body-content-wrapper"
_LINAI_BODY_INTERNAL_GROUP_IDS = (
    "linai-particles",
    "linai-mouth",
    "linai-eye-left",
    "linai-eye-right",
    "linai-inner-patterns",
)


def _subtree_ids(element: ET.Element) -> set[str]:
    """Return all explicit ``id`` values present under one subtree."""
    return {node.attrib["id"] for node in element.iter() if "id" in node.attrib}


def _remove_layer_children(root: ET.Element, *, layer_ids: set[str]) -> None:
    """Remove direct scene children whose subtree contains any target layer ids."""
    for child in list(root):
        if _subtree_ids(child).intersection(layer_ids):
            root.remove(child)


def _parse_nested_svg(svg_text: str) -> ET.Element:
    """Parse one standalone SVG document that will be nested into a scene."""
    element = ET.fromstring(svg_text)
    if local_name(element.tag) != "svg":
        msg = "nested renderer scene layer must have an <svg> root"
        raise ValueError(msg)
    return element


def _leading_defs_count(root: ET.Element) -> int:
    """Return how many leading direct children are ``<defs>`` blocks."""
    count = 0
    for child in list(root):
        if local_name(child.tag) != "defs":
            break
        count += 1
    return count


def _find_element_by_id(root: ET.Element, element_id: str) -> ET.Element | None:
    """Return the first element in ``root`` whose ``id`` exactly matches."""
    for element in root.iter():
        if element.attrib.get("id") == element_id:
            return element
    return None


def _qualify_tag(root: ET.Element, local_tag: str) -> str:
    """Return one tag name that matches the scene root namespace style."""
    if root.tag.startswith("{") and "}" in root.tag:
        namespace = root.tag[1:].split("}", 1)[0]
        return f"{{{namespace}}}{local_tag}"
    return local_tag


def _find_parent(root: ET.Element, target: ET.Element) -> ET.Element | None:
    """Return the direct parent element for one target, when present."""
    for parent in root.iter():
        if target in list(parent):
            return parent
    return None


def _is_nested_inside(root: ET.Element, target: ET.Element, *, ancestor_id: str) -> bool:
    """Return whether ``target`` is nested under the named ancestor id."""
    current = target
    while True:
        parent = _find_parent(root, current)
        if parent is None:
            return False
        if parent.attrib.get("id") == ancestor_id:
            return True
        current = parent


def _ensure_root_defs(root: ET.Element) -> ET.Element:
    """Return the direct root ``<defs>`` block, creating one when missing."""
    for child in list(root):
        if local_name(child.tag) == "defs":
            return child

    defs = ET.Element(_qualify_tag(root, "defs"))
    root.insert(0, defs)
    return defs


def _first_geometry_child(group: ET.Element) -> ET.Element | None:
    """Return the first geometry child that can define a clip boundary."""
    for child in group.iter():
        if child is group:
            continue
        if local_name(child.tag) in {"ellipse", "path"}:
            return child
    return None


def _geometry_attrs_for_clip(shape: ET.Element) -> dict[str, str]:
    """Return only geometry attrs that are safe to reuse inside a clipPath."""
    disallowed = {"id", "fill", "stroke", "clip-path", "filter", "opacity", "style"}
    return {
        name: value
        for name, value in shape.attrib.items()
        if not name.startswith("{") and name not in disallowed
    }


def _ensure_eye_socket_clip(
    *,
    root: ET.Element,
    defs: ET.Element,
    eye_group_id: str,
    eye_group: ET.Element,
) -> str | None:
    """Return one per-eye clipPath reference built from the eye's base geometry."""
    clip_id = _LINAI_EYE_SOCKET_CLIP_IDS[eye_group_id]
    clip_path = _find_element_by_id(defs, clip_id)
    if clip_path is not None:
        return f"url(#{clip_id})"

    shape = _first_geometry_child(eye_group)
    if shape is None:
        return None

    clip_path = ET.SubElement(
        defs,
        _qualify_tag(root, "clipPath"),
        {"id": clip_id},
    )
    ET.SubElement(
        clip_path,
        _qualify_tag(root, local_name(shape.tag)),
        _geometry_attrs_for_clip(shape),
    )
    return f"url(#{clip_id})"


def _wrap_eye_contents_with_socket_clip(
    *,
    root: ET.Element,
    eye_group: ET.Element,
    clip_path_ref: str,
) -> None:
    """Wrap all eye contents in an inner group clipped to the eye socket."""
    wrapper = next(
        (
            child
            for child in list(eye_group)
            if local_name(child.tag) == "g"
            and child.attrib.get(_EYE_SOCKET_WRAPPER_ATTR) == "true"
        ),
        None,
    )
    if wrapper is None:
        lone_group_wrapper = next(
            (
                child
                for child in list(eye_group)
                if local_name(child.tag) == "g"
            ),
            None,
        )
        if lone_group_wrapper is not None and len(list(eye_group)) == 1:
            wrapper = lone_group_wrapper
            wrapper.attrib[_EYE_SOCKET_WRAPPER_ATTR] = "true"

    if wrapper is None:
        wrapper = ET.Element(
            _qualify_tag(root, "g"),
            {_EYE_SOCKET_WRAPPER_ATTR: "true"},
        )
        for child in list(eye_group):
            eye_group.remove(child)
            wrapper.append(child)
        eye_group.append(wrapper)
    wrapper.attrib["clip-path"] = clip_path_ref


def _ensure_linai_body_content_wrapper(
    *,
    root: ET.Element,
    body_group: ET.Element,
) -> ET.Element:
    """Return a stable wrapper used for face layers that must follow body motion."""
    wrapper = next(
        (
            child
            for child in list(body_group)
            if local_name(child.tag) == "g"
            and child.attrib.get(_LINAI_BODY_CONTENT_WRAPPER_ATTR) == "true"
        ),
        None,
    )
    if wrapper is not None:
        return wrapper

    wrapper = ET.Element(
        _qualify_tag(root, "g"),
        {_LINAI_BODY_CONTENT_WRAPPER_ATTR: "true"},
    )
    body_group.append(wrapper)
    return wrapper


def _nest_linai_body_internal_groups(root: ET.Element) -> None:
    """Move Linai's face and inner effects under ``linai-body``.

    This keeps eye, mouth, and symbol motion anchored to the same body
    transforms so the cloud mass cannot visibly animate away from the face.
    """
    body_group = _find_element_by_id(root, "linai-body")
    if body_group is None:
        return

    body_wrapper: ET.Element | None = None
    for group_id in _LINAI_BODY_INTERNAL_GROUP_IDS:
        target = _find_element_by_id(root, group_id)
        if target is None or _is_nested_inside(root, target, ancestor_id="linai-body"):
            continue

        parent = _find_parent(root, target)
        if parent is None:
            continue

        if body_wrapper is None:
            body_wrapper = _ensure_linai_body_content_wrapper(
                root=root,
                body_group=body_group,
            )

        parent.remove(target)
        body_wrapper.append(target)


def _apply_linai_internal_clip(root: ET.Element) -> None:
    """Clip Linai's face and inner effects so they never detach from the body."""
    defs = _ensure_root_defs(root)
    clip_path = _find_element_by_id(defs, _LINAI_INTERNAL_CLIP_ID)
    if clip_path is None:
        clip_path = ET.SubElement(
            defs,
            _qualify_tag(root, "clipPath"),
            {"id": _LINAI_INTERNAL_CLIP_ID},
        )
        ET.SubElement(
            clip_path,
            _qualify_tag(root, "path"),
            {"d": _LINAI_INTERNAL_CLIP_PATH},
        )

    clip_path_ref = f"url(#{_LINAI_INTERNAL_CLIP_ID})"
    for group_id in _LINAI_BODY_INTERNAL_GROUP_IDS:
        target = _find_element_by_id(root, group_id)
        if target is not None:
            target.attrib["clip-path"] = clip_path_ref
            if group_id in _LINAI_EYE_SOCKET_CLIP_IDS:
                eye_socket_clip_ref = _ensure_eye_socket_clip(
                    root=root,
                    defs=defs,
                    eye_group_id=group_id,
                    eye_group=target,
                )
                if eye_socket_clip_ref is not None:
                    _wrap_eye_contents_with_socket_clip(
                        root=root,
                        eye_group=target,
                        clip_path_ref=eye_socket_clip_ref,
                    )


def compose_renderer_scene_svg(*, scene_svg: str, clip: ClipManifest) -> str:
    """Reinsert the known background and obstacle layers into one scene SVG.

    Args:
        scene_svg: Raw scene SVG returned by the Renderer model.
        clip: Original clip manifest containing deterministic obstacle/background layers.

    Returns:
        SVG string with background and obstacle layers reinserted in stable order.

    Raises:
        xml.etree.ElementTree.ParseError: If the scene or nested SVG layers are malformed XML.
        ValueError: If the scene or nested layers do not have an ``<svg>`` root.
    """
    root = ET.fromstring(scene_svg)
    if local_name(root.tag) != "svg":
        msg = "renderer scene root must be <svg>"
        raise ValueError(msg)

    _remove_layer_children(root, layer_ids=_BACKGROUND_LAYER_IDS)
    _remove_layer_children(root, layer_ids=_OBSTACLE_LAYER_IDS)

    insert_index = _leading_defs_count(root)
    if clip.background_svg is not None:
        background_root = _parse_nested_svg(clip.background_svg)
        background_root.attrib["x"] = "0"
        background_root.attrib["y"] = "0"
        background_root.attrib["width"] = str(config.CANVAS_WIDTH)
        background_root.attrib["height"] = str(config.CANVAS_HEIGHT)
        root.insert(insert_index, background_root)
        insert_index += 1

    if clip.obstacle_svg_override is not None:
        obstacle_root = _parse_nested_svg(clip.obstacle_svg_override)
        obstacle_root.attrib["x"] = str(config.OBSTACLE_EMBED_X)
        obstacle_root.attrib["y"] = str(config.OBSTACLE_EMBED_Y)
        obstacle_root.attrib["width"] = str(config.OBSTACLE_EMBED_WIDTH)
        obstacle_root.attrib["height"] = str(config.OBSTACLE_EMBED_HEIGHT)
        root.insert(insert_index, obstacle_root)

    _nest_linai_body_internal_groups(root)
    _apply_linai_internal_clip(root)

    return to_svg_string(root)
