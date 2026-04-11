"""Unit tests for Renderer agent behavior."""

from __future__ import annotations

import pytest

from pipeline.agents.renderer.agent import RendererAgent
from pipeline.models import ClipManifest, Keyframe, RendererInput


class _FakeModelClient:
    """Simple fake Bedrock client for deterministic Renderer-agent tests."""

    def __init__(self, response_text: str) -> None:
        self._response_text = response_text
        self.calls: list[dict[str, object]] = []

    def converse(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        return {
            "output": {"message": {"content": [{"text": self._response_text}]}},
            "usage": {"inputTokens": 14, "outputTokens": 33},
        }


def _renderer_input() -> RendererInput:
    return RendererInput(
        job_id="job-123",
        session_id="session-123",
        clips=[
            ClipManifest(
                act_index=0,
                obstacle_type="wall",
                branch="approach",
                choice_index=None,
                duration_ms=4000,
                obstacle_x=400,
                obstacle_svg_override=(
                    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 150">'
                    '<g id="obstacle-root"><path id="obstacle-main" d="M10 140 L110 140" />'
                    '<g id="obstacle-animated-part"><path d="M20 20 L20 40" /></g></g></svg>'
                ),
                background_svg=(
                    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 200">\n'
                    '  <g id="background-main"><rect width="800" height="200" fill="#aaccee" />'
                    "</g>\n</svg>"
                ),
                keyframes=[
                    Keyframe(
                        time_ms=0,
                        character_x=40,
                        character_y=160,
                        support_y=160,
                        is_grounded=True,
                        expression="calm",
                        action="floating in",
                    ),
                    Keyframe(
                        time_ms=4000,
                        character_x=320,
                        character_y=160,
                        support_y=160,
                        is_grounded=True,
                        expression="nervous",
                        action="halting mid-hover",
                    ),
                ],
            )
        ],
    )


def test_renderer_agent_returns_typed_output() -> None:
    client = _FakeModelClient(
        '{"clips":[{"act_index":0,"branch":"approach","choice_index":null,'
        '"duration_ms":4000,"svg":"<svg viewBox=\\"0 0 800 200\\"><g id=\\"linai\\">'
        '<path id=\\"linai-mouth\\" d=\\"M1 1\\"/></g></svg>"}]}'
    )
    agent = RendererAgent(model_client=client)

    result = agent.run(_renderer_input())

    assert result.clips[0].branch == "approach"
    assert result.clips[0].duration_ms == 4000
    usage = agent.get_last_usage()
    assert usage.input_tokens == 14
    assert usage.output_tokens == 33


def test_renderer_agent_prompt_includes_validation_errors_and_obstacle_svg() -> None:
    client = _FakeModelClient('{"clips":[]}')
    agent = RendererAgent(model_client=client)
    validation_error = (
        'renderer clip (act_index=0, branch=approach, choice_index=None) missing id="linai"'
    )

    agent.run(
        _renderer_input(),
        validation_errors=[validation_error],
    )

    messages = client.calls[-1]["messages"]
    assert isinstance(messages, list)
    prompt = messages[0]["content"][0]["text"]
    assert 'missing id="linai"' in prompt
    assert "__SYSTEM_COMPOSED_OBSTACLE__" in prompt
    assert "__SYSTEM_COMPOSED_BACKGROUND__" in prompt
    assert "linai-inner-patterns" in prompt
    assert "linai-trails" in prompt
    assert "readable floating is mandatory" in prompt
    assert "Keep obstacle life visible in every clip." in prompt
    assert "Keep background life visible in every clip too." in prompt
    assert "Keep Linai fully inside the viewBox at all times." in prompt
    assert "Downward root translate must stay small even in fail clips" in prompt
    assert "Iris and pupil drifts should usually stay within about 2-3px" in prompt
    assert "do not reform her silhouette with extreme scale swings" in prompt
    assert "Never let the eyes or emotion symbols visibly detach outside the cloud." in prompt
    assert "Do not use `translate` motion on `linai-eye-left` or `linai-eye-right`" in prompt
    assert "face should read as riding with that body motion" in prompt
    assert "instead of defaulting to stars every time" in prompt
    assert "question marks or similar curious symbols" in prompt
    assert "lightning or jagged energy" in prompt
    assert "alternate the legs" not in prompt
    assert "keep Linai clearly before the obstacle plane" in prompt
    assert "Return compact JSON and compact SVG strings" in prompt
    assert "Prefer single quotes inside SVG attributes" in prompt
    assert "system injects the exact approved obstacle and background SVG layers" in prompt
    assert "fill='#aaccee'" not in prompt


def test_renderer_agent_raises_when_model_client_missing() -> None:
    agent = RendererAgent(model_client=None)

    with pytest.raises(RuntimeError, match="model_client"):
        agent.run(_renderer_input())


def test_renderer_agent_spawn_parallel_worker_returns_fresh_agent() -> None:
    client = _FakeModelClient('{"clips":[]}')
    agent = RendererAgent(model_client=client)

    worker = agent.spawn_parallel_worker()

    assert worker is not agent
    worker.run(_renderer_input())
    assert client.calls
