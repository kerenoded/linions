"""Unit tests for the canonical Linai template helper."""

from __future__ import annotations

from pathlib import Path

import pytest

import pipeline.media.linai_template as linai_template
from pipeline.media.linai_template import get_linai_part_ids, get_linai_template_svg


def test_get_linai_part_ids_returns_expected_ids_from_template() -> None:
    ids = get_linai_part_ids()

    assert ids == [
        "linai",
        "linai-trails",
        "linai-body",
        "linai-particles",
        "linai-mouth",
        "linai-eye-left",
        "linai-eye-right",
        "linai-inner-patterns",
    ]
    assert "ground-line" not in ids


def test_get_linai_template_svg_returns_canonical_template_markup() -> None:
    svg = get_linai_template_svg()

    assert svg.startswith("<svg")
    assert 'id="linai"' in svg
    assert 'id="linai-body"' in svg
    assert 'id="linai-inner-patterns"' in svg
    assert 'id="linai-particles"' in svg
    assert 'id="linai-trails"' in svg
    assert 'id="linai-mouth"' in svg
    assert 'id="linai-eye-left"' in svg
    assert 'id="linai-eye-right"' in svg
    assert 'id="linai-leg-left-group"' not in svg


def test_get_linai_template_svg_raises_clear_error_when_template_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    linai_template.get_linai_part_ids.cache_clear()
    linai_template.get_linai_template_svg.cache_clear()
    monkeypatch.setattr(linai_template, "_LINAI_TEMPLATE_PATH", tmp_path / "missing-template.svg")

    with pytest.raises(RuntimeError, match="Linai template SVG not found:"):
        linai_template.get_linai_template_svg()

    linai_template.get_linai_part_ids.cache_clear()
    linai_template.get_linai_template_svg.cache_clear()


def test_get_linai_part_ids_raises_when_template_is_invalid_xml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bad_svg = tmp_path / "bad.svg"
    bad_svg.write_text("<svg>not closed", encoding="utf-8")
    linai_template.get_linai_part_ids.cache_clear()
    monkeypatch.setattr(linai_template, "_LINAI_TEMPLATE_PATH", bad_svg)

    with pytest.raises(RuntimeError, match="Invalid Linai template SVG"):
        linai_template.get_linai_part_ids()

    linai_template.get_linai_part_ids.cache_clear()


def test_get_linai_part_ids_raises_when_linai_group_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bad_svg = tmp_path / "no-linai.svg"
    bad_svg.write_text('<svg viewBox="0 0 800 200"><g id="other"/></svg>', encoding="utf-8")
    linai_template.get_linai_part_ids.cache_clear()
    monkeypatch.setattr(linai_template, "_LINAI_TEMPLATE_PATH", bad_svg)

    with pytest.raises(RuntimeError, match='missing required id="linai"'):
        linai_template.get_linai_part_ids()

    linai_template.get_linai_part_ids.cache_clear()


def test_get_linai_template_svg_raises_when_template_is_invalid_xml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bad_svg = tmp_path / "bad.svg"
    bad_svg.write_text("<svg>not closed", encoding="utf-8")
    linai_template.get_linai_template_svg.cache_clear()
    monkeypatch.setattr(linai_template, "_LINAI_TEMPLATE_PATH", bad_svg)

    with pytest.raises(RuntimeError, match="Invalid Linai template SVG"):
        linai_template.get_linai_template_svg()

    linai_template.get_linai_template_svg.cache_clear()


def test_get_linai_template_svg_raises_when_linai_group_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bad_svg = tmp_path / "no-linai.svg"
    bad_svg.write_text('<svg viewBox="0 0 800 200"><g id="other"/></svg>', encoding="utf-8")
    linai_template.get_linai_template_svg.cache_clear()
    monkeypatch.setattr(linai_template, "_LINAI_TEMPLATE_PATH", bad_svg)

    with pytest.raises(RuntimeError, match='missing required id="linai"'):
        linai_template.get_linai_template_svg()

    linai_template.get_linai_template_svg.cache_clear()
