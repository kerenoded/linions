"""Unit tests for thumbnail extraction utility."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from pipeline.media.thumbnail import extract_thumbnail
from pipeline.validators._xml_utils import find_parent, local_name


def test_extract_thumbnail_strips_linai_animation_elements() -> None:
    svg = (
        '<svg viewBox="0 0 800 200">'
        '<g id="linai">'
        '<animateTransform attributeName="transform" type="translate" values="0 0;10 0" dur="1s"/>'
        '<g id="linai-body"><animate attributeName="opacity" from="0" to="1" dur="1s"/></g>'
        "</g>"
        "</svg>"
    )

    thumbnail = extract_thumbnail(svg)
    assert "<animate" not in thumbnail
    assert "<animateTransform" not in thumbnail
    assert 'id="linai"' in thumbnail


def test_extract_thumbnail_preserves_background_and_obstacle_animations() -> None:
    svg = (
        '<svg viewBox="0 0 800 200">'
        '<g id="background-root">'
        '<g id="background-animated-part">'
        '<animate attributeName="opacity" values="0.8;1;0.8" dur="3s" repeatCount="indefinite"/>'
        "</g>"
        "</g>"
        '<g id="obstacle-root">'
        '<g id="obstacle-animated-part">'
        '<animateTransform attributeName="transform" type="translate" '
        'values="0 0;5 0" dur="2s" repeatCount="indefinite"/>'
        "</g>"
        "</g>"
        '<g id="linai">'
        '<animate attributeName="opacity" from="0" to="1" dur="1s"/>'
        "</g>"
        "</svg>"
    )

    thumbnail = extract_thumbnail(svg)
    root = ET.fromstring(thumbnail)
    bg_part = next(el for el in root.iter() if el.attrib.get("id") == "background-animated-part")
    obs_part = next(el for el in root.iter() if el.attrib.get("id") == "obstacle-animated-part")
    linai = next(el for el in root.iter() if el.attrib.get("id") == "linai")

    assert any(local_name(el.tag) in {"animate", "animateTransform"} for el in bg_part.iter())
    assert any(local_name(el.tag) in {"animate", "animateTransform"} for el in obs_part.iter())
    assert not any(local_name(el.tag) in {"animate", "animateTransform"} for el in linai.iter())


def test_extract_thumbnail_keeps_non_animated_svg() -> None:
    svg = '<svg viewBox="0 0 800 200"><g id="linai"/></svg>'

    thumbnail = extract_thumbnail(svg)
    assert "viewBox" in thumbnail
    assert 'id="linai"' in thumbnail


def test_extract_thumbnail_raises_on_malformed_xml() -> None:
    with pytest.raises(ValueError):
        extract_thumbnail("<svg>")


def test_extract_thumbnail_raises_without_linai_element() -> None:
    svg = '<svg viewBox="0 0 800 200"><g id="other"/></svg>'
    with pytest.raises(ValueError):
        extract_thumbnail(svg)


def test_extract_thumbnail_raises_for_none_input() -> None:
    with pytest.raises(TypeError):
        extract_thumbnail(None)  # type: ignore[arg-type]


def test_thumbnail_helpers_cover_namespace_and_missing_parent_branch() -> None:
    assert local_name("{http://www.w3.org/2000/svg}svg") == "svg"

    root = ET.fromstring('<svg viewBox="0 0 800 200"><g id="linai"/></svg>')
    detached = ET.Element("animate")
    assert find_parent(root, detached) is None
