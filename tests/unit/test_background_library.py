"""Unit tests for the bundled background SVG library helpers."""

from __future__ import annotations

from pathlib import Path

import pipeline.media.background_library as background_library


def _make_library(tmp_path: Path, slugs: list[str]) -> Path:
    library_dir = tmp_path / "frontend" / "public" / "backgrounds"
    library_dir.mkdir(parents=True)
    for slug in slugs:
        (library_dir / f"{slug}.svg").write_text("<svg/>", encoding="utf-8")
    return library_dir


def test_get_background_svg_returns_known_library_asset(
    monkeypatch: object, tmp_path: Path
) -> None:
    library_dir = _make_library(tmp_path, ["tropical-blue-beach"])
    monkeypatch.setattr(background_library, "_LIBRARY_DIR", library_dir)

    assert background_library.get_background_svg("tropical-blue-beach") == "<svg/>"


def test_get_background_svg_returns_none_for_unknown_slug(
    monkeypatch: object, tmp_path: Path
) -> None:
    library_dir = _make_library(tmp_path, [])
    monkeypatch.setattr(background_library, "_LIBRARY_DIR", library_dir)

    assert background_library.get_background_svg("forest") is None


def test_list_background_library_names_returns_sorted_names(
    monkeypatch: object, tmp_path: Path
) -> None:
    library_dir = _make_library(tmp_path, ["tropical-blue-beach", "open-night-sky"])
    monkeypatch.setattr(background_library, "_LIBRARY_DIR", library_dir)

    assert background_library.list_background_library_names() == [
        "open-night-sky",
        "tropical-blue-beach",
    ]


# --- prompt_to_background_slug ---


def test_prompt_to_background_slug_extracts_3_meaningful_words() -> None:
    prompt = "Draw a full-canvas background of a tropical blue beach at midday."
    assert background_library.prompt_to_background_slug(prompt) == "tropical-blue-beach"


def test_prompt_to_background_slug_strips_stop_words() -> None:
    prompt = "Draw a background scene with glowing stars and a dark sky above."
    assert background_library.prompt_to_background_slug(prompt) == "glowing-stars-dark"


def test_prompt_to_background_slug_returns_background_on_all_stop_words() -> None:
    assert background_library.prompt_to_background_slug("draw the background") == "background"


# --- find_background_library_slug ---


def test_find_background_library_slug_matches_all_3_words_order_independent(
    monkeypatch: object, tmp_path: Path
) -> None:
    library_dir = _make_library(tmp_path, ["beach-sunny-tropical"])
    monkeypatch.setattr(background_library, "_LIBRARY_DIR", library_dir)

    # Keywords: tropical, blue, beach — only 2 of 3 match beach-sunny-tropical → no match
    # But keywords tropical, sunny, beach → all 3 match
    result = background_library.find_background_library_slug(
        "A tropical sunny beach with palm trees."
    )
    assert result == "beach-sunny-tropical"


def test_find_background_library_slug_returns_none_when_not_all_3_words_match(
    monkeypatch: object, tmp_path: Path
) -> None:
    library_dir = _make_library(tmp_path, ["tropical-blue-beach"])
    monkeypatch.setattr(background_library, "_LIBRARY_DIR", library_dir)

    # Keywords: tropical, sunny, beach — "blue" missing → no match
    result = background_library.find_background_library_slug(
        "A tropical sunny beach with waves."
    )
    assert result is None


def test_find_background_library_slug_ignores_non_3_word_slugs(
    monkeypatch: object, tmp_path: Path
) -> None:
    library_dir = _make_library(tmp_path, ["beach", "sunny-beach", "tropical-blue-beach-sunny"])
    monkeypatch.setattr(background_library, "_LIBRARY_DIR", library_dir)

    # Only 3-word slugs are eligible — 1-word and 4-word slugs are ignored
    result = background_library.find_background_library_slug(
        "A tropical blue beach midday scene."
    )
    assert result is None


def test_find_background_library_slug_returns_none_for_too_few_keywords(
    monkeypatch: object, tmp_path: Path
) -> None:
    library_dir = _make_library(tmp_path, ["tropical-blue-beach"])
    monkeypatch.setattr(background_library, "_LIBRARY_DIR", library_dir)

    # Only 1 meaningful word after stop word filtering
    result = background_library.find_background_library_slug("Draw the background.")
    assert result is None


def test_find_background_library_slug_uses_combined_texts(
    monkeypatch: object, tmp_path: Path
) -> None:
    library_dir = _make_library(tmp_path, ["tropical-blue-beach"])
    monkeypatch.setattr(background_library, "_LIBRARY_DIR", library_dir)

    # Keywords drawn from combined text: tropical, blue, beach (first 3 non-stop words)
    result = background_library.find_background_library_slug(
        "A tropical blue beach.",
        "Linai walks along the shore.",
    )
    assert result == "tropical-blue-beach"
