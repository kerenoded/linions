"""Unit tests for pipeline models."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from pipeline.models import (
    Act,
    AnimatorInput,
    AnimatorOutput,
    Choice,
    ClipManifest,
    DirectorInput,
    DirectorOutput,
    DrawingInput,
    DrawingOutput,
    Episode,
    EpisodeAct,
    EpisodeChoice,
    EpisodeClips,
    Keyframe,
    PartNote,
    RendererInput,
    RendererOutput,
    SvgClip,
)

FIXTURES_DIR = Path("tests/fixtures")

_BG_PROMPT = "Draw a simple background with gentle rolling hills and a clear blue sky above. " * 2


def _load_fixture(path: str) -> dict:
    return json.loads((FIXTURES_DIR / path).read_text())


# ---------------------------------------------------------------------------
# DirectorInput
# ---------------------------------------------------------------------------


def test_director_input_requires_all_explicit_fields() -> None:
    model = DirectorInput(
        prompt="Linai meets a wall",
        username="somedev",
        job_id="job-1",
        session_id="session-1",
        rag_context="context",
        preferred_obstacle_library_names=["wall", "bird"],
    )

    assert model.prompt == "Linai meets a wall"
    assert model.session_id == "session-1"
    assert model.preferred_obstacle_library_names == ["wall", "bird"]


def test_director_input_rejects_missing_required_field() -> None:
    with pytest.raises(ValidationError):
        DirectorInput(prompt="x", username="dev", job_id="j1")  # type: ignore[call-arg]


def test_director_input_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        DirectorInput(
            prompt="x",
            username="dev",
            job_id="j1",
            session_id="s1",
            rag_context="ctx",
            extra_field="oops",
        )


# ---------------------------------------------------------------------------
# Choice
# ---------------------------------------------------------------------------


def test_choice_includes_outcome_description() -> None:
    choice = Choice(
        label="Knock politely",
        is_winning=True,
        outcome_description="Linai gets a warm smile and a clear path.",
    )

    assert choice.outcome_description.startswith("Linai")


def test_choice_rejects_missing_label() -> None:
    with pytest.raises(ValidationError):
        Choice(is_winning=True, outcome_description="desc")  # type: ignore[call-arg]


def test_choice_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        Choice(label="Go left", is_winning=False, outcome_description="desc", unknown="x")


# ---------------------------------------------------------------------------
# Act
# ---------------------------------------------------------------------------


def test_act_accepts_valid_obstacle_types() -> None:
    obstacles = ("wall", "bird", "hot-air-balloon", "fire-dragon")
    for obstacle in obstacles:
        act = Act(
            act_index=0,
            obstacle_type=obstacle,
            approach_description="Linai approaches",
            choices=[],
            background_drawing_prompt=_BG_PROMPT,
        )
        assert act.obstacle_type == obstacle


def test_act_rejects_invalid_obstacle_type() -> None:
    with pytest.raises(ValidationError):
        Act(
            act_index=0,
            obstacle_type="Dragon!",
            approach_description="Linai approaches",
            choices=[],
            background_drawing_prompt=_BG_PROMPT,
        )


def test_act_rejects_missing_required_field() -> None:
    with pytest.raises(ValidationError):
        Act(act_index=0, obstacle_type="wall", choices=[])  # type: ignore[call-arg]


def test_act_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        Act(
            act_index=0,
            obstacle_type="wall",
            approach_description="desc",
            choices=[],
            background_drawing_prompt=_BG_PROMPT,
            surprise="yes",
        )


def test_act_drawing_prompt_defaults_to_none() -> None:
    """drawing_prompt is optional and defaults to None for library obstacles."""
    act = Act(
        act_index=0,
        obstacle_type="wall",
        approach_description="Linai floats up to a wall.",
        choices=[
            Choice(label="Climb", is_winning=True, outcome_description="She climbs over."),
            Choice(label="Kick", is_winning=False, outcome_description="It doesn't budge."),
        ],
        background_drawing_prompt=_BG_PROMPT,
    )
    assert act.drawing_prompt is None


def test_act_drawing_prompt_accepts_string() -> None:
    """drawing_prompt accepts a rich prompt string for non-library obstacles."""
    prompt = "Draw a detailed knight with plate armor and a plumed helmet. " * 3
    act = Act(
        act_index=0,
        obstacle_type="knight",
        approach_description="A knight blocks the path.",
        choices=[
            Choice(label="Fight", is_winning=True, outcome_description="She wins."),
            Choice(label="Run", is_winning=False, outcome_description="She trips."),
        ],
        drawing_prompt=prompt,
        background_drawing_prompt=_BG_PROMPT,
    )
    assert act.drawing_prompt == prompt


def test_act_background_drawing_prompt_required() -> None:
    """background_drawing_prompt is required on every act."""
    with pytest.raises(ValidationError):
        Act(
            act_index=0,
            obstacle_type="wall",
            approach_description="Linai floats up.",
            choices=[
                Choice(label="Climb", is_winning=True, outcome_description="Over."),
                Choice(label="Kick", is_winning=False, outcome_description="Nope."),
            ],
            # background_drawing_prompt intentionally omitted
        )


# ---------------------------------------------------------------------------
# DirectorOutput
# ---------------------------------------------------------------------------


def test_director_output_accepts_valid_data() -> None:
    output = DirectorOutput(title="A Short Walk", description="Linai meets a wall.", acts=[])
    assert output.title == "A Short Walk"


def test_director_output_rejects_missing_title() -> None:
    with pytest.raises(ValidationError):
        DirectorOutput(description="desc", acts=[])  # type: ignore[call-arg]


def test_director_output_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        DirectorOutput(title="T", description="D", acts=[], extra="x")


# ---------------------------------------------------------------------------
# AnimatorInput
# ---------------------------------------------------------------------------


def test_animator_input_includes_config_driven_fields() -> None:
    model = AnimatorInput(
        job_id="job-1",
        session_id="session-1",
        acts=[],
        walk_duration_seconds=8,
        canvas_width=800,
        canvas_height=200,
        ground_line_y=160,
        handoff_character_x=160,
    )

    assert model.canvas_width == 800
    assert model.ground_line_y == 160
    assert model.handoff_character_x == 160
    assert model.requires_handoff_in is False
    assert model.requires_handoff_out is False


def test_animator_input_accepts_explicit_handoff_flags() -> None:
    model = AnimatorInput(
        job_id="job-1",
        session_id="session-1",
        acts=[],
        walk_duration_seconds=8,
        canvas_width=800,
        canvas_height=200,
        ground_line_y=160,
        handoff_character_x=160,
        requires_handoff_in=True,
        requires_handoff_out=False,
    )

    assert model.requires_handoff_in is True
    assert model.requires_handoff_out is False


def test_animator_input_rejects_missing_canvas_fields() -> None:
    with pytest.raises(ValidationError):
        AnimatorInput(job_id="j", session_id="s", acts=[], walk_duration_seconds=8)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Keyframe
# ---------------------------------------------------------------------------


def test_keyframe_accepts_valid_data() -> None:
    kf = Keyframe(
        time_ms=0,
        character_x=100.0,
        character_y=160.0,
        support_y=160.0,
        is_grounded=True,
        is_handoff_pose=False,
        expression="trying to stay brave",
        action="steps back nervously",
        motion_note="hesitates before retreating",
        part_notes=[PartNote(target_id="linai-mouth", note="small tense mouth")],
    )
    assert kf.time_ms == 0


def test_keyframe_accepts_open_expression_and_action_text() -> None:
    kf = Keyframe(
        time_ms=0,
        character_x=100.0,
        character_y=160.0,
        support_y=160.0,
        is_grounded=True,
        is_handoff_pose=False,
        expression="trying not to cry but pretending otherwise",
        action="sits beside the obstacle and glances up at it",
    )

    assert kf.expression.startswith("trying")
    assert kf.action.startswith("sits")


def test_part_note_rejects_empty_note() -> None:
    with pytest.raises(ValidationError):
        PartNote(target_id="linai-mouth", note="")


def test_keyframe_rejects_empty_expression_or_action() -> None:
    with pytest.raises(ValidationError):
        Keyframe(
            time_ms=0,
            character_x=100.0,
            character_y=160.0,
            support_y=160.0,
            is_grounded=True,
            is_handoff_pose=False,
            expression="",
            action="walks carefully",
        )
    with pytest.raises(ValidationError):
        Keyframe(
            time_ms=0,
            character_x=100.0,
            character_y=160.0,
            support_y=160.0,
            is_grounded=True,
            is_handoff_pose=False,
            expression="worried",
            action="",
        )


def test_keyframe_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        Keyframe(
            time_ms=0,
            character_x=100.0,
            character_y=160.0,
            support_y=160.0,
            is_grounded=True,
            is_handoff_pose=False,
            expression="neutral",
            action="walk",
            extra="x",
        )


# ---------------------------------------------------------------------------
# ClipManifest
# ---------------------------------------------------------------------------


def test_clip_manifest_accepts_none_choice_index_for_approach() -> None:
    clip = ClipManifest(
        act_index=0,
        obstacle_type="wall",
        branch="approach",
        choice_index=None,
        duration_ms=5000,
        keyframes=[],
        obstacle_x=400.0,
    )
    assert clip.choice_index is None
    assert clip.obstacle_svg_override is None


def test_clip_manifest_accepts_int_choice_index_for_win() -> None:
    clip = ClipManifest(
        act_index=0,
        obstacle_type="bird",
        branch="win",
        choice_index=1,
        duration_ms=3000,
        keyframes=[],
        obstacle_x=400.0,
    )
    assert clip.choice_index == 1


def test_clip_manifest_rejects_invalid_branch() -> None:
    with pytest.raises(ValidationError):
        ClipManifest(
            act_index=0,
            obstacle_type="wall",
            branch="intro",  # type: ignore[arg-type]
            choice_index=None,
            duration_ms=3000,
            keyframes=[],
            obstacle_x=400.0,
        )


def test_clip_manifest_background_svg_defaults_to_none() -> None:
    """ClipManifest.background_svg is optional and defaults to None."""
    clip = ClipManifest(
        act_index=0,
        obstacle_type="wall",
        branch="approach",
        choice_index=None,
        duration_ms=8000,
        keyframes=[],
        obstacle_x=400,
    )
    assert clip.background_svg is None


def test_clip_manifest_background_svg_accepts_string() -> None:
    """ClipManifest.background_svg accepts an SVG string."""
    bg = '<svg viewBox="0 0 800 200"><rect fill="#336"/></svg>'
    clip = ClipManifest(
        act_index=0,
        obstacle_type="wall",
        branch="approach",
        choice_index=None,
        duration_ms=8000,
        keyframes=[],
        obstacle_x=400,
        background_svg=bg,
    )
    assert clip.background_svg == bg


def test_clip_manifest_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ClipManifest(
            act_index=0,
            obstacle_type="wall",
            branch="approach",
            choice_index=None,
            duration_ms=3000,
            keyframes=[],
            obstacle_x=400.0,
            surprise="yes",
        )


# ---------------------------------------------------------------------------
# AnimatorOutput
# ---------------------------------------------------------------------------


def test_animator_output_accepts_empty_clips() -> None:
    output = AnimatorOutput(clips=[])
    assert output.clips == []


def test_animator_output_rejects_missing_clips() -> None:
    with pytest.raises(ValidationError):
        AnimatorOutput()  # type: ignore[call-arg]


def test_animator_output_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        AnimatorOutput(clips=[], extra="x")


# ---------------------------------------------------------------------------
# RendererInput
# ---------------------------------------------------------------------------


def test_renderer_input_defaults_character_template_id() -> None:
    model = RendererInput(job_id="job-1", session_id="session-1", clips=[])
    assert model.character_template_id == "linai-v2"


def test_renderer_input_accepts_custom_template_id() -> None:
    model = RendererInput(job_id="j", session_id="s", clips=[], character_template_id="linoi-v1")
    assert model.character_template_id == "linoi-v1"


def test_renderer_input_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        RendererInput(job_id="j", session_id="s", clips=[], surprise="yes")


# ---------------------------------------------------------------------------
# Drawing models
# ---------------------------------------------------------------------------


def test_drawing_input_accepts_valid_slug() -> None:
    model = DrawingInput(
        job_id="job-1",
        session_id="session-1",
        obstacle_type="dragon",
        drawing_prompt="Draw a dragon with scales and wings. " * 3,
    )
    assert model.obstacle_type == "dragon"


def test_drawing_input_rejects_invalid_slug() -> None:
    with pytest.raises(ValidationError):
        DrawingInput(
            job_id="job-1",
            session_id="session-1",
            obstacle_type="Dragon!",
            drawing_prompt="Draw a dragon.",
        )


def test_drawing_input_requires_drawing_prompt() -> None:
    """DrawingInput now requires a drawing_prompt string."""
    with pytest.raises(ValidationError):
        DrawingInput(
            job_id="job-1",
            session_id="sess-1",
            obstacle_type="knight",
            # drawing_prompt intentionally omitted
        )


def test_drawing_input_obstacle_type_default() -> None:
    """DrawingInput drawing_type defaults to 'obstacle'."""
    di = DrawingInput(
        job_id="job-1",
        session_id="sess-1",
        obstacle_type="knight",
        drawing_prompt="Draw a knight with armor and sword. " * 3,
    )
    assert di.drawing_type == "obstacle"


def test_drawing_input_background_type() -> None:
    """DrawingInput accepts drawing_type='background'."""
    di = DrawingInput(
        job_id="job-1",
        session_id="sess-1",
        obstacle_type="forest-bg",
        drawing_prompt="Draw a forest background with tall trees. " * 3,
        drawing_type="background",
    )
    assert di.drawing_type == "background"


def test_drawing_output_accepts_svg_payload() -> None:
    model = DrawingOutput(
        svg=(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 150">'
            '<g id="obstacle-root"/>'
            "</svg>"
        )
    )
    assert model.svg.startswith("<svg")


# ---------------------------------------------------------------------------
# SvgClip
# ---------------------------------------------------------------------------


def test_svg_clip_accepts_valid_data() -> None:
    clip = SvgClip(
        act_index=0,
        branch="approach",
        choice_index=None,
        svg='<svg viewBox="0 0 800 200"><g id="linai"/></svg>',
        duration_ms=4000,
    )
    assert clip.branch == "approach"
    assert clip.choice_index is None


def test_svg_clip_rejects_invalid_branch() -> None:
    with pytest.raises(ValidationError):
        SvgClip(
            act_index=0,
            branch="setup",  # type: ignore[arg-type]
            choice_index=None,
            svg="<svg/>",
            duration_ms=1000,
        )


def test_svg_clip_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        SvgClip(
            act_index=0,
            branch="win",
            choice_index=0,
            svg="<svg/>",
            duration_ms=1000,
            extra="x",
        )


# ---------------------------------------------------------------------------
# RendererOutput
# ---------------------------------------------------------------------------


def test_renderer_output_accepts_empty_clips() -> None:
    output = RendererOutput(clips=[])
    assert output.clips == []


def test_renderer_output_rejects_missing_clips() -> None:
    with pytest.raises(ValidationError):
        RendererOutput()  # type: ignore[call-arg]


def test_renderer_output_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        RendererOutput(clips=[], extra="x")


# ---------------------------------------------------------------------------
# EpisodeChoice (alias fields)
# ---------------------------------------------------------------------------


def test_episode_choice_accepts_winning_choice_via_aliases() -> None:
    choice = EpisodeChoice.model_validate(
        {
            "choiceIndex": 1,
            "label": "Jump over",
            "isWinning": True,
            "outcomeText": "Linai hops neatly over the obstacle.",
            "winClip": "<svg/>",
            "failClip": None,
        }
    )
    assert choice.choice_index == 1
    assert choice.is_winning is True
    assert choice.outcome_text == "Linai hops neatly over the obstacle."
    assert choice.win_clip == "<svg/>"


def test_episode_choice_accepts_losing_choice_via_aliases() -> None:
    choice = EpisodeChoice.model_validate(
        {
            "choiceIndex": 0,
            "label": "Run away",
            "isWinning": False,
            "outcomeText": "Linai backs off and regroups.",
            "winClip": None,
            "failClip": "<svg/>",
        }
    )
    assert choice.choice_index == 0
    assert choice.fail_clip == "<svg/>"


def test_episode_choice_rejects_winning_choice_with_missing_win_clip() -> None:
    with pytest.raises(ValidationError):
        EpisodeChoice.model_validate(
            {
                "choiceIndex": 1,
                "label": "Jump",
                "isWinning": True,
                "outcomeText": "Linai tries a leap.",
                "winClip": None,
                "failClip": None,
            }
        )


def test_episode_choice_rejects_losing_choice_with_missing_fail_clip() -> None:
    with pytest.raises(ValidationError):
        EpisodeChoice.model_validate(
            {
                "choiceIndex": 0,
                "label": "Run",
                "isWinning": False,
                "outcomeText": "Linai retreats.",
                "winClip": None,
                "failClip": None,
            }
        )


# ---------------------------------------------------------------------------
# EpisodeClips
# ---------------------------------------------------------------------------


def test_episode_clips_accepts_valid_data() -> None:
    clips = EpisodeClips(approach="<svg/>", choices=[])
    assert clips.approach == "<svg/>"


def test_episode_clips_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        EpisodeClips(approach="<svg/>", choices=[], extra="x")


# ---------------------------------------------------------------------------
# EpisodeAct (alias fields)
# ---------------------------------------------------------------------------


def test_episode_act_accepts_valid_data_via_aliases() -> None:
    act = EpisodeAct.model_validate(
        {
            "actIndex": 0,
            "obstacleType": "wall",
            "approachText": "Linai studies the wall.",
            "clips": {"approach": "<svg/>", "choices": []},
        }
    )
    assert act.act_index == 0
    assert act.obstacle_type == "wall"
    assert act.approach_text == "Linai studies the wall."


def test_episode_act_rejects_invalid_obstacle_type() -> None:
    with pytest.raises(ValidationError):
        EpisodeAct.model_validate(
            {
                "actIndex": 0,
                "obstacleType": "Volcano!",
                "approachText": "Linai studies the wall.",
                "clips": {"approach": "<svg/>", "choices": []},
            }
        )


def test_episode_act_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        EpisodeAct.model_validate(
            {
                "actIndex": 0,
                "obstacleType": "wall",
                "approachText": "Linai studies the wall.",
                "clips": {"approach": "<svg/>", "choices": []},
                "extra": "x",
            }
        )


# ---------------------------------------------------------------------------
# Episode (fixture-based and validator tests)
# ---------------------------------------------------------------------------


def test_episode_model_accepts_valid_fixture() -> None:
    episode = Episode.model_validate(_load_fixture("valid_episode.json"))
    assert episode.schema_version == "1.0"
    assert episode.username == "somedev"


def test_episode_rejects_missing_uuid_fixture() -> None:
    with pytest.raises(ValidationError):
        Episode.model_validate(_load_fixture("invalid/missing-uuid.json"))


def test_episode_rejects_empty_username_fixture() -> None:
    with pytest.raises(ValidationError):
        Episode.model_validate(_load_fixture("invalid/empty-username.json"))


def test_episode_rejects_invalid_schema_version() -> None:
    with pytest.raises(ValidationError):
        Episode.model_validate(_load_fixture("invalid/invalid-schema-version.json"))


def test_episode_rejects_winning_choice_without_win_clip() -> None:
    episode_json = _load_fixture("valid_episode.json")
    episode_json["acts"][0]["clips"]["choices"][1]["winClip"] = None

    with pytest.raises(ValidationError):
        Episode.model_validate(episode_json)


def test_episode_rejects_losing_choice_with_win_clip() -> None:
    episode_json = _load_fixture("valid_episode.json")
    episode_json["acts"][0]["clips"]["choices"][0]["winClip"] = "<svg/>"

    with pytest.raises(ValidationError):
        Episode.model_validate(episode_json)


def test_episode_rejects_winning_choice_with_fail_clip() -> None:
    episode_json = _load_fixture("valid_episode.json")
    episode_json["acts"][0]["clips"]["choices"][1]["failClip"] = "<svg/>"

    with pytest.raises(ValidationError):
        Episode.model_validate(episode_json)


def test_episode_rejects_losing_choice_without_fail_clip() -> None:
    episode_json = _load_fixture("valid_episode.json")
    episode_json["acts"][0]["clips"]["choices"][0]["failClip"] = None

    with pytest.raises(ValidationError):
        Episode.model_validate(episode_json)


def test_episode_rejects_act_count_mismatch() -> None:
    episode_json = _load_fixture("valid_episode.json")
    episode_json["actCount"] = 99  # wrong — does not match len(acts)

    with pytest.raises(ValidationError):
        Episode.model_validate(episode_json)


def test_episode_rejects_extra_root_fields() -> None:
    episode_json = _load_fixture("valid_episode.json")
    episode_json["unknownField"] = "oops"

    with pytest.raises(ValidationError):
        Episode.model_validate(episode_json)
