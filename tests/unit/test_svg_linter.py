"""Unit tests for SVG linter rules (DESIGN.md §6.4)."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from pipeline.validators._xml_utils import find_parent, local_name
from pipeline.validators.svg_linter import validate_and_sanitise_svg

FIXTURES_DIR = Path("tests/fixtures")


def _load_fixture(path: str) -> dict:
    return json.loads((FIXTURES_DIR / path).read_text())


def _first_approach_svg(path: str) -> str:
    fixture = _load_fixture(path)
    return fixture["acts"][0]["clips"]["approach"]


def test_validate_and_sanitise_svg_passes_for_valid_svg() -> None:
    svg = _first_approach_svg("valid_episode.json")

    result, sanitised = validate_and_sanitise_svg(svg)
    assert result.is_valid is True
    assert sanitised is not None
    assert "viewBox" in sanitised
    assert "<ns0:" not in sanitised


def test_validate_and_sanitise_svg_fails_on_forbidden_script_tag() -> None:
    svg = _first_approach_svg("invalid/svg-with-script-tag.json")

    result, sanitised = validate_and_sanitise_svg(svg)
    assert result.is_valid is False
    assert sanitised is None
    assert any("forbidden tag removed" in err for err in result.errors)


def test_validate_and_sanitise_svg_fails_on_external_url() -> None:
    svg = _first_approach_svg("invalid/svg-with-external-url.json")

    result, sanitised = validate_and_sanitise_svg(svg)
    assert result.is_valid is False
    assert sanitised is None
    assert any("external url attribute removed" in err for err in result.errors)


def test_validate_and_sanitise_svg_fails_on_data_uri() -> None:
    svg = (
        '<svg viewBox="0 0 800 200"><g id="linai"/><image href="data:image/png;base64,AAA"/></svg>'
    )

    result, sanitised = validate_and_sanitise_svg(svg)
    assert result.is_valid is False
    assert sanitised is None
    assert any("data uri" in err for err in result.errors)


def test_validate_and_sanitise_svg_fails_without_viewbox() -> None:
    svg = '<svg><g id="linai"/></svg>'

    result, sanitised = validate_and_sanitise_svg(svg)
    assert result.is_valid is False
    assert sanitised is None
    assert any("viewBox" in err for err in result.errors)


def test_validate_and_sanitise_svg_fails_with_non_svg_root() -> None:
    svg = '<g id="linai"/>'

    result, sanitised = validate_and_sanitise_svg(svg)
    assert result.is_valid is False
    assert sanitised is None
    assert any("root element" in err for err in result.errors)


def test_validate_and_sanitise_svg_fails_without_linai_id() -> None:
    svg = '<svg viewBox="0 0 800 200"><g id="not-linai"/></svg>'

    result, sanitised = validate_and_sanitise_svg(svg)
    assert result.is_valid is False
    assert sanitised is None
    assert any('id="linai"' in err for err in result.errors)


def test_validate_and_sanitise_svg_accepts_obstacle_mode_required_ids() -> None:
    svg = (
        '<svg viewBox="0 0 120 150">'
        '<g id="obstacle-root">'
        '<path id="obstacle-main" d="M10 140 L60 20 L110 140 Z"/>'
        '<g id="obstacle-animated-part"><path d="M60 20 C70 15 80 10 90 8"/>'
        '<animateTransform attributeName="transform" type="rotate" '
        'values="-3 60 20;3 60 20;-3 60 20" dur="1200ms" '
        'repeatCount="indefinite"/>'
        "</g>"
        "</g>"
        "</svg>"
    )

    result, sanitised = validate_and_sanitise_svg(
        svg,
        required_ids={"obstacle-root", "obstacle-main", "obstacle-animated-part"},
        animated_ids={"obstacle-animated-part"},
    )
    assert result.is_valid is True
    assert sanitised is not None
    assert 'id="obstacle-root"' in sanitised


def test_validate_and_sanitise_svg_accepts_animated_ids_via_href_target() -> None:
    svg = (
        '<svg viewBox="0 0 120 150" xmlns:xlink="http://www.w3.org/1999/xlink">'
        '<g id="obstacle-root">'
        '<path id="obstacle-main" d="M10 140 L60 20 L110 140 Z"/>'
        '<g id="obstacle-animated-part"><path d="M60 20 C70 15 80 10 90 8"/></g>'
        '<animateTransform xlink:href="#obstacle-animated-part" '
        'attributeName="transform" type="rotate" '
        'values="-3 60 20;3 60 20;-3 60 20" dur="1200ms" '
        'repeatCount="indefinite"/>'
        "</g>"
        "</svg>"
    )

    result, sanitised = validate_and_sanitise_svg(
        svg,
        required_ids={"obstacle-root", "obstacle-main", "obstacle-animated-part"},
        animated_ids={"obstacle-animated-part"},
    )
    assert result.is_valid is True
    assert sanitised is not None
    assert 'id="obstacle-root"' in sanitised
    assert "<ns0:" not in sanitised


def test_validate_and_sanitise_svg_fails_when_required_animated_id_is_static() -> None:
    svg = (
        '<svg viewBox="0 0 120 150">'
        '<g id="obstacle-root">'
        '<path id="obstacle-main" d="M10 140 L60 20 L110 140 Z"/>'
        '<g id="obstacle-animated-part"><path d="M60 20 C70 15 80 10 90 8"/></g>'
        "</g>"
        "</svg>"
    )

    result, sanitised = validate_and_sanitise_svg(
        svg,
        required_ids={"obstacle-root", "obstacle-main", "obstacle-animated-part"},
        animated_ids={"obstacle-animated-part"},
    )

    assert result.is_valid is False
    assert sanitised is None
    assert any("must contain an SVG animation tag" in err for err in result.errors)


def test_validate_and_sanitise_svg_fails_on_oversize_payload() -> None:
    payload = "a" * 600_000
    svg = f'<svg viewBox="0 0 800 200"><g id="linai">{payload}</g></svg>'

    result, sanitised = validate_and_sanitise_svg(svg)
    assert result.is_valid is False
    assert sanitised is None
    assert any("size exceeds max" in err for err in result.errors)


def test_validate_and_sanitise_svg_fails_on_clip_count_mismatch() -> None:
    svg = _first_approach_svg("valid_episode.json")

    result, sanitised = validate_and_sanitise_svg(
        svg,
        expected_clip_count=6,
        output_clip_count=5,
    )
    assert result.is_valid is False
    assert sanitised is None
    assert any("clip count" in err for err in result.errors)


def test_validate_and_sanitise_svg_fails_on_malformed_xml() -> None:
    result, sanitised = validate_and_sanitise_svg("<svg>")
    assert result.is_valid is False
    assert sanitised is None
    assert any("malformed svg xml" in err for err in result.errors)


def test_validate_and_sanitise_svg_fails_on_javascript_attribute() -> None:
    svg = '<svg viewBox="0 0 800 200"><g id="linai" onclick="javascript:evil()"/></svg>'

    result, sanitised = validate_and_sanitise_svg(svg)
    assert result.is_valid is False
    assert sanitised is None
    assert any("javascript" in err for err in result.errors)


def test_validate_and_sanitise_svg_raises_for_none_input() -> None:
    with pytest.raises(TypeError):
        validate_and_sanitise_svg(None)  # type: ignore[arg-type]


def test_svg_linter_helpers_cover_non_namespace_and_missing_parent_branch() -> None:
    assert local_name("{http://www.w3.org/2000/svg}g") == "g"
    assert local_name("svg") == "svg"

    root = ET.fromstring('<svg viewBox="0 0 800 200"><g id="linai"/></svg>')
    detached = ET.Element("script")
    assert find_parent(root, detached) is None


def test_validate_and_sanitise_svg_fails_when_required_animated_id_is_absent() -> None:
    """When animated_ids names an element that doesn't exist, return a clear error."""
    svg = '<svg viewBox="0 0 120 150"><g id="obstacle-root"><path id="obstacle-main"/></g></svg>'

    result, sanitised = validate_and_sanitise_svg(
        svg,
        required_ids={"obstacle-root", "obstacle-main"},
        animated_ids={"obstacle-animated-part"},
    )

    assert result.is_valid is False
    assert sanitised is None
    assert any("obstacle-animated-part" in err for err in result.errors)
