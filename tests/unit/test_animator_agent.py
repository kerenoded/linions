"""Unit tests for Animator agent behavior."""

from __future__ import annotations

import json

import pytest

from pipeline import config
from pipeline.agents.animator.agent import AnimatorAgent
from pipeline.models import Act, AnimatorInput, Choice

_BG_PROMPT = "Draw a simple background with gentle rolling hills and a clear blue sky above. " * 2


class _FakeModelClient:
    """Simple fake Bedrock client for deterministic Animator tests."""

    def __init__(self, response_text: str) -> None:
        self._response_text = response_text
        self.calls: list[dict[str, object]] = []

    def converse(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        return {
            "output": {"message": {"content": [{"text": self._response_text}]}},
            "usage": {"inputTokens": 13, "outputTokens": 34},
        }


def _animator_input() -> AnimatorInput:
    return AnimatorInput(
        job_id="job-123",
        session_id="session-123",
        acts=[
            Act(
                act_index=0,
                obstacle_type="wall",
                approach_description="Linai sees a wall and slows down.",
                background_drawing_prompt=_BG_PROMPT,
                choices=[
                    Choice(
                        label="Knock politely",
                        is_winning=True,
                        outcome_description="The wall swings open like a door.",
                    ),
                    Choice(
                        label="Jump at it",
                        is_winning=False,
                        outcome_description="Linai bounces backward with surprise.",
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


def test_animator_agent_returns_typed_output(capsys: pytest.CaptureFixture[str]) -> None:
    output_json = {
        "clips": [
            {
                "act_index": 0,
                "obstacle_type": "wall",
                "branch": "approach",
                "choice_index": None,
                "duration_ms": 8000,
                "obstacle_x": 400,
                "keyframes": [
                    {
                        "time_ms": 0,
                        "character_x": 40,
                        "character_y": 160,
                        "support_y": 160,
                        "is_grounded": True,
                        "is_handoff_pose": False,
                        "expression": "neutral",
                        "action": "walk",
                    },
                    {
                        "time_ms": 8000,
                        "character_x": config.MAX_GROUNDED_APPROACH_CHARACTER_X,
                        "character_y": 160,
                        "support_y": 160,
                        "is_grounded": True,
                        "is_handoff_pose": False,
                        "expression": "scared",
                        "action": "stop",
                    },
                ],
            },
            {
                "act_index": 0,
                "obstacle_type": "wall",
                "branch": "win",
                "choice_index": 0,
                "duration_ms": 4500,
                "obstacle_x": 400,
                "keyframes": [
                    {
                        "time_ms": 0,
                        "character_x": config.HANDOFF_CHARACTER_X,
                        "character_y": 160,
                        "support_y": 160,
                        "is_grounded": True,
                        "is_handoff_pose": False,
                        "expression": "neutral",
                        "action": "react",
                    },
                    {
                        "time_ms": 4500,
                        "character_x": 500,
                        "character_y": 160,
                        "support_y": 160,
                        "is_grounded": True,
                        "is_handoff_pose": False,
                        "expression": "triumphant",
                        "action": "celebrate",
                    },
                ],
            },
            {
                "act_index": 0,
                "obstacle_type": "wall",
                "branch": "fail",
                "choice_index": 1,
                "duration_ms": 3200,
                "obstacle_x": 400,
                "keyframes": [
                    {
                        "time_ms": 0,
                        "character_x": config.HANDOFF_CHARACTER_X,
                        "character_y": 160,
                        "support_y": 160,
                        "is_grounded": True,
                        "is_handoff_pose": False,
                        "expression": "scared",
                        "action": "jump",
                    },
                    {
                        "time_ms": 3200,
                        "character_x": 200,
                        "character_y": 160,
                        "support_y": 160,
                        "is_grounded": True,
                        "is_handoff_pose": False,
                        "expression": "sad",
                        "action": "fall",
                    },
                ],
            },
        ]
    }
    client = _FakeModelClient(json.dumps(output_json))
    agent = AnimatorAgent(model_client=client)

    result = agent.run(_animator_input())

    assert len(result.clips) == 3
    usage = agent.get_last_usage()
    assert usage.input_tokens == 13
    assert usage.output_tokens == 34
    logs = capsys.readouterr().out
    assert (
        "DEBUG [job-123] [AnimatorAgent.run_start] "
        "Starting an Animator agent run for the current job." in logs
    )
    assert (
        "DEBUG [job-123] [AnimatorAgent.build_prompt_start] "
        "Building the Animator prompt from the template and inputs." in logs
    )
    assert (
        "DEBUG [job-123] [AnimatorAgent.invoke_model_complete] "
        "Received a response from the Bedrock Animator model." in logs
    )
    assert (
        "DEBUG [job-123] [AnimatorAgent.parse_json_object_complete] "
        "Parsed a JSON object from the Animator response text." in logs
    )
    assert (
        "DEBUG [job-123] [AnimatorAgent.run_complete] "
        "Animator returned a keyframe payload that passed model validation." in logs
    )


def test_animator_agent_reprompt_includes_validation_errors() -> None:
    output_json = {
        "clips": [
            {
                "act_index": 0,
                "obstacle_type": "wall",
                "branch": "approach",
                "choice_index": None,
                "duration_ms": 8000,
                "obstacle_x": 400,
                "keyframes": [
                    {
                        "time_ms": 0,
                        "character_x": 40,
                        "character_y": 160,
                        "support_y": 160,
                        "is_grounded": True,
                        "is_handoff_pose": False,
                        "expression": "neutral",
                        "action": "walk",
                    },
                    {
                        "time_ms": 8000,
                        "character_x": config.MAX_GROUNDED_APPROACH_CHARACTER_X,
                        "character_y": 160,
                        "support_y": 160,
                        "is_grounded": True,
                        "is_handoff_pose": False,
                        "expression": "happy",
                        "action": "stop",
                    },
                ],
            }
        ]
    }
    client = _FakeModelClient(json.dumps(output_json))
    agent = AnimatorAgent(model_client=client)

    agent.run(_animator_input(), validation_errors=["clip act 0 must contain exactly one win clip"])

    prompt = str(client.calls[-1]["messages"])
    assert "clip act 0 must contain exactly one win clip" in prompt


def test_animator_agent_build_prompt_returns_exact_prompt_text() -> None:
    client = _FakeModelClient("{}")
    agent = AnimatorAgent(model_client=client)
    animator_input = _animator_input().model_copy(
        update={
            "requires_handoff_in": True,
            "requires_handoff_out": False,
        }
    )

    prompt = agent.build_prompt(
        animator_input,
        validation_errors=["clip act 0 must contain exactly one win clip"],
    )

    assert '"act_index": 0' in prompt
    assert '"obstacle_type": "wall"' in prompt
    assert "Canvas is 800 by 200." in prompt
    assert f"always within {config.SUPPORT_Y_TOLERANCE_PX}px" in prompt
    assert f"within {config.HANDOFF_SUPPORT_Y_TOLERANCE_PX}px of support_y" in prompt
    assert (
        f"positioned at x={config.HANDOFF_CHARACTER_X} so the next act can begin "
        "from the same place"
        in prompt
    )
    assert (
        f"do not send character_y above {config.MIN_CHARACTER_Y_IN_FRAME_PX}" in prompt
    )
    assert (
        f"stop at or before x={config.MAX_GROUNDED_APPROACH_CHARACTER_X}" in prompt
    )
    assert "This Animator input slice requires handoff-in: true" in prompt
    assert "This Animator input slice requires handoff-out: false" in prompt
    assert "Valid Linai SVG ids for keyframe part notes:" in prompt
    assert '"linai-mouth"' in prompt
    assert '"linai-eye-left"' in prompt
    assert '"linai-inner-patterns"' in prompt
    assert '"linai-trails"' in prompt
    assert '"part_notes"' in prompt
    assert '"is_handoff_pose": false' in prompt
    assert "final grounded approach pose may get close to the obstacle" in prompt
    assert (
        "Grounded travel should feel like controlled hovering, "
        "not stepping or rigid sliding." in prompt
    )
    assert "Linai should feel brave, theatrical, playful, and slightly overdramatic." in prompt
    assert "clip act 0 must contain exactly one win clip" in prompt


def test_animator_agent_raises_on_invalid_json() -> None:
    client = _FakeModelClient("not-json")
    agent = AnimatorAgent(model_client=client)

    with pytest.raises(RuntimeError, match="invalid JSON"):
        agent.run(_animator_input())
