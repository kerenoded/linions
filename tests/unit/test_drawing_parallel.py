"""Unit tests for parallel Drawing task execution."""

from __future__ import annotations

import threading

from pipeline.agents.drawing.agent import DrawingAgent
from pipeline.agents.drawing.parallel import run_drawing_tasks_in_parallel
from pipeline.models import DrawingInput


class _FakeModelClient:
    """Simple thread-safe fake Bedrock client for Drawing parallel tests."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self._lock = threading.Lock()

    def converse(self, **kwargs: object) -> dict[str, object]:
        with self._lock:
            self.calls.append(kwargs)
        prompt = kwargs["messages"][0]["content"][0]["text"]
        return {
            "output": {
                "message": {
                    "content": [{"text": f"<svg viewBox='0 0 120 150'><text>{prompt}</text></svg>"}]
                }
            },
            "usage": {"inputTokens": 9, "outputTokens": 21},
        }


def test_run_drawing_tasks_in_parallel_returns_one_result_per_input() -> None:
    client = _FakeModelClient()
    agent = DrawingAgent(model_client=client)

    results = run_drawing_tasks_in_parallel(
        base_agent=agent,
        drawing_inputs=[
            DrawingInput(
                job_id="job-1",
                session_id="session-1",
                obstacle_type="dragon",
                drawing_prompt="draw dragon",
            ),
            DrawingInput(
                job_id="job-1",
                session_id="session-1",
                obstacle_type="bg-act-0",
                drawing_prompt="draw background",
                drawing_type="background",
            ),
        ],
        validation_errors_by_identity={
            ("obstacle", "dragon"): None,
            ("background", "bg-act-0"): ['svg must include required element id="background-root"'],
        },
        max_workers=4,
    )

    assert len(results) == 2
    identities = {result.task_identity for result in results}
    assert identities == {("obstacle", "dragon"), ("background", "bg-act-0")}
    assert all(result.output is not None for result in results)
    background_call = next(
        call
        for call in client.calls
        if "draw background" in call["messages"][0]["content"][0]["text"]
    )
    background_prompt = background_call["messages"][0]["content"][0]["text"]
    assert 'id="background-root"' in background_prompt
    assert background_call
