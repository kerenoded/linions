"""Unit tests for Drawing agent behavior."""

from __future__ import annotations

import pytest

from pipeline.agents.drawing.agent import DrawingAgent
from pipeline.models import DrawingInput

_OBSTACLE_PROMPT = (
    "Draw a detailed, high-quality SVG illustration of a "
    "fully armored medieval dragon in a heroic standing pose. "
) * 2

_BACKGROUND_PROMPT = (
    "Draw a dark enchanted forest background with fireflies "
    "and a narrow winding path through dense gnarled trees. "
) * 2


class _FakeModelClient:
    """Simple fake Bedrock client for deterministic Drawing-agent tests."""

    def __init__(self, response_text: str) -> None:
        self._response_text = response_text
        self.calls: list[dict[str, object]] = []

    def converse(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        return {
            "output": {"message": {"content": [{"text": self._response_text}]}},
            "usage": {"inputTokens": 9, "outputTokens": 21},
        }


def _drawing_input(
    *,
    drawing_type: str = "obstacle",
    drawing_prompt: str | None = None,
) -> DrawingInput:
    """Build a DrawingInput for tests."""
    prompt = drawing_prompt or (
        _BACKGROUND_PROMPT if drawing_type == "background" else _OBSTACLE_PROMPT
    )
    return DrawingInput(
        job_id="job-123",
        session_id="session-123",
        obstacle_type="dragon" if drawing_type == "obstacle" else "forest-bg",
        drawing_prompt=prompt,
        drawing_type=drawing_type,
    )


def test_drawing_agent_returns_typed_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Drawing agent returns a DrawingOutput with SVG content."""
    client = _FakeModelClient(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 150">'
        '<g id="obstacle-root">'
        '<path id="obstacle-main" d="M15 140 L60 20 L105 140 Z" fill="white"/>'
        '<g id="obstacle-animated-part"><path d="M60 20 C72 14 84 10 94 12"/>'
        '<animateTransform attributeName="transform" type="rotate" '
        'values="-3 60 20;3 60 20;-3 60 20" dur="1200ms" '
        'repeatCount="indefinite"/>'
        "</g>"
        "</g>"
        "</svg>"
    )
    agent = DrawingAgent(model_client=client)

    result = agent.run(_drawing_input())

    assert result.svg.startswith("<svg")
    usage = agent.get_last_usage()
    assert usage.input_tokens == 9
    assert usage.output_tokens == 21
    logs = capsys.readouterr().out
    assert "Drawing agent returned an SVG payload." in logs


def test_drawing_agent_reprompt_includes_validation_errors() -> None:
    """Validation errors are appended to the prompt on retry."""
    client = _FakeModelClient("<svg viewBox='0 0 120 150'></svg>")
    agent = DrawingAgent(model_client=client)

    agent.run(
        _drawing_input(),
        validation_errors=['svg must include required element id="obstacle-main"'],
    )

    prompt = str(client.calls[-1]["messages"])
    assert 'svg must include required element id="obstacle-main"' in prompt


def test_drawing_agent_raises_when_model_client_missing() -> None:
    """Agent raises RuntimeError when no model client is provided."""
    agent = DrawingAgent(model_client=None)

    with pytest.raises(RuntimeError, match="model_client"):
        agent.run(_drawing_input())


def test_drawing_agent_uses_drawing_prompt_from_input() -> None:
    """Drawing agent sends the Director's drawing_prompt as the user message."""
    svg_response = (
        '<svg viewBox="0 0 120 150">'
        '<g id="obstacle-root"><g id="obstacle-main">'
        '<g id="obstacle-animated-part"/></g></g></svg>'
    )
    client = _FakeModelClient(response_text=svg_response)
    agent = DrawingAgent(model_client=client)
    inp = _drawing_input()
    agent.run(inp)
    sent_message = client.calls[0]["messages"][0]["content"][0]["text"]
    assert _OBSTACLE_PROMPT in sent_message


def test_drawing_agent_background_type_uses_background_system_prompt() -> None:
    """Background drawing uses a system prompt mentioning background IDs."""
    svg_response = (
        '<svg viewBox="0 0 800 200">'
        '<g id="background-root"><g id="background-main">'
        '<g id="background-animated-part"/></g></g></svg>'
    )
    client = _FakeModelClient(response_text=svg_response)
    agent = DrawingAgent(model_client=client)
    inp = _drawing_input(drawing_type="background")
    agent.run(inp)
    system_text = client.calls[0]["system"][0]["text"]
    assert "full-canvas backgrounds" in system_text
    assert "id='background-root'" in system_text
    assert "background-animated-part" in system_text
    assert "opacity" in system_text
    assert "fill" in system_text


def test_drawing_agent_obstacle_type_uses_obstacle_system_prompt() -> None:
    """Obstacle drawing uses obstacle-specific system prompt."""
    svg_response = '<svg viewBox="0 0 120 150"><g id="obstacle-root"/></svg>'
    client = _FakeModelClient(response_text=svg_response)
    agent = DrawingAgent(model_client=client)
    inp = _drawing_input(drawing_type="obstacle")
    agent.run(inp)
    system_text = client.calls[0]["system"][0]["text"]
    assert "expert SVG illustrator" in system_text
    assert "id='obstacle-root'" in system_text
    assert "obstacle-animated-part" in system_text
    assert "animateTransform" in system_text
    assert "full-canvas backgrounds" not in system_text


def test_drawing_agent_spawn_parallel_worker_returns_fresh_agent() -> None:
    """Parallel workers get a fresh DrawingAgent instance with shared client."""
    client = _FakeModelClient("<svg viewBox='0 0 120 150'></svg>")
    agent = DrawingAgent(model_client=client)

    worker = agent.spawn_parallel_worker()

    assert worker is not agent
    worker.run(_drawing_input())
    assert client.calls
