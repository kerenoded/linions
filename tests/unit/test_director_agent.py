"""Unit tests for Director agent behavior."""

from __future__ import annotations

import json

import pytest

from pipeline import config
from pipeline.agents.director.agent import DirectorAgent
from pipeline.models import DirectorInput

_BG_PROMPT = "Draw a simple background with gentle rolling hills and a clear blue sky above. " * 2


class _FakeModelClient:
    """Simple fake Bedrock client for deterministic tests."""

    def __init__(self, response_text: str) -> None:
        self._response_text = response_text
        self.calls: list[dict[str, object]] = []

    def converse(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        return {
            "output": {"message": {"content": [{"text": self._response_text}]}},
            "usage": {"inputTokens": 11, "outputTokens": 22},
        }


def _director_input() -> DirectorInput:
    return DirectorInput(
        prompt="Linai meets a wall and tries funny solutions.",
        username="somedev",
        job_id="job-123",
        session_id="session-123",
        rag_context="Linai is persistent and playful.",
        preferred_obstacle_library_names=["bird", "wall"],
    )


def test_director_agent_returns_typed_output(capsys: pytest.CaptureFixture[str]) -> None:
    output_json = {
        "title": "A Wall and a Wink",
        "description": "Linai tries two silly plans before success.",
        "acts": [
            {
                "act_index": 0,
                "obstacle_type": "wall",
                "approach_description": "Linai sees the wall and stops.",
                "background_drawing_prompt": _BG_PROMPT,
                "choices": [
                    {
                        "label": "Knock politely",
                        "is_winning": True,
                        "outcome_description": "The wall opens like a door.",
                    },
                    {
                        "label": "Jump at it",
                        "is_winning": False,
                        "outcome_description": "Linai bounces backward.",
                    },
                ],
            },
            {
                "act_index": 1,
                "obstacle_type": "bird",
                "approach_description": "A bird blocks the path.",
                "background_drawing_prompt": _BG_PROMPT,
                "choices": [
                    {
                        "label": "Wave hello",
                        "is_winning": True,
                        "outcome_description": "The bird smiles and moves aside.",
                    },
                    {
                        "label": "Duck and run",
                        "is_winning": False,
                        "outcome_description": "Linai tumbles in panic.",
                    },
                ],
            },
        ],
    }
    client = _FakeModelClient(json.dumps(output_json))
    agent = DirectorAgent(model_client=client)

    result = agent.run(_director_input())

    assert result.title == "A Wall and a Wink"
    assert len(result.acts) == 2
    usage = agent.get_last_usage()
    assert usage.input_tokens == 11
    assert usage.output_tokens == 22
    logs = capsys.readouterr().out
    assert (
        "DEBUG [job-123] [DirectorAgent.run_start] "
        "Starting a Director agent run for the current job." in logs
    )
    assert (
        "DEBUG [job-123] [DirectorAgent.build_prompt_start] "
        "Building the Director prompt from the template and inputs." in logs
    )
    assert (
        "DEBUG [job-123] [DirectorAgent.invoke_model_complete] "
        "Received a response from the Bedrock Director model." in logs
    )
    assert (
        "DEBUG [job-123] [DirectorAgent.parse_json_object_complete] "
        "Parsed a JSON object from the Director response text." in logs
    )
    assert (
        "DEBUG [job-123] [DirectorAgent.run_complete] "
        "Director returned a script payload that passed model validation." in logs
    )


def test_director_agent_reprompt_includes_validation_errors() -> None:
    output_json = {
        "title": "T",
        "description": "D",
        "acts": [
            {
                "act_index": 0,
                "obstacle_type": "wall",
                "approach_description": "desc",
                "background_drawing_prompt": _BG_PROMPT,
                "choices": [
                    {"label": "A", "is_winning": True, "outcome_description": "ok"},
                    {"label": "B", "is_winning": False, "outcome_description": "ok"},
                ],
            },
            {
                "act_index": 1,
                "obstacle_type": "tree",
                "approach_description": "desc",
                "background_drawing_prompt": _BG_PROMPT,
                "choices": [
                    {"label": "A", "is_winning": True, "outcome_description": "ok"},
                    {"label": "B", "is_winning": False, "outcome_description": "ok"},
                ],
            },
        ],
    }
    client = _FakeModelClient(json.dumps(output_json))
    agent = DirectorAgent(model_client=client)

    agent.run(_director_input(), validation_errors=["act 1 must have exactly one winning choice"])

    prompt = str(client.calls[-1]["messages"])
    assert "act 1 must have exactly one winning choice" in prompt
    assert "bird, wall" in prompt


def test_director_agent_build_prompt_returns_exact_prompt_text() -> None:
    client = _FakeModelClient("{}")
    agent = DirectorAgent(model_client=client)

    prompt = agent.build_prompt(
        _director_input(),
        validation_errors=["act 1 must have exactly one winning choice"],
    )

    assert "Linai meets a wall and tries funny solutions." in prompt
    assert "Linai is persistent and playful." in prompt
    assert "bird, wall" in prompt
    assert (
        f"Produce between {config.MIN_OBSTACLE_ACTS} and {config.MAX_OBSTACLE_ACTS} acts."
        in prompt
    )
    assert (
        "Each act has between "
        f"{config.MIN_CHOICES_PER_ACT} and {config.MAX_CHOICES_PER_ACT} choices."
        in prompt
    )
    assert f"title <= {config.MAX_TITLE_LENGTH_CHARS} chars" in prompt
    assert f"description <= {config.MAX_DESCRIPTION_LENGTH_CHARS} chars" in prompt
    assert f"choice label <= {config.MAX_CHOICE_LABEL_LENGTH_CHARS} chars" in prompt
    assert "treat them as real act obstacles before inventing substitute obstacles" in prompt
    assert "Do not hide user-named obstacles only inside approach_description" in prompt
    assert "act 1 must have exactly one winning choice" in prompt


def test_director_agent_raises_on_invalid_json() -> None:
    client = _FakeModelClient("not-json")
    agent = DirectorAgent(model_client=client)

    with pytest.raises(RuntimeError, match="invalid JSON"):
        agent.run(_director_input())
