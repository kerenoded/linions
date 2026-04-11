"""Unit tests for script validator rules (DESIGN.md §6.2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline import config
from pipeline.models import Act, Choice, DirectorOutput
from pipeline.validators.script_validator import validate_script

_BG_PROMPT = "Draw a simple background with gentle rolling hills and a clear blue sky above. " * 2

FIXTURES_DIR = Path("tests/fixtures")


def _load_fixture(path: str) -> dict:
    return json.loads((FIXTURES_DIR / path).read_text())


def _director_output_from_episode_fixture(path: str) -> DirectorOutput:
    fixture = _load_fixture(path)
    acts: list[Act] = []
    for act_json in fixture["acts"]:
        choices = [
            Choice(
                label=choice_json["label"],
                is_winning=choice_json["isWinning"],
                outcome_description=f"Outcome for {choice_json['label']}",
            )
            for choice_json in act_json["clips"]["choices"]
        ]
        acts.append(
            Act(
                act_index=act_json["actIndex"],
                obstacle_type=act_json["obstacleType"],
                approach_description="Linai approaches.",
                background_drawing_prompt=_BG_PROMPT,
                choices=choices,
            )
        )

    return DirectorOutput(
        title=fixture["title"],
        description=fixture["description"],
        acts=acts,
    )


def test_validate_script_passes_for_valid_fixture_mapped_output() -> None:
    script = _director_output_from_episode_fixture("valid_episode.json")
    assert len(script.acts) == 2
    assert all(len(act.choices) == 2 for act in script.acts)
    result = validate_script(
        script,
        preferred_obstacle_library_names=[a.obstacle_type for a in script.acts],
    )
    assert result.is_valid is True
    assert result.errors == []


def test_validate_script_fails_when_act_count_out_of_bounds() -> None:
    script = _director_output_from_episode_fixture("invalid/act-count-exceeds-maximum.json")
    result = validate_script(script)
    assert result.is_valid is False
    assert any("acts count" in err for err in result.errors)


def test_validate_script_fails_when_choice_count_out_of_bounds() -> None:
    script = _director_output_from_episode_fixture("valid_episode.json")
    script.acts[0].choices = [script.acts[0].choices[0]]

    result = validate_script(script)
    assert result.is_valid is False
    assert (
        f"act 0 choices count must be between {config.MIN_CHOICES_PER_ACT} "
        f"and {config.MAX_CHOICES_PER_ACT}; got 1"
    ) in result.errors


def test_validate_script_fails_when_missing_winning_choice() -> None:
    script = _director_output_from_episode_fixture("invalid/missing-winning-choice.json")
    result = validate_script(script)
    assert result.is_valid is False
    assert any("exactly one winning choice" in err for err in result.errors)


def test_validate_script_fails_when_title_too_long() -> None:
    script = _director_output_from_episode_fixture("valid_episode.json")
    script.title = "a" * 61

    result = validate_script(script)
    assert result.is_valid is False
    assert any("title must be 60" in err for err in result.errors)


def test_validate_script_fails_when_description_too_long() -> None:
    script = _director_output_from_episode_fixture("valid_episode.json")
    script.description = "a" * 121

    result = validate_script(script)
    assert result.is_valid is False
    assert any("description must be 120" in err for err in result.errors)


def test_validate_script_fails_when_choice_label_too_long() -> None:
    script = _director_output_from_episode_fixture("valid_episode.json")
    script.acts[0].choices[0].label = "a" * 41

    result = validate_script(script)
    assert result.is_valid is False
    assert any("label must be 40" in err for err in result.errors)


def test_validate_script_fails_when_act_index_not_sequential() -> None:
    script = _director_output_from_episode_fixture("valid_episode.json")
    script.acts[1].act_index = 5

    result = validate_script(script)
    assert result.is_valid is False
    assert any("act_index values must be sequential" in err for err in result.errors)


def test_validate_script_fails_when_duplicate_act_index() -> None:
    script = _director_output_from_episode_fixture("valid_episode.json")
    script.acts[1].act_index = 0

    result = validate_script(script)
    assert result.is_valid is False
    assert any("duplicate act_index" in err for err in result.errors)


def test_validate_script_fails_when_obstacle_type_slug_invalid() -> None:
    script = _director_output_from_episode_fixture("valid_episode.json")
    invalid_act = Act.model_construct(
        act_index=script.acts[0].act_index,
        obstacle_type="Lava Pit!",  # bypass pydantic validation intentionally
        approach_description=script.acts[0].approach_description,
        choices=script.acts[0].choices,
        background_drawing_prompt=_BG_PROMPT,
    )
    script.acts[0] = invalid_act

    result = validate_script(
        script,
        preferred_obstacle_library_names=[a.obstacle_type for a in script.acts],
    )
    assert result.is_valid is False
    assert any("invalid obstacle_type slug" in err for err in result.errors)


def test_validate_script_raises_for_none_input() -> None:
    with pytest.raises(TypeError):
        validate_script(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# drawing_prompt and background_drawing_prompt rules
# ---------------------------------------------------------------------------


def _make_valid_script() -> DirectorOutput:
    """Return a minimal valid DirectorOutput for drawing prompt tests."""
    return DirectorOutput(
        title="Test Episode",
        description="A test episode.",
        acts=[
            Act(
                act_index=0,
                obstacle_type="wall",
                approach_description="Linai floats up to a wall.",
                choices=[
                    Choice(
                        label="Climb",
                        is_winning=True,
                        outcome_description="She climbs over.",
                    ),
                    Choice(
                        label="Kick",
                        is_winning=False,
                        outcome_description="It doesn't budge.",
                    ),
                ],
                background_drawing_prompt=_BG_PROMPT,
            ),
            Act(
                act_index=1,
                obstacle_type="hole",
                approach_description="A hole appears.",
                choices=[
                    Choice(
                        label="Jump",
                        is_winning=True,
                        outcome_description="She jumps over.",
                    ),
                    Choice(
                        label="Sit",
                        is_winning=False,
                        outcome_description="She sits and waits.",
                    ),
                ],
                background_drawing_prompt=_BG_PROMPT,
            ),
        ],
    )


def test_validate_script_fails_when_drawing_prompt_missing_for_non_library_obstacle() -> None:
    """Non-library obstacles must have a drawing_prompt."""
    script = _make_valid_script()
    script.acts[0].obstacle_type = "dragon"
    script.acts[0].drawing_prompt = None
    result = validate_script(script, preferred_obstacle_library_names=["wall", "hole"])
    assert not result.is_valid
    assert any("drawing_prompt" in e for e in result.errors)


def test_validate_script_fails_when_drawing_prompt_too_short() -> None:
    """drawing_prompt must be at least 50 characters when present."""
    script = _make_valid_script()
    script.acts[0].obstacle_type = "dragon"
    script.acts[0].drawing_prompt = "Draw a dragon."
    result = validate_script(script, preferred_obstacle_library_names=["wall", "hole"])
    assert not result.is_valid
    assert any("50 characters" in e for e in result.errors)


def test_validate_script_passes_when_drawing_prompt_null_for_library_obstacle() -> None:
    """Library obstacles may have drawing_prompt=None."""
    script = _make_valid_script()
    script.acts[0].obstacle_type = "wall"
    script.acts[0].drawing_prompt = None
    result = validate_script(script, preferred_obstacle_library_names=["wall", "hole"])
    assert result.is_valid


def test_validate_script_fails_when_background_drawing_prompt_too_short() -> None:
    """background_drawing_prompt must be at least 50 characters."""
    script = _make_valid_script()
    script.acts[0].background_drawing_prompt = "Short."
    result = validate_script(script, preferred_obstacle_library_names=["wall"])
    assert not result.is_valid
    assert any("background_drawing_prompt" in e for e in result.errors)


def test_validate_script_passes_with_valid_drawing_and_background_prompts() -> None:
    """Valid prompts pass validation."""
    script = _make_valid_script()
    script.acts[0].obstacle_type = "dragon"
    script.acts[0].drawing_prompt = (
        "Draw a detailed dragon with scales, wings, and a long tail. " * 2
    )
    script.acts[0].background_drawing_prompt = (
        "Draw a mountain landscape with snow-capped peaks and a river. " * 2
    )
    result = validate_script(script, preferred_obstacle_library_names=["wall", "hole"])
    assert result.is_valid
