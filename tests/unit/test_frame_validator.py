"""Unit tests for frame validator rules (DESIGN.md §6.3)."""

from __future__ import annotations

import pytest

from pipeline import config
from pipeline.models import (
    Act,
    AnimatorInput,
    AnimatorOutput,
    Choice,
    ClipManifest,
    Keyframe,
    PartNote,
)
from pipeline.validators.frame_repairs import repair_animator_keyframe_bounds
from pipeline.validators.frame_validator import validate_frames

_BG_PROMPT = "Draw a simple background with gentle rolling hills and a clear blue sky above. " * 2


def _make_animator_input() -> AnimatorInput:
    return AnimatorInput(
        job_id="job-1",
        session_id="session-1",
        acts=[
            Act(
                act_index=0,
                obstacle_type="wall",
                approach_description="Linai approaches a wall.",
                background_drawing_prompt=_BG_PROMPT,
                choices=[
                    Choice(
                        label="Jump",
                        is_winning=True,
                        outcome_description="Linai clears the wall.",
                    ),
                    Choice(
                        label="Push",
                        is_winning=False,
                        outcome_description="Linai bounces back.",
                    ),
                ],
            )
        ],
        walk_duration_seconds=8,
        canvas_width=800,
        canvas_height=200,
        ground_line_y=160,
        handoff_character_x=config.HANDOFF_CHARACTER_X,
    )


def _make_two_act_animator_input() -> AnimatorInput:
    return AnimatorInput(
        job_id="job-2",
        session_id="session-2",
        acts=[
            Act(
                act_index=0,
                obstacle_type="wall",
                approach_description="Linai approaches a wall.",
                background_drawing_prompt=_BG_PROMPT,
                choices=[
                    Choice(
                        label="Jump",
                        is_winning=True,
                        outcome_description="Linai clears the wall.",
                    ),
                    Choice(
                        label="Push",
                        is_winning=False,
                        outcome_description="Linai bounces back.",
                    ),
                ],
            ),
            Act(
                act_index=1,
                obstacle_type="bird",
                approach_description="Linai meets a bird after the wall.",
                background_drawing_prompt=_BG_PROMPT,
                choices=[
                    Choice(
                        label="Wave",
                        is_winning=True,
                        outcome_description="The bird smiles.",
                    ),
                    Choice(
                        label="Hide",
                        is_winning=False,
                        outcome_description="Linai trips.",
                    ),
                ],
            ),
        ],
        walk_duration_seconds=8,
        canvas_width=800,
        canvas_height=200,
        ground_line_y=160,
        handoff_character_x=config.HANDOFF_CHARACTER_X,
    )


def _make_valid_clip(act_index: int, branch: str, choice_index: int | None) -> ClipManifest:
    return ClipManifest(
        act_index=act_index,
        obstacle_type="wall",
        branch=branch,
        choice_index=choice_index,
        duration_ms=1000,
        obstacle_x=400,
        keyframes=[
            Keyframe(
                time_ms=0,
                character_x=40,
                character_y=160,
                support_y=160,
                is_grounded=True,
                is_handoff_pose=False,
                expression="neutral",
                action="walk",
                part_notes=[
                    PartNote(
                        target_id="linai-inner-patterns",
                        note="small curious sparkles gather inside the cloud",
                    )
                ],
            ),
            Keyframe(
                time_ms=500,
                character_x=config.HANDOFF_CHARACTER_X,
                character_y=160,
                support_y=160,
                is_grounded=True,
                is_handoff_pose=False,
                expression="happy",
                action="react",
            ),
        ],
    )


def _make_valid_output() -> AnimatorOutput:
    return AnimatorOutput(
        clips=[
            _make_valid_clip(0, "approach", None),
            _make_valid_clip(0, "win", 0),
            _make_valid_clip(0, "fail", 1),
        ]
    )


def test_validate_frames_passes_for_valid_manifest() -> None:
    result = validate_frames(_make_valid_output(), _make_animator_input())
    assert result.is_valid is True
    assert result.errors == []


def test_validate_frames_fails_when_character_x_out_of_bounds() -> None:
    output = _make_valid_output()
    output.clips[0].keyframes[0].character_x = 9999

    result = validate_frames(output, _make_animator_input())
    assert result.is_valid is False
    assert any("character_x out of bounds" in err for err in result.errors)


def test_validate_frames_fails_when_grounded_character_y_leaves_support_line() -> None:
    output = _make_valid_output()
    output.clips[0].keyframes[0].character_y = 170

    result = validate_frames(output, _make_animator_input())
    assert result.is_valid is False
    assert any(
        f"grounded keyframe character_y outside support_y±{config.SUPPORT_Y_TOLERANCE_PX}" in err
        for err in result.errors
    )


def test_validate_frames_fails_when_character_y_rises_too_high_for_frame() -> None:
    output = _make_valid_output()
    output.clips[0].keyframes[0].character_y = config.MIN_CHARACTER_Y_IN_FRAME_PX - 1

    result = validate_frames(output, _make_animator_input())
    assert result.is_valid is False
    assert any("must be at least" in err and "keep Linai in frame" in err for err in result.errors)


def test_validate_frames_allows_small_grounded_vertical_drift_for_expressive_pose() -> None:
    output = _make_valid_output()
    output.clips[0].keyframes[0].character_y = 155

    result = validate_frames(output, _make_animator_input())
    assert result.is_valid is True


def test_validate_frames_allows_airborne_keyframe_below_support_line() -> None:
    output = _make_valid_output()
    output.clips[0].keyframes[0].is_grounded = False
    output.clips[0].keyframes[0].character_y = 190

    result = validate_frames(output, _make_animator_input())
    assert result.is_valid is True


def test_validate_frames_allows_non_final_resolution_to_end_without_handoff_pose() -> None:
    output = AnimatorOutput(
        clips=[
            _make_valid_clip(0, "approach", None),
            _make_valid_clip(0, "win", 0),
            _make_valid_clip(0, "fail", 1),
            _make_valid_clip(1, "approach", None),
            _make_valid_clip(1, "win", 0),
            _make_valid_clip(1, "fail", 1),
        ]
    )
    for clip in output.clips[3:]:
        clip.obstacle_type = "bird"
    output.clips[3].keyframes[0].is_handoff_pose = True
    output.clips[3].keyframes[0].character_x = config.HANDOFF_CHARACTER_X

    result = validate_frames(output, _make_two_act_animator_input())
    assert result.is_valid is True
    assert result.errors == []


def test_validate_frames_requires_handoff_pose_on_later_approach_start() -> None:
    output = AnimatorOutput(
        clips=[
            _make_valid_clip(0, "approach", None),
            _make_valid_clip(0, "win", 0),
            _make_valid_clip(0, "fail", 1),
            _make_valid_clip(1, "approach", None),
            _make_valid_clip(1, "win", 0),
            _make_valid_clip(1, "fail", 1),
        ]
    )
    output.clips[1].keyframes[-1].is_handoff_pose = True
    output.clips[2].keyframes[-1].is_handoff_pose = True

    result = validate_frames(output, _make_two_act_animator_input())
    assert result.is_valid is False
    assert any(
        "approach clip must start with exactly one handoff pose" in err for err in result.errors
    )


def test_validate_frames_rejects_handoff_pose_outside_act_boundary() -> None:
    output = _make_valid_output()
    output.clips[0].keyframes[0].is_handoff_pose = True

    result = validate_frames(output, _make_animator_input())
    assert result.is_valid is False
    assert any(
        "must not set is_handoff_pose outside an act boundary" in err for err in result.errors
    )


def test_validate_frames_rejects_airborne_handoff_pose() -> None:
    output = AnimatorOutput(
        clips=[
            _make_valid_clip(0, "approach", None),
            _make_valid_clip(0, "win", 0),
            _make_valid_clip(0, "fail", 1),
            _make_valid_clip(1, "approach", None),
            _make_valid_clip(1, "win", 0),
            _make_valid_clip(1, "fail", 1),
        ]
    )
    output.clips[1].keyframes[-1].is_handoff_pose = True
    output.clips[1].keyframes[-1].is_grounded = False
    output.clips[2].keyframes[-1].is_handoff_pose = True
    output.clips[3].keyframes[0].is_handoff_pose = True

    result = validate_frames(output, _make_two_act_animator_input())
    assert result.is_valid is False
    assert any("handoff pose must be grounded" in err for err in result.errors)


def test_validate_frames_rejects_handoff_pose_at_wrong_x_position() -> None:
    output = AnimatorOutput(
        clips=[
            _make_valid_clip(0, "approach", None),
            _make_valid_clip(0, "win", 0),
            _make_valid_clip(0, "fail", 1),
            _make_valid_clip(1, "approach", None),
            _make_valid_clip(1, "win", 0),
            _make_valid_clip(1, "fail", 1),
        ]
    )
    output.clips[1].keyframes[-1].is_handoff_pose = True
    output.clips[1].keyframes[-1].character_x = 280
    output.clips[2].keyframes[-1].is_handoff_pose = True
    output.clips[3].keyframes[0].is_handoff_pose = True

    result = validate_frames(output, _make_two_act_animator_input())
    assert result.is_valid is False
    assert any("handoff pose character_x must be within" in err for err in result.errors)


def test_validate_frames_rejects_handoff_pose_at_wrong_y_position() -> None:
    output = AnimatorOutput(
        clips=[
            _make_valid_clip(0, "approach", None),
            _make_valid_clip(0, "win", 0),
            _make_valid_clip(0, "fail", 1),
            _make_valid_clip(1, "approach", None),
            _make_valid_clip(1, "win", 0),
            _make_valid_clip(1, "fail", 1),
        ]
    )
    output.clips[1].keyframes[-1].is_handoff_pose = True
    output.clips[1].keyframes[-1].character_y = 155
    output.clips[2].keyframes[-1].is_handoff_pose = True
    output.clips[3].keyframes[0].is_handoff_pose = True

    result = validate_frames(output, _make_two_act_animator_input())
    assert result.is_valid is False
    assert any("handoff pose character_y must be within" in err for err in result.errors)


def test_validate_frames_fails_when_support_y_out_of_bounds() -> None:
    output = _make_valid_output()
    output.clips[0].keyframes[0].support_y = 999

    result = validate_frames(output, _make_animator_input())
    assert result.is_valid is False
    assert any("support_y out of bounds" in err for err in result.errors)


def test_validate_frames_fails_when_time_not_strictly_increasing() -> None:
    output = _make_valid_output()
    output.clips[0].keyframes[1].time_ms = 0

    result = validate_frames(output, _make_animator_input())
    assert result.is_valid is False
    assert any("strictly increasing" in err for err in result.errors)


def test_validate_frames_fails_when_time_is_negative() -> None:
    output = _make_valid_output()
    output.clips[0].keyframes[0].time_ms = -1

    result = validate_frames(output, _make_animator_input())
    assert result.is_valid is False
    assert any("negative keyframe time_ms" in err for err in result.errors)


def test_validate_frames_fails_when_part_note_targets_removed_v1_linai_id() -> None:
    output = _make_valid_output()
    output.clips[0].keyframes[0].part_notes = [
        PartNote(
            target_id="linai-arm-left",
            note="tries to point with a limb that no longer exists",
        ),
    ]

    result = validate_frames(output, _make_animator_input())
    assert result.is_valid is False
    assert any("unknown part_notes target_id" in err for err in result.errors)


def test_validate_frames_fails_when_part_note_target_is_duplicated_in_one_keyframe() -> None:
    output = _make_valid_output()
    output.clips[0].keyframes[0].part_notes = [
        PartNote(target_id="linai-inner-patterns", note="tense jagged sparks"),
        PartNote(target_id="linai-inner-patterns", note="also trying to show question marks"),
    ]

    result = validate_frames(output, _make_animator_input())
    assert result.is_valid is False
    assert any("duplicate part_notes target_id" in err for err in result.errors)


def test_validate_frames_fails_when_duration_non_positive() -> None:
    output = _make_valid_output()
    output.clips[0].duration_ms = 0

    result = validate_frames(output, _make_animator_input())
    assert result.is_valid is False
    assert any("non-positive duration_ms" in err for err in result.errors)


def test_validate_frames_fails_when_duration_exceeds_maximum() -> None:
    output = _make_valid_output()
    output.clips[0].duration_ms = 91_000

    result = validate_frames(output, _make_animator_input())
    assert result.is_valid is False
    assert any("duration_ms exceeds" in err for err in result.errors)


def test_validate_frames_fails_when_obstacle_x_out_of_bounds() -> None:
    output = _make_valid_output()
    output.clips[0].obstacle_x = 10

    result = validate_frames(output, _make_animator_input())
    assert result.is_valid is False
    assert any("obstacle_x out of bounds" in err for err in result.errors)


def test_validate_frames_fails_when_clip_has_fewer_than_two_keyframes() -> None:
    output = _make_valid_output()
    output.clips[0].keyframes = output.clips[0].keyframes[:1]

    result = validate_frames(output, _make_animator_input())
    assert result.is_valid is False
    assert any("at least 2 keyframes" in err for err in result.errors)


def test_validate_frames_rejects_grounded_approach_that_ends_inside_obstacle_plane() -> None:
    output = _make_valid_output()
    output.clips[0].keyframes[-1].character_x = (
        output.clips[0].obstacle_x - config.APPROACH_OBSTACLE_CLEARANCE_PX + 5
    )

    result = validate_frames(output, _make_animator_input())
    assert result.is_valid is False
    assert any(
        "final grounded approach character_x must stay at or before" in err
        for err in result.errors
    )


def test_validate_frames_allows_airborne_approach_to_finish_near_obstacle_plane() -> None:
    output = _make_valid_output()
    output.clips[0].keyframes[-1].is_grounded = False
    output.clips[0].keyframes[-1].character_x = (
        output.clips[0].obstacle_x - config.APPROACH_OBSTACLE_CLEARANCE_PX + 5
    )

    result = validate_frames(output, _make_animator_input())
    assert result.is_valid is True


def test_validate_frames_fails_when_approach_clip_has_choice_index() -> None:
    output = _make_valid_output()
    output.clips[0].choice_index = 0

    result = validate_frames(output, _make_animator_input())
    assert result.is_valid is False
    assert any("approach clip must use choice_index null" in err for err in result.errors)


def test_validate_frames_fails_when_win_clip_has_no_choice_index() -> None:
    output = _make_valid_output()
    output.clips[1].choice_index = None

    result = validate_frames(output, _make_animator_input())
    assert result.is_valid is False
    assert any("win clip must include choice_index" in err for err in result.errors)


def test_validate_frames_fails_when_choice_index_is_out_of_range() -> None:
    output = _make_valid_output()
    output.clips[1].choice_index = 99

    result = validate_frames(output, _make_animator_input())
    assert result.is_valid is False
    assert any("invalid choice_index" in err for err in result.errors)


def test_validate_frames_fails_when_clip_references_unknown_act_index() -> None:
    output = _make_valid_output()
    output.clips[0].act_index = 9

    result = validate_frames(output, _make_animator_input())
    assert result.is_valid is False
    assert any("unknown act_index" in err for err in result.errors)


def test_validate_frames_fails_when_clip_obstacle_type_does_not_match_act() -> None:
    output = _make_valid_output()
    output.clips[0].obstacle_type = "bird"

    result = validate_frames(output, _make_animator_input())
    assert result.is_valid is False
    assert any("obstacle_type must match act obstacle_type" in err for err in result.errors)


def test_validate_frames_fails_when_missing_approach_clip() -> None:
    output = _make_valid_output()
    output.clips = [clip for clip in output.clips if clip.branch != "approach"]

    result = validate_frames(output, _make_animator_input())
    assert result.is_valid is False
    assert any("exactly one approach clip" in err for err in result.errors)


def test_validate_frames_fails_when_missing_win_or_fail_clip() -> None:
    output = _make_valid_output()
    output.clips = [
        clip for clip in output.clips if not (clip.branch == "fail" and clip.choice_index == 1)
    ]

    result = validate_frames(output, _make_animator_input())
    assert result.is_valid is False
    assert any("exactly one fail clip" in err for err in result.errors)


def test_validate_frames_fails_when_missing_win_clip() -> None:
    output = _make_valid_output()
    output.clips = [
        clip for clip in output.clips if not (clip.branch == "win" and clip.choice_index == 0)
    ]

    result = validate_frames(output, _make_animator_input())
    assert result.is_valid is False
    assert any("exactly one win clip" in err for err in result.errors)


def test_validate_frames_fails_when_losing_choice_contains_win_clip() -> None:
    output = _make_valid_output()
    output.clips.append(_make_valid_clip(0, "win", 1))

    result = validate_frames(output, _make_animator_input())
    assert result.is_valid is False
    assert any("must not contain a win clip" in err for err in result.errors)


def test_validate_frames_raises_for_none_input() -> None:
    with pytest.raises(TypeError):
        validate_frames(None, _make_animator_input())  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        validate_frames(_make_valid_output(), None)  # type: ignore[arg-type]


def test_repair_animator_keyframe_bounds_clamps_character_y_below_canvas() -> None:
    # character_y=220 on a 200px canvas — common when a fail/fall clip overshoots.
    output = _make_valid_output()
    output.clips[0].keyframes[0].is_grounded = False
    output.clips[0].keyframes[0].character_y = 220.0

    repaired = repair_animator_keyframe_bounds(
        output, canvas_width=800, canvas_height=200
    )
    result = validate_frames(repaired, _make_animator_input())

    assert result.is_valid is True
    assert result.errors == []
    assert repaired.clips[0].keyframes[0].character_y == 200.0


def test_repair_animator_keyframe_bounds_adjusts_support_y_for_grounded_frame() -> None:
    # Grounded keyframe with character_y=220 — support_y must follow to avoid grounded check.
    output = _make_valid_output()
    output.clips[0].keyframes[0].character_y = 220.0
    output.clips[0].keyframes[0].support_y = 220.0
    output.clips[0].keyframes[0].is_grounded = True

    repaired = repair_animator_keyframe_bounds(
        output, canvas_width=800, canvas_height=200
    )
    result = validate_frames(repaired, _make_animator_input())

    assert result.is_valid is True
    assert result.errors == []
    assert repaired.clips[0].keyframes[0].character_y == 200.0
    assert repaired.clips[0].keyframes[0].support_y == 200.0


def test_repair_animator_keyframe_bounds_preserves_valid_values() -> None:
    output = _make_valid_output()
    # All values are already within bounds — output should be unchanged.
    repaired = repair_animator_keyframe_bounds(
        output, canvas_width=800, canvas_height=200
    )

    assert repaired.clips[0].keyframes[0].character_y == 160.0
    assert repaired.clips[0].keyframes[0].support_y == 160.0


def test_validate_frames_fails_when_character_y_is_negative() -> None:
    output = _make_valid_output()
    output.clips[0].keyframes[0].is_grounded = False
    output.clips[0].keyframes[0].character_y = -5.0

    result = validate_frames(output, _make_animator_input())

    assert result.is_valid is False
    assert any("character_y out of bounds" in err for err in result.errors)


def test_validate_frames_skips_clips_for_acts_outside_act_indices_to_validate() -> None:
    """Clips whose act_index is not in act_indices_to_validate are silently skipped."""
    two_act_input = _make_two_act_animator_input()
    output = AnimatorOutput(
        clips=[
            _make_valid_clip(0, "approach", None),
            _make_valid_clip(0, "win", 0),
            _make_valid_clip(0, "fail", 1),
            _make_valid_clip(1, "approach", None),
            _make_valid_clip(1, "win", 0),
            _make_valid_clip(1, "fail", 1),
        ]
    )
    for clip in output.clips:
        if clip.act_index == 1:
            clip.obstacle_type = "bird"

    # Validate only act 0 — act 1 clips should be silently skipped.
    result = validate_frames(output, two_act_input, act_indices_to_validate={0})

    assert result.is_valid is True
    assert result.errors == []
