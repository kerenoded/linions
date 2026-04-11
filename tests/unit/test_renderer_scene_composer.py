"""Unit tests for deterministic renderer scene composition."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from pipeline import config
from pipeline.agents.renderer.scene_composer import compose_renderer_scene_svg
from pipeline.models import ClipManifest, Keyframe


def _clip_with_layers() -> ClipManifest:
    return ClipManifest(
        act_index=0,
        obstacle_type="wall",
        branch="approach",
        choice_index=None,
        duration_ms=4000,
        obstacle_x=400,
        obstacle_svg_override=(
            '<svg xmlns="http://www.w3.org/2000/svg" id="obstacle-root" viewBox="0 0 120 150">'
            '<g id="obstacle-main"><rect x="10" y="20" width="100" height="120"/>'
            '<g id="obstacle-animated-part"><rect x="40" y="10" width="10" height="20"/>'
            '<animateTransform attributeName="transform" type="rotate" '
            'values="-3 45 20;3 45 20;-3 45 20" dur="2s" repeatCount="indefinite"/>'
            "</g></g></svg>"
        ),
        background_svg=(
            '<svg xmlns="http://www.w3.org/2000/svg" id="background-root" viewBox="0 0 800 200">'
            '<g id="background-main"><rect width="800" height="200" fill="#aaccee"/>'
            '<g id="background-animated-part"><rect width="800" height="40" fill="#ccddee">'
            '<animate attributeName="opacity" values="0.4;0.7;0.4" dur="3s" '
            'repeatCount="indefinite"/></rect></g></g></svg>'
        ),
        keyframes=[
            Keyframe(
                time_ms=0,
                character_x=40,
                character_y=160,
                support_y=160,
                is_grounded=True,
                expression="calm",
                action="floating in",
            ),
            Keyframe(
                time_ms=4000,
                character_x=320,
                character_y=160,
                support_y=160,
                is_grounded=True,
                expression="focused",
                action="halting mid-hover",
            ),
        ],
    )


def _find_parent(root: ET.Element, target: ET.Element) -> ET.Element | None:
    for parent in root.iter():
        if target in list(parent):
            return parent
    return None


def test_compose_renderer_scene_svg_reinserts_expected_layers_in_order() -> None:
    clip = _clip_with_layers()
    raw_scene = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 200">'
        '<g id="background-root"><g id="background-main"><rect width="1" height="1"/></g></g>'
        '<svg viewBox="0 0 120 150"><g id="obstacle-main"><rect width="10" height="10"/>'
        '<g id="obstacle-animated-part"><rect width="1" height="1"/></g></g></svg>'
        '<g id="linai">'
        '<g id="linai-body"><ellipse cx="104" cy="90" rx="34" ry="28"/></g>'
        '<g id="linai-eye-left"><ellipse cx="92" cy="80" rx="8" ry="10"/>'
        '<circle cx="94" cy="80" r="3"/><animateTransform attributeName="transform" '
        'type="translate" values="0 0;2 0;0 0" dur="1s" repeatCount="indefinite"/></g>'
        '<g id="linai-eye-right"><ellipse cx="116" cy="78" rx="9" ry="11"/>'
        '<circle cx="118" cy="78" r="3"/><animateTransform attributeName="transform" '
        'type="translate" values="0 0;2 0;0 0" dur="1s" repeatCount="indefinite"/></g>'
        '<g id="linai-mouth"><path d="M104 102 Q112 108 120 103"/></g>'
        '<g id="linai-inner-patterns"><path d="M88 84 Q100 74 112 82"/></g>'
        '<g id="linai-particles"><circle cx="100" cy="92" r="2"/></g>'
        '<g id="linai-trails"><path d="M92 118 Q88 136 84 154"/></g>'
        "</g>"
        "</svg>"
    )

    composed = compose_renderer_scene_svg(scene_svg=raw_scene, clip=clip)

    root = ET.fromstring(composed)
    direct_child_ids = [child.attrib.get("id") for child in list(root) if "id" in child.attrib]
    assert direct_child_ids == ["background-root", "obstacle-root", "linai"]

    obstacle = next(child for child in root if child.attrib.get("id") == "obstacle-root")
    assert obstacle.attrib["x"] == str(config.OBSTACLE_EMBED_X)
    assert obstacle.attrib["y"] == str(config.OBSTACLE_EMBED_Y)
    assert obstacle.attrib["width"] == str(config.OBSTACLE_EMBED_WIDTH)
    assert obstacle.attrib["height"] == str(config.OBSTACLE_EMBED_HEIGHT)

    background = next(child for child in root if child.attrib.get("id") == "background-root")
    assert background.attrib["width"] == str(config.CANVAS_WIDTH)
    assert background.attrib["height"] == str(config.CANVAS_HEIGHT)

    clip_path = next(
        element for element in root.iter() if element.attrib.get("id") == "cloud-body-clip"
    )
    assert clip_path.tag.endswith("clipPath")
    eye_left_socket_clip = next(
        element for element in root.iter() if element.attrib.get("id") == "cloud-eye-left-clip"
    )
    eye_right_socket_clip = next(
        element for element in root.iter() if element.attrib.get("id") == "cloud-eye-right-clip"
    )
    assert eye_left_socket_clip.tag.endswith("clipPath")
    assert eye_right_socket_clip.tag.endswith("clipPath")

    for element_id in (
        "linai-eye-left",
        "linai-eye-right",
        "linai-mouth",
        "linai-inner-patterns",
        "linai-particles",
    ):
        target = next(element for element in root.iter() if element.attrib.get("id") == element_id)
        assert target.attrib["clip-path"] == "url(#cloud-body-clip)"

    eye_left_group = next(
        element for element in root.iter() if element.attrib.get("id") == "linai-eye-left"
    )
    eye_right_group = next(
        element for element in root.iter() if element.attrib.get("id") == "linai-eye-right"
    )
    body_group = next(
        element for element in root.iter() if element.attrib.get("id") == "linai-body"
    )
    body_wrapper = next(
        child
        for child in list(body_group)
        if child.attrib.get("data-linai-body-content-wrapper") == "true"
    )
    assert _find_parent(root, eye_left_group) is body_wrapper
    assert _find_parent(root, eye_right_group) is body_wrapper

    eye_left_wrapper = next(
        child
        for child in list(eye_left_group)
        if child.attrib.get("data-eye-socket-wrapper") == "true"
    )
    eye_right_wrapper = next(
        child
        for child in list(eye_right_group)
        if child.attrib.get("data-eye-socket-wrapper") == "true"
    )
    assert eye_left_wrapper.attrib["clip-path"] == "url(#cloud-eye-left-clip)"
    assert eye_right_wrapper.attrib["clip-path"] == "url(#cloud-eye-right-clip)"
    assert [child.tag.rsplit('}', 1)[-1] for child in list(eye_left_wrapper)] == [
        "ellipse",
        "circle",
        "animateTransform",
    ]
    assert [child.tag.rsplit('}', 1)[-1] for child in list(eye_right_wrapper)] == [
        "ellipse",
        "circle",
        "animateTransform",
    ]


def test_compose_renderer_scene_svg_reuses_existing_eye_group_wrapper_for_socket_clip() -> None:
    clip = _clip_with_layers()
    raw_scene = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 200">'
        '<g id="linai">'
        '<g id="linai-body"><ellipse cx="104" cy="90" rx="34" ry="28"/>'
        '<g id="linai-eye-left"><g><animateTransform attributeName="transform" type="translate" '
        'values="0 0;2 0;0 0" dur="1s" repeatCount="indefinite"/>'
        '<ellipse cx="92" cy="80" rx="8" ry="10"/><circle cx="94" cy="80" r="3"/></g></g>'
        '<g id="linai-eye-right"><g><animateTransform attributeName="transform" type="translate" '
        'values="0 0;2 0;0 0" dur="1s" repeatCount="indefinite"/>'
        '<ellipse cx="116" cy="78" rx="9" ry="11"/><circle cx="118" cy="78" r="3"/></g></g>'
        '<g id="linai-mouth"><path d="M104 102 Q112 108 120 103"/></g>'
        '<g id="linai-inner-patterns"><path d="M88 84 Q100 74 112 82"/></g>'
        '<g id="linai-particles"><circle cx="100" cy="92" r="2"/></g>'
        "</g>"
        '<g id="linai-trails"><path d="M92 118 Q88 136 84 154"/></g>'
        "</g>"
        "</svg>"
    )

    composed = compose_renderer_scene_svg(scene_svg=raw_scene, clip=clip)
    root = ET.fromstring(composed)

    eye_left_group = next(
        element for element in root.iter() if element.attrib.get("id") == "linai-eye-left"
    )
    wrapper = next(
        child
        for child in list(eye_left_group)
        if child.attrib.get("data-eye-socket-wrapper") == "true"
    )
    assert wrapper.attrib["clip-path"] == "url(#cloud-eye-left-clip)"
    assert [child.tag.rsplit('}', 1)[-1] for child in list(wrapper)] == [
        "animateTransform",
        "ellipse",
        "circle",
    ]
