"""Unit tests for the Phase 5 pipeline orchestrator behavior."""

from __future__ import annotations

import hashlib
import json
import threading
from typing import Any

import pytest

from pipeline import config
from pipeline.lambdas.orchestrator.knowledge_base import BedrockKnowledgeBaseService
from pipeline.lambdas.orchestrator.pipeline_orchestrator import LibraryLookups, PipelineOrchestrator
from pipeline.models import (
    Act,
    AnimatorOutput,
    Choice,
    ClipManifest,
    DirectorOutput,
    DrawingOutput,
    Keyframe,
    RendererOutput,
    SvgClip,
)

_BG_PROMPT = "Draw a simple background with gentle rolling hills and a clear blue sky above. " * 2
_DRAW_PROMPT = "Draw a richly layered obstacle SVG with a clearly animated secondary part. " * 2
_VALID_LIBRARY_OBSTACLE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 150">'
    '<g id="obstacle-root">'
    '<path id="obstacle-main" d="M15 140 L60 20 L105 140 Z" fill="#ffffff"/>'
    '<g id="obstacle-animated-part"><path d="M60 20 C72 14 84 10 94 12"/>'
    '<animateTransform attributeName="transform" type="rotate" '
    'values="-3 60 20;3 60 20;-3 60 20" dur="1200ms" '
    'repeatCount="indefinite"/>'
    "</g></g></svg>"
)

_VALID_BACKGROUND_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 200">'
    '<g id="background-root"><g id="background-main">'
    '<rect width="800" height="200" fill="#87CEEB"/>'
    '<g id="background-animated-part">'
    '<rect width="800" height="100" y="100" fill="#228B22">'
    '<animate attributeName="opacity" values="0.9;1;0.9" dur="3s" repeatCount="indefinite"/>'
    "</rect></g></g></g></svg>"
)


def _fake_obstacle_svg(slug: str) -> str | None:
    """Return deterministic obstacle-library SVGs for unit tests."""
    if slug in {"wall", "bird"}:
        return _VALID_LIBRARY_OBSTACLE_SVG
    return None


def _make_library_lookups(
    *,
    get_obstacle_svg: Any = None,
    list_obstacle_names: Any = None,
    get_background_svg: Any = None,
    find_background_library_slug: Any = None,
    prompt_to_background_slug: Any = None,
) -> LibraryLookups:
    return LibraryLookups(
        get_obstacle_svg=get_obstacle_svg or _fake_obstacle_svg,
        list_obstacle_names=list_obstacle_names or (lambda: ["wall", "bird"]),
        get_background_svg=get_background_svg or (lambda _slug: None),
        find_background_library_slug=find_background_library_slug or (lambda *_: None),
        prompt_to_background_slug=prompt_to_background_slug or (lambda _: "gentle-rolling-hills"),
    )


class _FakeJobStore:
    """Capture pipeline orchestrator job-store calls for assertions."""

    def __init__(self) -> None:
        self.status = "GENERATING"
        self.stage_updates: list[str] = []
        self.done_calls: list[dict[str, Any]] = []
        self.failed_calls: list[dict[str, Any]] = []

    def get_job(self, _job_id: str) -> dict[str, str]:
        return {"status": self.status}

    def update_stage_generating(self, _job_id: str, stage: str) -> None:
        self.stage_updates.append(stage)

    def mark_done(self, **kwargs: Any) -> None:
        self.done_calls.append(kwargs)

    def mark_failed(self, **kwargs: Any) -> None:
        self.failed_calls.append(kwargs)


class _FakeDirectorAgent:
    """Fake director agent with queued outputs."""

    def __init__(self, outputs: list[Any], output_tokens: int = 20) -> None:
        self._outputs = outputs
        self.calls: list[dict[str, Any]] = []
        self._output_tokens = output_tokens

    def run(self, input: Any, validation_errors: list[str] | None = None) -> DirectorOutput:
        self.calls.append({"input": input, "validation_errors": validation_errors})
        output = self._outputs[len(self.calls) - 1]
        if isinstance(output, Exception):
            raise output
        return output

    def get_last_usage(self) -> Any:
        class Usage:
            input_tokens = 10
            output_tokens = 20

        Usage.output_tokens = self._output_tokens
        return Usage()

    def get_last_prompt(self) -> str:
        return "director-prompt"

    def get_last_response_text(self) -> str:
        return "director-response"


class _FakeAnimatorAgent:
    """Fake animator agent with queued outputs."""

    def __init__(
        self,
        outputs: dict[int, list[Any]],
        output_tokens: int = 20,
        *,
        calls: list[dict[str, Any]] | None = None,
        call_counts_by_act: dict[int, int] | None = None,
        lock: threading.Lock | None = None,
    ) -> None:
        self._outputs = outputs
        self.calls: list[dict[str, Any]] = [] if calls is None else calls
        self._call_counts_by_act = {} if call_counts_by_act is None else call_counts_by_act
        self._lock = threading.Lock() if lock is None else lock
        self._output_tokens = output_tokens

    def run(self, input: Any, validation_errors: list[str] | None = None) -> AnimatorOutput:
        act_index = input.acts[0].act_index
        with self._lock:
            self.calls.append({"input": input, "validation_errors": validation_errors})
            call_index = self._call_counts_by_act.get(act_index, 0)
            self._call_counts_by_act[act_index] = call_index + 1
        output = self._outputs[act_index][call_index]
        if isinstance(output, Exception):
            raise output
        return output

    def spawn_parallel_worker(self) -> _FakeAnimatorAgent:
        return _FakeAnimatorAgent(
            outputs=self._outputs,
            output_tokens=self._output_tokens,
            calls=self.calls,
            call_counts_by_act=self._call_counts_by_act,
            lock=self._lock,
        )

    def get_last_usage(self) -> Any:
        class Usage:
            input_tokens = 12
            output_tokens = 24

        Usage.output_tokens = self._output_tokens
        return Usage()

    def get_last_prompt(self) -> str:
        return "animator-prompt"

    def get_last_response_text(self) -> str:
        return "animator-response"


class _FakeDrawingAgent:
    """Fake drawing agent with queued outputs."""

    def __init__(
        self,
        outputs: list[Any] | None = None,
        output_tokens: int = 20,
        *,
        outputs_by_identity: dict[tuple[str, str], list[Any]] | None = None,
        calls: list[dict[str, Any]] | None = None,
        call_counts_by_identity: dict[tuple[str, str], int] | None = None,
        lock: threading.Lock | None = None,
    ) -> None:
        self._outputs = outputs or []
        self._outputs_by_identity = {} if outputs_by_identity is None else outputs_by_identity
        self.calls: list[dict[str, Any]] = [] if calls is None else calls
        self._call_counts_by_identity = (
            {} if call_counts_by_identity is None else call_counts_by_identity
        )
        self._lock = threading.Lock() if lock is None else lock
        self._output_tokens = output_tokens

    def run(self, input: Any, validation_errors: list[str] | None = None) -> Any:
        identity = (input.drawing_type, input.obstacle_type)
        with self._lock:
            self.calls.append({"input": input, "validation_errors": validation_errors})
            call_index = self._call_counts_by_identity.get(identity, 0)
            self._call_counts_by_identity[identity] = call_index + 1

        if self._outputs_by_identity:
            queued = self._outputs_by_identity.get(identity)
            if queued is None:
                raise AssertionError(f"Unexpected Drawing task identity: {identity}")
            output = queued[min(call_index, len(queued) - 1)]
        else:
            if not self._outputs:
                raise AssertionError("Drawing agent should not have been called")
            output = self._outputs[len(self.calls) - 1]
        if isinstance(output, Exception):
            raise output
        return output

    def spawn_parallel_worker(self) -> _FakeDrawingAgent:
        return _FakeDrawingAgent(
            outputs=self._outputs,
            output_tokens=self._output_tokens,
            outputs_by_identity=self._outputs_by_identity,
            calls=self.calls,
            call_counts_by_identity=self._call_counts_by_identity,
            lock=self._lock,
        )

    def get_last_usage(self) -> Any:
        class Usage:
            input_tokens = 8
            output_tokens = 16

        Usage.output_tokens = self._output_tokens
        return Usage()

    def get_last_prompt(self) -> str:
        return "drawing-prompt"

    def get_last_response_text(self) -> str:
        return "drawing-response"


class _FakeRendererAgent:
    """Fake renderer agent with queued outputs."""

    def __init__(
        self,
        outputs: list[Any],
        output_tokens: int = 20,
        *,
        calls: list[dict[str, Any]] | None = None,
        call_count: list[int] | None = None,
        lock: threading.Lock | None = None,
    ) -> None:
        self._outputs = outputs
        self.calls: list[dict[str, Any]] = [] if calls is None else calls
        self._output_tokens = output_tokens
        self._call_count = [0] if call_count is None else call_count
        self._lock = threading.Lock() if lock is None else lock

    def spawn_parallel_worker(self) -> _FakeRendererAgent:
        return _FakeRendererAgent(
            outputs=self._outputs,
            output_tokens=self._output_tokens,
            calls=self.calls,
            call_count=self._call_count,
            lock=self._lock,
        )

    def run(self, input: Any, validation_errors: list[str] | None = None) -> RendererOutput:
        with self._lock:
            self.calls.append({"input": input, "validation_errors": validation_errors})
            call_index = min(self._call_count[0], len(self._outputs) - 1)
            self._call_count[0] += 1
        queued_output = self._outputs[call_index]
        output = queued_output(input) if callable(queued_output) else queued_output
        if isinstance(output, Exception):
            raise output
        return output

    def get_last_usage(self) -> Any:
        class Usage:
            input_tokens = 18
            output_tokens = 42

        Usage.output_tokens = self._output_tokens
        return Usage()

    def get_last_prompt(self) -> str:
        return "renderer-prompt"

    def get_last_response_text(self) -> str:
        return "renderer-response"


class _FakeEpisodeStore:
    """Capture S3 draft artifact operations for assertions."""

    def __init__(
        self,
        *,
        fail_json: bool = False,
        fail_thumbnail: bool = False,
        fail_svg_key: str | None = None,
    ) -> None:
        self.fail_json = fail_json
        self.fail_thumbnail = fail_thumbnail
        self.fail_svg_key = fail_svg_key
        self.json_put_calls: list[dict[str, str]] = []
        self.thumbnail_put_calls: list[dict[str, str]] = []
        self.svg_put_calls: list[dict[str, str]] = []
        self.delete_calls: list[str] = []
        self.operations: list[str] = []

    def put_draft_json(self, key: str, body: str) -> None:
        self.operations.append("put_draft_json")
        self.json_put_calls.append({"key": key, "body": body})
        if self.fail_json:
            raise RuntimeError("json put failed")

    def put_draft_thumbnail(self, key: str, body: str) -> None:
        self.operations.append("put_draft_thumbnail")
        self.thumbnail_put_calls.append({"key": key, "body": body})
        if self.fail_thumbnail:
            raise RuntimeError("thumbnail put failed")

    def put_draft_svg(self, key: str, body: str) -> None:
        self.operations.append("put_draft_svg")
        self.svg_put_calls.append({"key": key, "body": body})
        if self.fail_svg_key == key:
            raise RuntimeError("supporting svg put failed")

    def delete_draft_object(self, key: str) -> None:
        self.operations.append("delete_draft_object")
        self.delete_calls.append(key)


class _FakeKbClient:
    """Fake KB retrieve client returning deterministic snippets."""

    def retrieve(self, **_kwargs: Any) -> dict[str, Any]:
        return {"retrievalResults": [{"content": {"text": "KB text"}}]}


class _FakeAgentCoreClient:
    """Fake AgentCore client returning one session id."""

    def create_session(self, **_kwargs: Any) -> dict[str, str]:
        return {"sessionId": "session-1"}


def _valid_director_output() -> DirectorOutput:
    return DirectorOutput(
        title="A Valid Episode",
        description="Linai solves obstacles with comic persistence.",
        acts=[
            Act(
                act_index=0,
                obstacle_type="wall",
                approach_description="Linai reaches a wall.",
                drawing_prompt=_DRAW_PROMPT,
                background_drawing_prompt=_BG_PROMPT,
                choices=[
                    Choice(label="Knock", is_winning=True, outcome_description="Door opens."),
                    Choice(label="Jump", is_winning=False, outcome_description="Falls down."),
                ],
            ),
            Act(
                act_index=1,
                obstacle_type="bird",
                approach_description="A bird blocks the path.",
                drawing_prompt=_DRAW_PROMPT,
                background_drawing_prompt=_BG_PROMPT,
                choices=[
                    Choice(label="Wave", is_winning=True, outcome_description="Bird smiles."),
                    Choice(label="Hide", is_winning=False, outcome_description="Trips."),
                ],
            ),
        ],
    )


def _invalid_director_output() -> DirectorOutput:
    return DirectorOutput(
        title="Invalid",
        description="Too few acts.",
        acts=[
            Act(
                act_index=0,
                obstacle_type="wall",
                approach_description="Only one act.",
                drawing_prompt=_DRAW_PROMPT,
                background_drawing_prompt=_BG_PROMPT,
                choices=[
                    Choice(label="Knock", is_winning=True, outcome_description="Open."),
                    Choice(label="Jump", is_winning=False, outcome_description="Fail."),
                ],
            )
        ],
    )


def _keyframes(
    start_x: float,
    end_x: float,
    expression: str,
    action: str,
    *,
    start_handoff: bool = False,
    end_handoff: bool = False,
) -> list[Keyframe]:
    return [
        Keyframe(
            time_ms=0,
            character_x=config.HANDOFF_CHARACTER_X if start_handoff else start_x,
            character_y=160,
            support_y=160,
            is_grounded=True,
            is_handoff_pose=start_handoff,
            expression="neutral",
            action="float",
        ),
        Keyframe(
            time_ms=1000,
            character_x=config.HANDOFF_CHARACTER_X if end_handoff else end_x,
            character_y=160,
            support_y=160,
            is_grounded=True,
            is_handoff_pose=end_handoff,
            expression=expression,  # type: ignore[arg-type]
            action=action,  # type: ignore[arg-type]
        ),
    ]


def _valid_animator_output() -> AnimatorOutput:
    return AnimatorOutput(
        clips=[
            ClipManifest(
                act_index=0,
                obstacle_type="wall",
                branch="approach",
                choice_index=None,
                duration_ms=8000,
                obstacle_x=400,
                keyframes=_keyframes(
                    40,
                    config.MAX_GROUNDED_APPROACH_CHARACTER_X,
                    "scared",
                    "stop",
                ),
            ),
            ClipManifest(
                act_index=0,
                obstacle_type="wall",
                branch="win",
                choice_index=0,
                duration_ms=4500,
                obstacle_x=400,
                keyframes=_keyframes(320, 500, "triumphant", "celebrate"),
            ),
            ClipManifest(
                act_index=0,
                obstacle_type="wall",
                branch="fail",
                choice_index=1,
                duration_ms=3000,
                obstacle_x=400,
                keyframes=_keyframes(320, 210, "sad", "fall"),
            ),
            ClipManifest(
                act_index=1,
                obstacle_type="bird",
                branch="approach",
                choice_index=None,
                duration_ms=7000,
                obstacle_x=420,
                keyframes=_keyframes(
                    60,
                    config.MAX_GROUNDED_APPROACH_CHARACTER_X,
                    "scared",
                    "stop",
                    start_handoff=True,
                ),
            ),
            ClipManifest(
                act_index=1,
                obstacle_type="bird",
                branch="win",
                choice_index=0,
                duration_ms=4000,
                obstacle_x=420,
                keyframes=_keyframes(340, 520, "happy", "celebrate"),
            ),
            ClipManifest(
                act_index=1,
                obstacle_type="bird",
                branch="fail",
                choice_index=1,
                duration_ms=3100,
                obstacle_x=420,
                keyframes=_keyframes(340, 210, "sad", "fall"),
            ),
        ]
    )


def _valid_animator_output_for_act(act_index: int) -> AnimatorOutput:
    return AnimatorOutput(
        clips=[clip for clip in _valid_animator_output().clips if clip.act_index == act_index]
    )


def _invalid_animator_output_for_act(act_index: int, obstacle_type: str) -> AnimatorOutput:
    return AnimatorOutput(
        clips=[
            ClipManifest(
                act_index=act_index,
                obstacle_type=obstacle_type,
                branch="approach",
                choice_index=None,
                duration_ms=8000,
                obstacle_x=400,
                keyframes=_keyframes(
                    40,
                    config.MAX_GROUNDED_APPROACH_CHARACTER_X,
                    "scared",
                    "stop",
                ),
            )
        ]
    )


def _output_for_act(animator_output: AnimatorOutput, act_index: int) -> AnimatorOutput:
    return AnimatorOutput(
        clips=[clip for clip in animator_output.clips if clip.act_index == act_index]
    )


def _rendered_svg() -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 200" fill="none">'
        '<g id="linai">'
        '<g id="linai-body"><ellipse cx="104" cy="90" rx="34" ry="28" fill="#88eeff">'
        '<animate attributeName="fill" values="#88eeff;#aaf4ff;#88eeff" dur="1200ms" '
        'repeatCount="indefinite"/>'
        "</ellipse></g>"
        '<g id="linai-eye-left"><ellipse cx="92" cy="80" rx="8" ry="10" fill="#ffffff"/>'
        '<animateTransform attributeName="transform" type="rotate" '
        'values="0 92 80;-4 92 80;0 92 80" dur="900ms" repeatCount="indefinite"/>'
        "</g>"
        '<g id="linai-eye-right"><ellipse cx="116" cy="78" rx="9" ry="11" fill="#ffffff"/></g>'
        '<g id="linai-mouth"><path d="M104 102 Q112 108 120 103" stroke="#2299aa" fill="none"/>'
        "</g>"
        '<g id="linai-inner-patterns"><path d="M88 84 Q100 74 112 82" '
        'stroke="#ffffff" fill="none"/></g>'
        '<g id="linai-particles"><circle cx="100" cy="92" r="2" fill="#ffffff"/>'
        '<animateTransform attributeName="transform" type="translate" '
        'values="0 0;2 -2;0 0" dur="1100ms" repeatCount="indefinite"/>'
        "</g>"
        '<g id="linai-trails"><path d="M92 118 Q88 136 84 154" stroke="#88eeff" fill="none"/>'
        '<animateTransform attributeName="transform" type="scale" '
        'values="1 1;1.06 0.94;1 1" dur="1000ms" repeatCount="indefinite"/>'
        "</g>"
        "</g>"
        "</svg>"
    )


def _invalid_rendered_svg() -> str:
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 200"></svg>'


def _gliding_rendered_svg() -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 200" fill="none">'
        '<g id="linai">'
        '<g id="linai-body"><ellipse cx="104" cy="90" rx="34" ry="28" fill="#88eeff"/></g>'
        '<g id="linai-eye-left"><ellipse cx="92" cy="80" rx="8" ry="10" fill="#ffffff"/></g>'
        '<g id="linai-eye-right"><ellipse cx="116" cy="78" rx="9" ry="11" fill="#ffffff"/></g>'
        '<g id="linai-mouth"><path d="M104 102 Q112 108 120 103" stroke="#2299aa" fill="none"/></g>'
        '<g id="linai-inner-patterns"><path d="M88 84 Q100 74 112 82" '
        'stroke="#ffffff" fill="none"/></g>'
        '<g id="linai-particles"><circle cx="100" cy="92" r="2" fill="#ffffff"/></g>'
        '<g id="linai-trails"><path d="M92 118 Q88 136 84 154" stroke="#88eeff" fill="none"/></g>'
        "</g>"
        "</svg>"
    )


def _valid_renderer_output_for_input(renderer_input: Any) -> RendererOutput:
    return RendererOutput(
        clips=[
            SvgClip(
                act_index=clip.act_index,
                branch=clip.branch,
                choice_index=clip.choice_index,
                duration_ms=clip.duration_ms,
                svg=_rendered_svg(),
            )
            for clip in renderer_input.clips
        ]
    )


def _invalid_renderer_output_for_input(renderer_input: Any) -> RendererOutput:
    return RendererOutput(
        clips=[
            SvgClip(
                act_index=clip.act_index,
                branch=clip.branch,
                choice_index=clip.choice_index,
                duration_ms=clip.duration_ms,
                svg=_invalid_rendered_svg(),
            )
            for clip in renderer_input.clips
        ]
    )


def _gliding_renderer_output_for_input(renderer_input: Any) -> RendererOutput:
    return RendererOutput(
        clips=[
            SvgClip(
                act_index=clip.act_index,
                branch=clip.branch,
                choice_index=clip.choice_index,
                duration_ms=clip.duration_ms,
                svg=_gliding_rendered_svg(),
            )
            for clip in renderer_input.clips
        ]
    )


def _compute_content_hash(episode_dict: dict[str, Any]) -> str:
    hash_input = {**episode_dict, "contentHash": None}
    serialised = json.dumps(hash_input, sort_keys=True, ensure_ascii=False)
    return f"sha256:{hashlib.sha256(serialised.encode('utf-8')).hexdigest()}"


def _make_orchestrator(
    *,
    store: _FakeJobStore | None = None,
    director_outputs: list[Any] | None = None,
    animator_outputs: dict[int, list[Any]] | None = None,
    drawing_outputs: list[Any] | None = None,
    drawing_outputs_by_identity: dict[tuple[str, str], list[Any]] | None = None,
    renderer_outputs: list[Any] | None = None,
    episode_store: _FakeEpisodeStore | None = None,
    library_lookups: LibraryLookups | None = None,
    animator_output_tokens: int = 20,
    renderer_output_tokens: int = 20,
) -> tuple[
    PipelineOrchestrator,
    _FakeJobStore,
    _FakeDirectorAgent,
    _FakeAnimatorAgent,
    _FakeDrawingAgent,
    _FakeRendererAgent,
    _FakeEpisodeStore,
]:
    resolved_store = store or _FakeJobStore()
    resolved_animator_outputs = animator_outputs or {
        0: [_valid_animator_output_for_act(0)],
        1: [_valid_animator_output_for_act(1)],
    }
    director_agent = _FakeDirectorAgent(outputs=director_outputs or [_valid_director_output()])
    animator_agent = _FakeAnimatorAgent(
        outputs=resolved_animator_outputs,
        output_tokens=animator_output_tokens,
    )
    default_drawing_outputs_by_identity = {
        ("background", "gentle-rolling-hills"): [DrawingOutput(svg=_VALID_BACKGROUND_SVG)],
        ("background", "gentle-rolling-hills-1"): [DrawingOutput(svg=_VALID_BACKGROUND_SVG)],
    }
    drawing_agent = _FakeDrawingAgent(
        outputs=drawing_outputs,
        outputs_by_identity=(
            drawing_outputs_by_identity
            if drawing_outputs_by_identity is not None
            else default_drawing_outputs_by_identity
        ),
    )
    renderer_agent = _FakeRendererAgent(
        outputs=renderer_outputs or [_valid_renderer_output_for_input],
        output_tokens=renderer_output_tokens,
    )
    resolved_episode_store = episode_store or _FakeEpisodeStore()
    orchestrator = PipelineOrchestrator(
        job_store=resolved_store,
        director_agent=director_agent,
        animator_agent=animator_agent,
        drawing_agent=drawing_agent,
        renderer_agent=renderer_agent,
        knowledge_base_service=BedrockKnowledgeBaseService(_FakeKbClient(), "kb-1"),
        agentcore_client=_FakeAgentCoreClient(),
        episode_store=resolved_episode_store,
        library_lookups=library_lookups or _make_library_lookups(),
    )
    orchestrator._sleep_with_backoff = lambda _attempt: None  # type: ignore[method-assign]
    return (
        orchestrator,
        resolved_store,
        director_agent,
        animator_agent,
        drawing_agent,
        renderer_agent,
        resolved_episode_store,
    )


def test_pipeline_orchestrator_marks_done_when_full_phase_5_pipeline_passes(
    capsys: Any,
) -> None:
    (
        orchestrator,
        store,
        director_agent,
        animator_agent,
        drawing_agent,
        renderer_agent,
        episode_store,
    ) = _make_orchestrator()

    result = orchestrator.run(job_id="job-1", prompt="Prompt", username="dev")

    assert result["result"] == "ok"
    assert result["draftS3Key"] == "drafts/dev/1/episode.json"
    assert store.failed_calls == []
    assert len(store.done_calls) == 1
    assert store.done_calls[0]["draft_s3_key"] == "drafts/dev/1/episode.json"
    assert "director_script_json" in store.done_calls[0]
    assert "animator_manifest_json" in store.done_calls[0]
    assert director_agent.calls[0]["input"].session_id == "session-1"
    assert "wall" in director_agent.calls[0]["input"].preferred_obstacle_library_names
    assert len(animator_agent.calls) == 2
    assert all(len(call["input"].acts) == 1 for call in animator_agent.calls)
    assert len(drawing_agent.calls) == 2  # one background per act
    assert all(c["input"].drawing_type == "background" for c in drawing_agent.calls)
    assert len(renderer_agent.calls) == len(_valid_animator_output().clips)
    assert all(len(call["input"].clips) == 1 for call in renderer_agent.calls)
    assert renderer_agent.calls[0]["input"].session_id == "session-1"
    assert episode_store.operations == [
        "put_draft_json",
        "put_draft_thumbnail",
        "put_draft_svg",
        "put_draft_svg",
        "put_draft_svg",
        "put_draft_svg",
    ]
    assert len(episode_store.json_put_calls) == 1
    assert len(episode_store.thumbnail_put_calls) == 1
    assert len(episode_store.svg_put_calls) == 4

    episode_json = json.loads(episode_store.json_put_calls[0]["body"])
    assert episode_json["schemaVersion"] == config.EPISODE_SCHEMA_VERSION
    assert episode_json["username"] == "dev"
    assert episode_json["contentHash"] == _compute_content_hash(episode_json)
    assert (
        episode_json["acts"][0]["approachText"]
        == _valid_director_output().acts[0].approach_description
    )
    assert (
        episode_json["acts"][0]["clips"]["choices"][0]["outcomeText"]
        == _valid_director_output().acts[0].choices[0].outcome_description
    )
    assert episode_store.thumbnail_put_calls[0]["key"] == "drafts/dev/1/thumb.svg"
    assert [call["key"] for call in episode_store.svg_put_calls] == [
        "drafts/dev/1/obstacles/bird.svg",
        "drafts/dev/1/obstacles/wall.svg",
        "drafts/dev/1/backgrounds/gentle-rolling-hills.svg",
        "drafts/dev/1/backgrounds/gentle-rolling-hills-1.svg",
    ]
    logs = capsys.readouterr().out
    assert "INFO [job-1] [RendererAgent.agent_call_complete]" in logs
    assert "Renderer clip act 0 approach completed and passed deterministic validation." in logs


def test_pipeline_orchestrator_retries_director_with_validation_errors_then_succeeds() -> None:
    orchestrator, store, _director, animator_agent, _drawing, renderer_agent, _episode_store = (
        _make_orchestrator(director_outputs=[_invalid_director_output(), _valid_director_output()])
    )

    orchestrator.run(job_id="job-1", prompt="Prompt", username="dev")

    assert len(animator_agent.calls) == 2
    assert len(renderer_agent.calls) == len(_valid_animator_output().clips)
    assert len(store.done_calls) == 1


def test_pipeline_orchestrator_normalises_director_text_limits_without_retry() -> None:
    director_output = _valid_director_output()
    director_output.title = "T" * (config.MAX_TITLE_LENGTH_CHARS + 5)
    director_output.description = "D" * (config.MAX_DESCRIPTION_LENGTH_CHARS + 5)
    director_output.acts[1].choices[1].label = "L" * (config.MAX_CHOICE_LABEL_LENGTH_CHARS + 5)

    (
        orchestrator,
        store,
        director_agent,
        animator_agent,
        _drawing,
        renderer_agent,
        _episode_store,
    ) = _make_orchestrator(director_outputs=[director_output])

    result = orchestrator.run(job_id="job-1", prompt="Prompt", username="dev")

    assert result["result"] == "ok"
    assert len(director_agent.calls) == 1
    assert director_agent.calls[0]["validation_errors"] is None
    assert len(animator_agent.calls) == 2
    assert len(renderer_agent.calls) == len(_valid_animator_output().clips)
    stored_script = json.loads(store.done_calls[0]["director_script_json"])
    assert len(stored_script["title"]) == config.MAX_TITLE_LENGTH_CHARS
    assert stored_script["title"].endswith("...")
    assert len(stored_script["description"]) == config.MAX_DESCRIPTION_LENGTH_CHARS
    assert stored_script["description"].endswith("...")
    assert (
        len(stored_script["acts"][1]["choices"][1]["label"])
        == config.MAX_CHOICE_LABEL_LENGTH_CHARS
    )
    assert stored_script["acts"][1]["choices"][1]["label"].endswith("...")


def test_pipeline_orchestrator_retries_animator_with_validation_errors_then_succeeds() -> None:
    orchestrator, store, _director, animator_agent, _drawing, renderer_agent, _episode_store = (
        _make_orchestrator(
            animator_outputs={
                0: [
                    _invalid_animator_output_for_act(0, "wall"),
                    _valid_animator_output_for_act(0),
                ],
                1: [_valid_animator_output_for_act(1)],
            }
        )
    )

    orchestrator.run(job_id="job-1", prompt="Prompt", username="dev")

    assert len(animator_agent.calls) == 3
    retry_call = next(
        call
        for call in animator_agent.calls
        if call["input"].acts[0].act_index == 0 and call["validation_errors"]
    )
    assert retry_call["validation_errors"]
    assert len(renderer_agent.calls) == len(_valid_animator_output().clips)
    assert len(store.done_calls) == 1
    assert store.failed_calls == []


def test_pipeline_orchestrator_normalises_small_grounded_animator_y_drift_without_retry() -> None:
    act_0_output = _valid_animator_output_for_act(0).model_copy(deep=True)
    for clip in act_0_output.clips:
        updated_keyframes = []
        for keyframe in clip.keyframes:
            if keyframe.is_grounded:
                updated_keyframes.append(
                    keyframe.model_copy(update={"character_y": keyframe.support_y - 8})
                )
            else:
                updated_keyframes.append(keyframe)
        clip.keyframes = updated_keyframes

    orchestrator, store, _director, animator_agent, _drawing, renderer_agent, _episode_store = (
        _make_orchestrator(
            animator_outputs={
                0: [act_0_output],
                1: [_valid_animator_output_for_act(1)],
            }
        )
    )

    orchestrator.run(job_id="job-1", prompt="Prompt", username="dev")

    assert len(animator_agent.calls) == 2
    assert len(renderer_agent.calls) == len(_valid_animator_output().clips)
    assert len(store.done_calls) == 1
    assert store.failed_calls == []


def test_pipeline_orchestrator_retries_renderer_with_validation_errors_then_succeeds() -> None:
    valid_animator_output = _valid_animator_output()
    (
        orchestrator,
        store,
        _director,
        _animator,
        _drawing,
        renderer_agent,
        _episode_store,
    ) = _make_orchestrator(
        renderer_outputs=[_invalid_renderer_output_for_input, _valid_renderer_output_for_input]
    )

    orchestrator.run(job_id="job-1", prompt="Prompt", username="dev")

    assert len(renderer_agent.calls) == len(valid_animator_output.clips) + 1
    assert renderer_agent.calls[-1]["validation_errors"]
    assert len(store.done_calls) == 1
    assert store.failed_calls == []


def test_pipeline_orchestrator_retries_renderer_when_grounded_travel_glides() -> None:
    valid_animator_output = _valid_animator_output()
    (
        orchestrator,
        store,
        _director,
        _animator,
        _drawing,
        renderer_agent,
        _episode_store,
    ) = _make_orchestrator(
        renderer_outputs=[_gliding_renderer_output_for_input, _valid_renderer_output_for_input]
    )

    orchestrator.run(job_id="job-1", prompt="Prompt", username="dev")

    assert len(renderer_agent.calls) == len(valid_animator_output.clips) + 1
    assert renderer_agent.calls[-1]["validation_errors"]
    assert any(
        "grounded travel clip must visibly animate" in error
        for error in renderer_agent.calls[-1]["validation_errors"]
    )
    assert len(store.done_calls) == 1
    assert store.failed_calls == []


def _eye_drifting_rendered_svg() -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 200" fill="none">'
        '<g id="linai">'
        '<g id="linai-body"><ellipse cx="104" cy="90" rx="34" ry="28" fill="#88eeff">'
        '<animate attributeName="fill" values="#88eeff;#aaf4ff;#88eeff" dur="1200ms" '
        'repeatCount="indefinite"/>'
        "</ellipse></g>"
        '<g id="linai-eye-left"><ellipse cx="92" cy="80" rx="8" ry="10" fill="#ffffff"/>'
        '<ellipse cx="97" cy="73" rx="4" ry="5" fill="#00eeff">'
        '<animate attributeName="cx" values="97;103;97" dur="900ms" repeatCount="indefinite"/>'
        "</ellipse></g>"
        '<g id="linai-eye-right"><ellipse cx="116" cy="78" rx="9" ry="11" fill="#ffffff"/>'
        '<ellipse cx="121" cy="71" rx="4" ry="5" fill="#00eeff">'
        '<animate attributeName="cx" values="121;127;121" dur="900ms" repeatCount="indefinite"/>'
        "</ellipse></g>"
        '<g id="linai-mouth"><path d="M104 102 Q112 108 120 103" stroke="#2299aa" fill="none"/>'
        "</g>"
        '<g id="linai-inner-patterns"><path d="M88 84 Q100 74 112 82" '
        'stroke="#ffffff" fill="none"/></g>'
        '<g id="linai-particles"><circle cx="100" cy="92" r="2" fill="#ffffff"/>'
        '<animateTransform attributeName="transform" type="translate" '
        'values="0 0;2 -2;0 0" dur="1100ms" repeatCount="indefinite"/>'
        "</g>"
        '<g id="linai-trails"><path d="M92 118 Q88 136 84 154" stroke="#88eeff" fill="none"/>'
        '<animateTransform attributeName="transform" type="scale" '
        'values="1 1;1.06 0.94;1 1" dur="1000ms" repeatCount="indefinite"/>'
        "</g>"
        "</g>"
        "</svg>"
    )


def _eye_drifting_renderer_output_for_input(renderer_input: Any) -> RendererOutput:
    return RendererOutput(
        clips=[
            SvgClip(
                act_index=clip.act_index,
                branch=clip.branch,
                choice_index=clip.choice_index,
                duration_ms=clip.duration_ms,
                svg=_eye_drifting_rendered_svg(),
            )
            for clip in renderer_input.clips
        ]
    )


def _eye_partial_scaling_rendered_svg() -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 200" fill="none">'
        '<g id="linai">'
        '<g id="linai-body"><ellipse cx="104" cy="90" rx="34" ry="28" fill="#88eeff">'
        '<animate attributeName="fill" values="#88eeff;#aaf4ff;#88eeff" dur="1200ms" '
        'repeatCount="indefinite"/>'
        "</ellipse></g>"
        '<g id="linai-eye-left"><ellipse cx="92" cy="80" rx="8" ry="10" fill="#ffffff">'
        '<animateTransform attributeName="transform" type="scale" '
        'values="1 0.55;1 1.35;1 0.9" dur="900ms" repeatCount="indefinite"/>'
        "</ellipse>"
        '<ellipse cx="97" cy="73" rx="4" ry="5" fill="#00eeff"/></g>'
        '<g id="linai-eye-right"><ellipse cx="116" cy="78" rx="9" ry="11" fill="#ffffff">'
        '<animateTransform attributeName="transform" type="scale" '
        'values="1 0.55;1 1.4;1 0.9" dur="900ms" repeatCount="indefinite"/>'
        "</ellipse>"
        '<ellipse cx="121" cy="71" rx="4" ry="5" fill="#00eeff"/></g>'
        '<g id="linai-mouth"><path d="M104 102 Q112 108 120 103" stroke="#2299aa" fill="none"/>'
        "</g>"
        '<g id="linai-inner-patterns"><path d="M88 84 Q100 74 112 82" '
        'stroke="#ffffff" fill="none"/></g>'
        '<g id="linai-particles"><circle cx="100" cy="92" r="2" fill="#ffffff"/>'
        '<animateTransform attributeName="transform" type="translate" '
        'values="0 0;2 -2;0 0" dur="1100ms" repeatCount="indefinite"/>'
        "</g>"
        '<g id="linai-trails"><path d="M92 118 Q88 136 84 154" stroke="#88eeff" fill="none"/>'
        '<animateTransform attributeName="transform" type="scale" '
        'values="1 1;1.06 0.94;1 1" dur="1000ms" repeatCount="indefinite"/>'
        "</g>"
        "</g>"
        "</svg>"
    )


def _eye_partial_scaling_renderer_output_for_input(renderer_input: Any) -> RendererOutput:
    return RendererOutput(
        clips=[
            SvgClip(
                act_index=clip.act_index,
                branch=clip.branch,
                choice_index=clip.choice_index,
                duration_ms=clip.duration_ms,
                svg=_eye_partial_scaling_rendered_svg(),
            )
            for clip in renderer_input.clips
        ]
    )


def test_pipeline_orchestrator_repairs_renderer_eye_drift_without_retry() -> None:
    valid_animator_output = _valid_animator_output()
    (
        orchestrator,
        store,
        _director,
        _animator,
        _drawing,
        renderer_agent,
        _episode_store,
    ) = _make_orchestrator(
        renderer_outputs=[_eye_drifting_renderer_output_for_input],
    )

    orchestrator.run(job_id="job-1", prompt="Prompt", username="dev")

    assert len(renderer_agent.calls) == len(valid_animator_output.clips)
    assert len(store.done_calls) == 1
    assert store.failed_calls == []


def test_pipeline_orchestrator_repairs_renderer_partial_eye_scaling_without_retry() -> None:
    valid_animator_output = _valid_animator_output()
    (
        orchestrator,
        store,
        _director,
        _animator,
        _drawing,
        renderer_agent,
        _episode_store,
    ) = _make_orchestrator(
        renderer_outputs=[_eye_partial_scaling_renderer_output_for_input],
    )

    orchestrator.run(job_id="job-1", prompt="Prompt", username="dev")

    assert len(renderer_agent.calls) == len(valid_animator_output.clips)
    assert len(store.done_calls) == 1
    assert store.failed_calls == []


def test_pipeline_orchestrator_retries_truncated_renderer_json_with_compact_guidance() -> None:
    valid_animator_output = _valid_animator_output()
    (
        orchestrator,
        store,
        _director,
        _animator,
        _drawing,
        renderer_agent,
        _episode_store,
    ) = _make_orchestrator(
        renderer_outputs=[
            RuntimeError("Renderer model returned invalid JSON"),
            _valid_renderer_output_for_input,
        ],
        renderer_output_tokens=config.MAX_OUTPUT_TOKENS_RENDERER_STAGE,
    )

    orchestrator.run(job_id="job-1", prompt="Prompt", username="dev")

    assert len(renderer_agent.calls) == len(valid_animator_output.clips) + 1
    assert any(
        call["validation_errors"]
        and "Previous attempt was truncated at the output token limit." in call["validation_errors"]
        for call in renderer_agent.calls
    )
    assert len(store.done_calls) == 1
    assert store.failed_calls == []


def test_pipeline_orchestrator_marks_failed_when_animator_validation_retries_exhausted() -> None:
    orchestrator, store, _director, animator_agent, _drawing, renderer_agent, _episode_store = (
        _make_orchestrator(
            animator_outputs={
                0: [
                    _invalid_animator_output_for_act(0, "wall"),
                    _invalid_animator_output_for_act(0, "wall"),
                    _invalid_animator_output_for_act(0, "wall"),
                ],
                1: [_valid_animator_output_for_act(1)],
            }
        )
    )

    result = orchestrator.run(job_id="job-1", prompt="Prompt", username="dev")

    assert result["result"] == "failed"
    assert result["reason"] == "animator_validation_retries_exhausted"
    assert len(animator_agent.calls) == config.MAX_AGENT_RETRY_COUNT + 2
    assert renderer_agent.calls == []
    assert store.done_calls == []
    assert len(store.failed_calls) == 1


def test_pipeline_orchestrator_marks_failed_when_animator_retry_exceeds_deadline_budget() -> None:
    orchestrator, store, _director, animator_agent, _drawing, renderer_agent, _episode_store = (
        _make_orchestrator(
            animator_outputs={
                0: [_invalid_animator_output_for_act(0, "wall")],
                1: [_valid_animator_output_for_act(1)],
            }
        )
    )
    orchestrator._retry_exceeds_deadline_budget = lambda *, last_attempt_elapsed_ms: True  # type: ignore[method-assign]

    result = orchestrator.run(job_id="job-1", prompt="Prompt", username="dev")

    assert result["result"] == "failed"
    assert result["reason"] == "job_deadline_exhausted"
    assert len(animator_agent.calls) == 2
    assert renderer_agent.calls == []
    assert store.done_calls == []
    assert len(store.failed_calls) == 1
    assert (
        "Animator retry skipped because the remaining job deadline is too short"
        in store.failed_calls[0]["error_message"]
    )


def test_pipeline_orchestrator_marks_failed_when_stage_start_budget_is_too_low() -> None:
    orchestrator, store, _director, animator_agent, _drawing, renderer_agent, _episode_store = (
        _make_orchestrator()
    )

    result = orchestrator.run(
        job_id="job-1",
        prompt="Prompt",
        username="dev",
        remaining_time_provider=lambda: 1_000,
    )

    assert result["result"] == "failed"
    assert result["reason"] == "job_deadline_exhausted"
    assert animator_agent.calls == []
    assert renderer_agent.calls == []
    assert store.done_calls == []
    assert len(store.failed_calls) == 1
    assert "minimum stage-start budget" in store.failed_calls[0]["error_message"]


def test_pipeline_orchestrator_marks_failed_when_animator_model_call_retries_exhausted() -> None:
    orchestrator, store, _director, animator_agent, _drawing, renderer_agent, _episode_store = (
        _make_orchestrator(
            animator_outputs={
                0: [
                    RuntimeError("timeout-1"),
                    RuntimeError("timeout-2"),
                    RuntimeError("timeout-3"),
                ],
                1: [_valid_animator_output_for_act(1)],
            }
        )
    )

    result = orchestrator.run(job_id="job-1", prompt="Prompt", username="dev")

    assert result["result"] == "failed"
    assert result["reason"] == "animator_model_call_failed"
    assert len(animator_agent.calls) == config.MAX_AGENT_RETRY_COUNT + 2
    assert (
        sum(1 for call in animator_agent.calls if call["input"].acts[0].act_index == 0)
        == config.MAX_AGENT_RETRY_COUNT + 1
    )
    assert renderer_agent.calls == []
    assert store.done_calls == []
    assert len(store.failed_calls) == 1


def test_pipeline_orchestrator_marks_failed_when_animator_output_tokens_exceed_ceiling() -> None:
    orchestrator, store, _director, _animator, _drawing, renderer_agent, _episode_store = (
        _make_orchestrator(animator_output_tokens=999999)
    )

    orchestrator.run(job_id="job-1", prompt="Prompt", username="dev")

    assert renderer_agent.calls == []
    assert store.done_calls == []
    assert len(store.failed_calls) == 1
    assert "Animator act 0 output token ceiling exceeded" in store.failed_calls[0]["error_message"]


def test_pipeline_orchestrator_builds_animator_input_from_config() -> None:
    orchestrator, _store, _director, animator_agent, _drawing, _renderer, _episode_store = (
        _make_orchestrator()
    )

    orchestrator.run(job_id="job-1", prompt="Prompt", username="dev")

    animator_inputs_by_act = {
        call["input"].acts[0].act_index: call["input"] for call in animator_agent.calls
    }
    assert set(animator_inputs_by_act) == {0, 1}

    act_0_input = animator_inputs_by_act[0]
    assert len(act_0_input.acts) == 1
    assert act_0_input.walk_duration_seconds == 8
    assert act_0_input.canvas_width == 800
    assert act_0_input.canvas_height == 200
    assert act_0_input.ground_line_y == 160
    assert act_0_input.handoff_character_x == config.HANDOFF_CHARACTER_X
    assert act_0_input.requires_handoff_in is False
    assert act_0_input.requires_handoff_out is False

    act_1_input = animator_inputs_by_act[1]
    assert act_1_input.handoff_character_x == config.HANDOFF_CHARACTER_X
    assert act_1_input.requires_handoff_in is True
    assert act_1_input.requires_handoff_out is False


def test_pipeline_orchestrator_draws_unknown_obstacle_once_and_reuses_svg() -> None:
    store = _FakeJobStore()
    episode_store = _FakeEpisodeStore()
    director_output = DirectorOutput(
        title="Dragon Day",
        description="Linai meets a dragon twice.",
        acts=[
            Act(
                act_index=0,
                obstacle_type="dragon",
                approach_description="Linai stops at a dragon.",
                drawing_prompt=_DRAW_PROMPT,
                background_drawing_prompt=_BG_PROMPT,
                choices=[
                    Choice(label="Wave", is_winning=True, outcome_description="The dragon bows."),
                    Choice(label="Hide", is_winning=False, outcome_description="Linai trips."),
                ],
            ),
            Act(
                act_index=1,
                obstacle_type="dragon",
                approach_description="Another dragon appears.",
                drawing_prompt=_DRAW_PROMPT,
                background_drawing_prompt=_BG_PROMPT,
                choices=[
                    Choice(
                        label="Smile",
                        is_winning=True,
                        outcome_description="The dragon smiles.",
                    ),
                    Choice(label="Run", is_winning=False, outcome_description="Dust everywhere."),
                ],
            ),
        ],
    )
    animator_output = AnimatorOutput(
        clips=[
            ClipManifest(
                act_index=0,
                obstacle_type="dragon",
                branch="approach",
                choice_index=None,
                duration_ms=8000,
                obstacle_x=400,
                keyframes=_keyframes(
                    40,
                    config.MAX_GROUNDED_APPROACH_CHARACTER_X,
                    "scared",
                    "stop",
                ),
            ),
            ClipManifest(
                act_index=0,
                obstacle_type="dragon",
                branch="win",
                choice_index=0,
                duration_ms=4000,
                obstacle_x=400,
                keyframes=_keyframes(320, 500, "happy", "celebrate"),
            ),
            ClipManifest(
                act_index=0,
                obstacle_type="dragon",
                branch="fail",
                choice_index=1,
                duration_ms=3000,
                obstacle_x=400,
                keyframes=_keyframes(320, 200, "sad", "fall"),
            ),
            ClipManifest(
                act_index=1,
                obstacle_type="dragon",
                branch="approach",
                choice_index=None,
                duration_ms=8000,
                obstacle_x=420,
                keyframes=_keyframes(
                    50,
                    config.MAX_GROUNDED_APPROACH_CHARACTER_X,
                    "scared",
                    "stop",
                    start_handoff=True,
                ),
            ),
            ClipManifest(
                act_index=1,
                obstacle_type="dragon",
                branch="win",
                choice_index=0,
                duration_ms=4000,
                obstacle_x=420,
                keyframes=_keyframes(330, 510, "happy", "celebrate"),
            ),
            ClipManifest(
                act_index=1,
                obstacle_type="dragon",
                branch="fail",
                choice_index=1,
                duration_ms=3000,
                obstacle_x=420,
                keyframes=_keyframes(330, 210, "sad", "fall"),
            ),
        ]
    )
    drawing_svg = (
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
    orchestrator = PipelineOrchestrator(
        job_store=store,
        director_agent=_FakeDirectorAgent(outputs=[director_output]),
        animator_agent=_FakeAnimatorAgent(
            outputs={
                0: [_output_for_act(animator_output, 0)],
                1: [_output_for_act(animator_output, 1)],
            }
        ),
        drawing_agent=_FakeDrawingAgent(
            outputs_by_identity={
                ("obstacle", "dragon"): [DrawingOutput(svg=drawing_svg)],
                ("background", "gentle-rolling-hills"): [
                    DrawingOutput(svg=_VALID_BACKGROUND_SVG)
                ],
                ("background", "gentle-rolling-hills-1"): [
                    DrawingOutput(svg=_VALID_BACKGROUND_SVG)
                ],
            }
        ),
        renderer_agent=_FakeRendererAgent(outputs=[_valid_renderer_output_for_input]),
        knowledge_base_service=BedrockKnowledgeBaseService(_FakeKbClient(), "kb-1"),
        agentcore_client=_FakeAgentCoreClient(),
        episode_store=episode_store,
        library_lookups=_make_library_lookups(get_obstacle_svg=lambda _slug: None),
    )
    orchestrator._sleep_with_backoff = lambda _attempt: None  # type: ignore[method-assign]

    orchestrator.run(job_id="job-1", prompt="Prompt", username="dev")

    manifest = json.loads(store.done_calls[0]["animator_manifest_json"])
    assert len(manifest["clips"]) == 6
    assert all(clip["obstacle_type"] == "dragon" for clip in manifest["clips"])
    assert all("obstacle-root" in clip["obstacle_svg_override"] for clip in manifest["clips"])
    assert len(orchestrator._drawing_agent.calls) == 3  # type: ignore[attr-defined]  # 1 obstacle + 2 backgrounds
    assert episode_store.json_put_calls[0]["key"] == "drafts/dev/1/episode.json"


def test_pipeline_orchestrator_retries_drawing_when_animated_part_is_static() -> None:
    store = _FakeJobStore()
    episode_store = _FakeEpisodeStore()
    static_drawing_svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 150">'
        '<g id="obstacle-root">'
        '<path id="obstacle-main" d="M15 140 L60 20 L105 140 Z" fill="white"/>'
        '<g id="obstacle-animated-part"><path d="M60 20 C72 14 84 10 94 12"/></g>'
        "</g>"
        "</svg>"
    )
    animated_drawing_svg = (
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
    animator_outputs = {
        0: [
            AnimatorOutput(
                clips=[
                    ClipManifest(
                        act_index=0,
                        obstacle_type="dragon",
                        branch="approach",
                        choice_index=None,
                        duration_ms=8000,
                        obstacle_x=400,
                        keyframes=_keyframes(
                            40,
                            config.MAX_GROUNDED_APPROACH_CHARACTER_X,
                            "scared",
                            "stop",
                        ),
                    ),
                    ClipManifest(
                        act_index=0,
                        obstacle_type="dragon",
                        branch="win",
                        choice_index=0,
                        duration_ms=4000,
                        obstacle_x=400,
                        keyframes=_keyframes(320, 500, "happy", "celebrate"),
                    ),
                    ClipManifest(
                        act_index=0,
                        obstacle_type="dragon",
                        branch="fail",
                        choice_index=1,
                        duration_ms=3000,
                        obstacle_x=400,
                        keyframes=_keyframes(320, 200, "sad", "fall"),
                    ),
                ]
            )
        ],
        1: [_valid_animator_output_for_act(1)],
    }
    orchestrator, _store, _director, _animator, drawing_agent, _renderer, _episode_store = (
        _make_orchestrator(
            store=store,
            director_outputs=[
                DirectorOutput(
                    title="Dragon Day",
                    description="Linai meets a dragon.",
                    acts=[
                        Act(
                            act_index=0,
                            obstacle_type="dragon",
                            approach_description="Linai stops at a dragon.",
                            drawing_prompt=_DRAW_PROMPT,
                            background_drawing_prompt=_BG_PROMPT,
                            choices=[
                                Choice(
                                    label="Wave",
                                    is_winning=True,
                                    outcome_description="The dragon bows.",
                                ),
                                Choice(
                                    label="Hide",
                                    is_winning=False,
                                    outcome_description="Linai trips.",
                                ),
                            ],
                        ),
                        Act(
                            act_index=1,
                            obstacle_type="bird",
                            approach_description="A bird blocks the path.",
                            drawing_prompt=_DRAW_PROMPT,
                            background_drawing_prompt=_BG_PROMPT,
                            choices=[
                                Choice(
                                    label="Wave",
                                    is_winning=True,
                                    outcome_description="Bird smiles.",
                                ),
                                Choice(
                                    label="Hide",
                                    is_winning=False,
                                    outcome_description="Trips.",
                                ),
                            ],
                        ),
                    ],
                )
            ],
            animator_outputs=animator_outputs,
            drawing_outputs_by_identity={
                ("obstacle", "dragon"): [
                    DrawingOutput(svg=static_drawing_svg),
                    DrawingOutput(svg=animated_drawing_svg),
                ],
                ("background", "gentle-rolling-hills"): [
                    DrawingOutput(svg=_VALID_BACKGROUND_SVG)
                ],
                ("background", "gentle-rolling-hills-1"): [
                    DrawingOutput(svg=_VALID_BACKGROUND_SVG)
                ],
            },
            episode_store=episode_store,
            library_lookups=_make_library_lookups(
                get_obstacle_svg=lambda slug: animated_drawing_svg if slug == "bird" else None,
            ),
        )
    )

    orchestrator.run(job_id="job-1", prompt="Prompt", username="dev")

    assert len(drawing_agent.calls) == 4  # 2 obstacle attempts + 2 backgrounds
    retry_calls = [
        call
        for call in drawing_agent.calls
        if call["input"].drawing_type == "obstacle" and call["validation_errors"]
    ]
    assert len(retry_calls) == 1
    assert any("obstacle-animated-part" in error for error in retry_calls[0]["validation_errors"])
    assert len(store.done_calls) == 1


def test_orchestrator_calls_drawing_agent_for_background(capsys: Any) -> None:
    """Orchestrator calls DrawingAgent with drawing_type='background' for each act."""
    orchestrator, store, _director, _animator, drawing_agent, _renderer, _episode_store = (
        _make_orchestrator()
    )

    result = orchestrator.run(job_id="job-1", prompt="Prompt", username="dev")

    assert result["result"] == "ok"
    bg_calls = [c for c in drawing_agent.calls if c["input"].drawing_type == "background"]
    assert len(bg_calls) == 2
    assert {call["input"].obstacle_type for call in bg_calls} == {
        "gentle-rolling-hills",
        "gentle-rolling-hills-1",
    }
    manifest = json.loads(store.done_calls[0]["animator_manifest_json"])
    assert all(clip.get("background_svg") for clip in manifest["clips"])


def test_pipeline_orchestrator_reuses_library_backgrounds_without_drawing() -> None:
    background_library_calls: list[str] = []

    def _get_background_svg(slug: str) -> str | None:
        background_library_calls.append(slug)
        return _VALID_BACKGROUND_SVG if slug == "beach" else None

    orchestrator, store, _director, _animator, drawing_agent, _renderer, _episode_store = (
        _make_orchestrator(
            library_lookups=_make_library_lookups(
                find_background_library_slug=lambda *_texts: "beach",
                get_background_svg=_get_background_svg,
            ),
        )
    )

    result = orchestrator.run(job_id="job-1", prompt="Prompt", username="dev")

    assert result["result"] == "ok"
    # Act 0 uses the library background; act 1 generates since the same slug
    # was already used, so exactly one drawing call is made.
    assert len(drawing_agent.calls) == 1
    assert len(store.done_calls) == 1
    assert background_library_calls == ["beach"]


def test_pipeline_orchestrator_suffixes_generated_background_when_library_slug_taken() -> None:
    orchestrator, store, _director, _animator, drawing_agent, _renderer, episode_store = (
        _make_orchestrator(
            library_lookups=_make_library_lookups(
                find_background_library_slug=lambda *_texts: "deep-outer-space",
                get_background_svg=(
                    lambda slug: _VALID_BACKGROUND_SVG if slug == "deep-outer-space" else None
                ),
                prompt_to_background_slug=lambda _: "deep-outer-space",
            ),
            drawing_outputs_by_identity={
                ("background", "deep-outer-space-1"): [DrawingOutput(svg=_VALID_BACKGROUND_SVG)]
            },
        )
    )

    result = orchestrator.run(job_id="job-1", prompt="Prompt", username="dev")

    assert result["result"] == "ok"
    assert len(store.done_calls) == 1
    bg_calls = [c for c in drawing_agent.calls if c["input"].drawing_type == "background"]
    assert len(bg_calls) == 1
    assert bg_calls[0]["input"].obstacle_type == "deep-outer-space-1"
    assert [call["key"] for call in episode_store.svg_put_calls] == [
        "drafts/dev/1/obstacles/bird.svg",
        "drafts/dev/1/obstacles/wall.svg",
        "drafts/dev/1/backgrounds/deep-outer-space.svg",
        "drafts/dev/1/backgrounds/deep-outer-space-1.svg",
    ]


def test_pipeline_orchestrator_keeps_distinct_generated_background_names_unsuffixed() -> None:
    forest_prompt = (
        "Draw a calm forest moon glow background with floating mist and soft stars above. "
        * 2
    )
    ocean_prompt = (
        "Draw a sunset ocean cliff background with glowing waves and warm clouds above. " * 2
    )
    director_output = DirectorOutput(
        title="Two Skies",
        description="Linai crosses two very different scenes.",
        acts=[
            Act(
                act_index=0,
                obstacle_type="wall",
                approach_description="Linai reaches a wall.",
                drawing_prompt=_DRAW_PROMPT,
                background_drawing_prompt=forest_prompt,
                choices=[
                    Choice(label="Knock", is_winning=True, outcome_description="Door opens."),
                    Choice(label="Jump", is_winning=False, outcome_description="Falls down."),
                ],
            ),
            Act(
                act_index=1,
                obstacle_type="bird",
                approach_description="A bird blocks the path.",
                drawing_prompt=_DRAW_PROMPT,
                background_drawing_prompt=ocean_prompt,
                choices=[
                    Choice(label="Wave", is_winning=True, outcome_description="Bird smiles."),
                    Choice(label="Hide", is_winning=False, outcome_description="Trips."),
                ],
            ),
        ],
    )

    orchestrator, store, _director, _animator, drawing_agent, _renderer, episode_store = (
        _make_orchestrator(
            director_outputs=[director_output],
            library_lookups=_make_library_lookups(
                find_background_library_slug=lambda *_texts: None,
                prompt_to_background_slug=(
                    lambda prompt: (
                        "forest-moon-glow"
                        if prompt == forest_prompt
                        else "sunset-ocean-cliff"
                    )
                ),
            ),
            drawing_outputs_by_identity={
                ("background", "forest-moon-glow"): [DrawingOutput(svg=_VALID_BACKGROUND_SVG)],
                ("background", "sunset-ocean-cliff"): [
                    DrawingOutput(svg=_VALID_BACKGROUND_SVG)
                ],
            },
        )
    )

    result = orchestrator.run(job_id="job-1", prompt="Prompt", username="dev")

    assert result["result"] == "ok"
    assert len(store.done_calls) == 1
    bg_calls = [c for c in drawing_agent.calls if c["input"].drawing_type == "background"]
    assert [call["input"].obstacle_type for call in bg_calls] == [
        "forest-moon-glow",
        "sunset-ocean-cliff",
    ]
    assert [call["key"] for call in episode_store.svg_put_calls] == [
        "drafts/dev/1/obstacles/bird.svg",
        "drafts/dev/1/obstacles/wall.svg",
        "drafts/dev/1/backgrounds/forest-moon-glow.svg",
        "drafts/dev/1/backgrounds/sunset-ocean-cliff.svg",
    ]


def test_orchestrator_passes_drawing_prompt_to_drawing_agent() -> None:
    """Orchestrator passes Director's drawing_prompt to DrawingAgent for non-library obstacles."""
    custom_prompt = (
        "Draw a ferocious blue dragon with iridescent scales "
        "and wisps of silver smoke rising from its nostrils. "
    ) * 2
    drawing_svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 150">'
        '<g id="obstacle-root">'
        '<path id="obstacle-main" d="M15 140 L60 20 L105 140 Z" fill="white"/>'
        '<g id="obstacle-animated-part"><path d="M60 20 C72 14 84 10 94 12"/>'
        '<animateTransform attributeName="transform" type="rotate" '
        'values="-3 60 20;3 60 20;-3 60 20" dur="1200ms" '
        'repeatCount="indefinite"/>'
        "</g></g></svg>"
    )
    director_output = DirectorOutput(
        title="Dragon Day",
        description="Linai meets a dragon.",
        acts=[
            Act(
                act_index=0,
                obstacle_type="dragon",
                approach_description="Linai stops at a dragon.",
                drawing_prompt=custom_prompt,
                background_drawing_prompt=_BG_PROMPT,
                choices=[
                    Choice(label="Wave", is_winning=True, outcome_description="Bows."),
                    Choice(label="Hide", is_winning=False, outcome_description="Trips."),
                ],
            ),
            Act(
                act_index=1,
                obstacle_type="dragon",
                approach_description="Another dragon.",
                drawing_prompt=custom_prompt,
                background_drawing_prompt=_BG_PROMPT,
                choices=[
                    Choice(label="Smile", is_winning=True, outcome_description="Smiles."),
                    Choice(label="Run", is_winning=False, outcome_description="Dust."),
                ],
            ),
        ],
    )
    dragon_clips_0 = AnimatorOutput(
        clips=[
            ClipManifest(
                act_index=0,
                obstacle_type="dragon",
                branch="approach",
                choice_index=None,
                duration_ms=8000,
                obstacle_x=400,
                keyframes=_keyframes(
                    40,
                    config.MAX_GROUNDED_APPROACH_CHARACTER_X,
                    "scared",
                    "stop",
                ),
            ),
            ClipManifest(
                act_index=0,
                obstacle_type="dragon",
                branch="win",
                choice_index=0,
                duration_ms=4000,
                obstacle_x=400,
                keyframes=_keyframes(320, 500, "happy", "celebrate"),
            ),
            ClipManifest(
                act_index=0,
                obstacle_type="dragon",
                branch="fail",
                choice_index=1,
                duration_ms=3000,
                obstacle_x=400,
                keyframes=_keyframes(320, 200, "sad", "fall"),
            ),
        ]
    )
    dragon_clips_1 = AnimatorOutput(
        clips=[
            ClipManifest(
                act_index=1,
                obstacle_type="dragon",
                branch="approach",
                choice_index=None,
                duration_ms=8000,
                obstacle_x=420,
                keyframes=_keyframes(
                    50,
                    config.MAX_GROUNDED_APPROACH_CHARACTER_X,
                    "scared",
                    "stop",
                    start_handoff=True,
                ),
            ),
            ClipManifest(
                act_index=1,
                obstacle_type="dragon",
                branch="win",
                choice_index=0,
                duration_ms=4000,
                obstacle_x=420,
                keyframes=_keyframes(330, 510, "happy", "celebrate"),
            ),
            ClipManifest(
                act_index=1,
                obstacle_type="dragon",
                branch="fail",
                choice_index=1,
                duration_ms=3000,
                obstacle_x=420,
                keyframes=_keyframes(330, 210, "sad", "fall"),
            ),
        ]
    )
    orchestrator, _store, _director, _animator, drawing_agent, _renderer, _episode_store = (
        _make_orchestrator(
            director_outputs=[director_output],
            animator_outputs={0: [dragon_clips_0], 1: [dragon_clips_1]},
            drawing_outputs_by_identity={
                ("obstacle", "dragon"): [DrawingOutput(svg=drawing_svg)],
                ("background", "gentle-rolling-hills"): [
                    DrawingOutput(svg=_VALID_BACKGROUND_SVG)
                ],
                ("background", "gentle-rolling-hills-1"): [
                    DrawingOutput(svg=_VALID_BACKGROUND_SVG)
                ],
            },
            library_lookups=_make_library_lookups(get_obstacle_svg=lambda _slug: None),
        )
    )

    orchestrator.run(job_id="job-1", prompt="Prompt", username="dev")

    obstacle_calls = [c for c in drawing_agent.calls if c["input"].drawing_type == "obstacle"]
    assert len(obstacle_calls) == 1  # reused for both acts
    assert obstacle_calls[0]["input"].drawing_prompt == custom_prompt


def test_pipeline_orchestrator_cleans_up_episode_json_when_thumbnail_write_fails() -> None:
    episode_store = _FakeEpisodeStore(fail_thumbnail=True)
    orchestrator, store, _director, _animator, _drawing, _renderer, _episode_store = (
        _make_orchestrator(episode_store=episode_store)
    )

    result = orchestrator.run(job_id="job-1", prompt="Prompt", username="dev")

    assert result["result"] == "failed"
    assert result["reason"] == "draft_thumbnail_write_failed"
    assert store.done_calls == []
    assert len(store.failed_calls) == 1
    assert episode_store.operations == [
        "put_draft_json",
        "put_draft_thumbnail",
        "delete_draft_object",
        "delete_draft_object",
    ]
    assert episode_store.delete_calls == [
        "drafts/dev/1/thumb.svg",
        "drafts/dev/1/episode.json",
    ]


def test_pipeline_orchestrator_cleans_up_written_artifacts_when_supporting_svg_write_fails(
) -> None:
    episode_store = _FakeEpisodeStore(
        fail_svg_key="drafts/dev/1/backgrounds/gentle-rolling-hills.svg"
    )
    orchestrator, store, _director, _animator, _drawing, _renderer, _episode_store = (
        _make_orchestrator(episode_store=episode_store)
    )

    result = orchestrator.run(job_id="job-1", prompt="Prompt", username="dev")

    assert result["result"] == "failed"
    assert result["reason"] == "draft_supporting_svg_write_failed"
    assert store.done_calls == []
    assert len(store.failed_calls) == 1
    assert episode_store.operations == [
        "put_draft_json",
        "put_draft_thumbnail",
        "put_draft_svg",
        "put_draft_svg",
        "put_draft_svg",
        "delete_draft_object",
        "delete_draft_object",
        "delete_draft_object",
        "delete_draft_object",
    ]
    assert episode_store.delete_calls == [
        "drafts/dev/1/obstacles/wall.svg",
        "drafts/dev/1/obstacles/bird.svg",
        "drafts/dev/1/thumb.svg",
        "drafts/dev/1/episode.json",
    ]


def test_pipeline_orchestrator_raises_when_job_not_in_generating_state() -> None:
    class _PendingJobStore(_FakeJobStore):
        def get_job(self, _job_id: str) -> dict[str, str]:
            return {"status": "PENDING"}

    orchestrator = PipelineOrchestrator(
        job_store=_PendingJobStore(),
        director_agent=_FakeDirectorAgent(outputs=[_valid_director_output()]),
        animator_agent=_FakeAnimatorAgent(
            outputs={
                0: [_valid_animator_output_for_act(0)],
                1: [_valid_animator_output_for_act(1)],
            }
        ),
        drawing_agent=_FakeDrawingAgent(),
        renderer_agent=_FakeRendererAgent(outputs=[_valid_renderer_output_for_input]),
        knowledge_base_service=BedrockKnowledgeBaseService(_FakeKbClient(), "kb-1"),
        agentcore_client=_FakeAgentCoreClient(),
        episode_store=_FakeEpisodeStore(),
        library_lookups=_make_library_lookups(),
    )

    with pytest.raises(RuntimeError, match="not in GENERATING state"):
        orchestrator.run(job_id="job-1", prompt="Prompt", username="dev")
