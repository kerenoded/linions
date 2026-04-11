"""Unit tests for published-episode validation helpers."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from pipeline.shared.published_episode import (
    validate_publish_path_segment,
    validate_published_episode_json,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _read_first_published_episode_json() -> str:
    """Return one real published episode JSON payload from the repo."""
    paths = sorted((PROJECT_ROOT / "episodes").glob("*/*/episode.json"))
    if not paths:
        msg = "Expected at least one published episode fixture in episodes/"
        raise RuntimeError(msg)
    return paths[0].read_text(encoding="utf-8")


def _mutate_first_approach_svg(transform: Callable[[str], str]) -> str:
    """Return a real published episode JSON payload with a mutated first approach clip."""
    episode = json.loads(_read_first_published_episode_json())
    original_svg = episode["acts"][0]["clips"]["approach"]
    episode["acts"][0]["clips"]["approach"] = transform(original_svg)
    return json.dumps(episode)


def test_validate_publish_path_segment_accepts_safe_segment() -> None:
    assert validate_publish_path_segment("kerenoded.dev-1", field_name="username") == (
        "kerenoded.dev-1"
    )


def test_validate_publish_path_segment_rejects_unsafe_segment() -> None:
    with pytest.raises(ValueError, match="username must contain only"):
        validate_publish_path_segment("../escape", field_name="username")


def test_validate_published_episode_json_accepts_valid_fixture() -> None:
    episode = validate_published_episode_json(_read_first_published_episode_json())
    assert episode.username
    assert episode.acts


def test_validate_published_episode_json_rejects_script_tag_fixture() -> None:
    with pytest.raises(ValueError, match="forbidden tag removed"):
        validate_published_episode_json(
            _mutate_first_approach_svg(
                lambda svg: svg.replace("</svg>", "<script>alert('x')</script></svg>", 1)
            )
        )


def test_validate_published_episode_json_rejects_external_url_fixture() -> None:
    with pytest.raises(ValueError, match="external url attribute removed"):
        validate_published_episode_json(
            _mutate_first_approach_svg(
                lambda svg: svg.replace(
                    "<svg ",
                    '<svg href="https://example.com/malicious.svg" ',
                    1,
                )
            )
        )
