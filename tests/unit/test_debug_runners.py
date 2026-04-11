"""Unit tests for local debug runner helpers."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
from types import SimpleNamespace

from pipeline import config
from pipeline.models import (
    Act,
    AnimatorInput,
    AnimatorOutput,
    Choice,
    ClipManifest,
    DirectorInput,
    DirectorOutput,
    Keyframe,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_BG_PROMPT = "Draw a simple background with gentle rolling hills and a clear blue sky above. " * 2


def _load_script_module(relative_path: str, module_name: str) -> object:
    """Load one hyphenated script file as an importable test module."""
    script_path = PROJECT_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        msg = f"Unable to load script module: {script_path}"
        raise RuntimeError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_director_output(*, act_count: int) -> DirectorOutput:
    """Build a minimally valid DirectorOutput shape for script-runner tests."""
    acts = []
    for act_index in range(act_count):
        acts.append(
            Act(
                act_index=act_index,
                obstacle_type=f"obstacle-{act_index}",
                approach_description=f"Linai meets obstacle {act_index}.",
                drawing_prompt=_BG_PROMPT,
                background_drawing_prompt=_BG_PROMPT,
                choices=[
                    Choice(
                        label="Try kindly",
                        is_winning=True,
                        outcome_description="It works.",
                    ),
                    Choice(
                        label="Rush in",
                        is_winning=False,
                        outcome_description="It fails.",
                    ),
                ],
            )
        )
    return DirectorOutput(
        title="Debug story",
        description="A debug story for local runner tests.",
        acts=acts,
    )


class _FakeDirectorAgent:
    """Small fake Director agent that returns scripted outputs per attempt."""

    def __init__(self, outputs: list[DirectorOutput]) -> None:
        self._outputs = outputs
        self.calls: list[list[str] | None] = []
        self._last_prompt = ""
        self._last_response_text = ""
        self._last_usage = SimpleNamespace(input_tokens=0, output_tokens=0)

    def run(
        self,
        input: DirectorInput,
        validation_errors: list[str] | None = None,
    ) -> DirectorOutput:
        attempt = len(self.calls)
        self.calls.append(validation_errors)
        self._last_prompt = (
            f"attempt={attempt} prompt for {input.job_id} validation_errors={validation_errors}"
        )
        output = self._outputs[attempt]
        self._last_response_text = output.model_dump_json(indent=2)
        self._last_usage = SimpleNamespace(input_tokens=10 + attempt, output_tokens=20 + attempt)
        return output

    def get_last_prompt(self) -> str:
        return self._last_prompt

    def get_last_response_text(self) -> str:
        return self._last_response_text

    def get_last_usage(self) -> SimpleNamespace:
        return self._last_usage


class _FakeAnimatorAgent:
    """Small fake Animator agent that supports per-act retries in tests."""

    def __init__(
        self,
        outputs_by_act: dict[int, list[AnimatorOutput | Exception]],
        *,
        calls: list[dict[str, object]] | None = None,
        counts_by_act: dict[int, int] | None = None,
    ) -> None:
        self._outputs_by_act = outputs_by_act
        self.calls = [] if calls is None else calls
        self._counts_by_act = {} if counts_by_act is None else counts_by_act
        self._last_prompt = ""
        self._last_response_text = ""
        self._last_usage = SimpleNamespace(input_tokens=0, output_tokens=0)

    def spawn_parallel_worker(self) -> _FakeAnimatorAgent:
        return _FakeAnimatorAgent(
            self._outputs_by_act,
            calls=self.calls,
            counts_by_act=self._counts_by_act,
        )

    def run(
        self,
        input: AnimatorInput,
        validation_errors: list[str] | None = None,
    ) -> AnimatorOutput:
        act_index = input.acts[0].act_index
        attempt = self._counts_by_act.get(act_index, 0)
        self._counts_by_act[act_index] = attempt + 1
        self.calls.append(
            {
                "act_index": act_index,
                "validation_errors": validation_errors,
            }
        )
        self._last_prompt = (
            f"act={act_index} attempt={attempt} validation_errors={validation_errors}"
        )
        output = self._outputs_by_act[act_index][attempt]
        if isinstance(output, Exception):
            self._last_response_text = ""
            self._last_usage = SimpleNamespace(input_tokens=0, output_tokens=0)
            raise output

        self._last_response_text = output.model_dump_json(indent=2)
        self._last_usage = SimpleNamespace(input_tokens=20 + act_index, output_tokens=30 + attempt)
        return output

    def get_last_prompt(self) -> str:
        return self._last_prompt

    def get_last_response_text(self) -> str:
        return self._last_response_text

    def get_last_usage(self) -> SimpleNamespace:
        return self._last_usage


def _valid_animator_output_for_act(
    *,
    act_index: int,
    obstacle_type: str,
    choice_count: int,
    requires_handoff_in: bool = False,
    requires_handoff_out: bool = False,
) -> AnimatorOutput:
    clips = [
        ClipManifest(
            act_index=act_index,
            obstacle_type=obstacle_type,
            branch="approach",
            choice_index=None,
            duration_ms=8000,
            obstacle_x=400,
            keyframes=[
                Keyframe(
                time_ms=0,
                    character_x=config.HANDOFF_CHARACTER_X if requires_handoff_in else 40,
                    character_y=160,
                    support_y=160,
                    is_grounded=True,
                    is_handoff_pose=requires_handoff_in,
                    expression="calm",
                    action="walking",
                ),
                Keyframe(
                    time_ms=8000,
                    character_x=config.MAX_GROUNDED_APPROACH_CHARACTER_X,
                    character_y=160,
                    support_y=160,
                    is_grounded=True,
                    expression="curious",
                    action="stopping",
                ),
            ],
        )
    ]
    for choice_index in range(choice_count):
        clips.append(
            ClipManifest(
                act_index=act_index,
                obstacle_type=obstacle_type,
                branch="win" if choice_index == 0 else "fail",
                choice_index=choice_index,
                duration_ms=4000,
                obstacle_x=400,
                keyframes=[
                    Keyframe(
                        time_ms=0,
                        character_x=config.HANDOFF_CHARACTER_X,
                        character_y=160,
                        support_y=160,
                        is_grounded=True,
                        expression="focused",
                        action="reacting",
                    ),
                    Keyframe(
                        time_ms=4000,
                        character_x=(
                            config.HANDOFF_CHARACTER_X
                            if requires_handoff_out
                            else (500 if choice_index == 0 else 220)
                        ),
                        character_y=160,
                        support_y=160,
                        is_grounded=True,
                        is_handoff_pose=requires_handoff_out,
                        expression="happy" if choice_index == 0 else "sad",
                        action="celebrating" if choice_index == 0 else "retreating",
                    ),
                ],
            )
        )
    return AnimatorOutput(clips=clips)


def test_run_director_debug_session_retries_script_validation_and_writes_output(
    tmp_path: Path,
) -> None:
    module = _load_script_module(
        "scripts/run-director-agent.py",
        "run_director_agent_test_module",
    )
    director_input = DirectorInput(
        prompt="Linai meets a butterfly, a computer, and an octopus.",
        username="debug-user",
        job_id="debug-director",
        session_id="debug-session",
        rag_context="Linai is playful.",
        preferred_obstacle_library_names=["wall", "bird"],
    )
    fake_agent = _FakeDirectorAgent(
        outputs=[
            _make_director_output(act_count=config.MAX_OBSTACLE_ACTS + 1),
            _make_director_output(act_count=config.MAX_OBSTACLE_ACTS),
        ]
    )

    exit_code = module.run_director_debug_session(
        director_input=director_input,
        output_dir=tmp_path,
        output_prefix="debug-director",
        validation_errors=[],
        agent=fake_agent,
    )

    assert exit_code == 0
    assert fake_agent.calls[0] is None
    assert fake_agent.calls[1] is not None
    assert any("acts count must be between" in error for error in fake_agent.calls[1] or [])
    assert (tmp_path / "debug-director.json").exists()
    assert (tmp_path / "debug-director.attempt-0.json").exists()
    assert (tmp_path / "debug-director.attempt-1.json").exists()
    assert (tmp_path / "debug-director.prompt.txt").exists()
    assert (tmp_path / "debug-director.raw.txt").exists()


def test_build_animator_input_raises_helpful_error_for_missing_director_json() -> None:
    module = _load_script_module(
        "scripts/run-animator-agent.py",
        "run_animator_agent_test_module",
    )
    args = argparse.Namespace(
        director_output_path="tmp/director-agent/missing-debug-director.json",
        job_id="debug-animator",
        session_id="debug-session",
        walk_duration_seconds=8,
        canvas_width=800,
        canvas_height=200,
        ground_line_y=160,
    )

    try:
        module.build_animator_input(args)
    except FileNotFoundError as error:
        assert (
            "Run scripts/run-director-agent.py until it writes a validated .json file first."
            in str(error)
        )
    else:  # pragma: no cover - defensive failure branch
        raise AssertionError("Expected FileNotFoundError for missing Director output JSON")


def test_build_renderer_input_raises_helpful_error_for_missing_animator_json() -> None:
    module = _load_script_module(
        "scripts/run-renderer-agent.py",
        "run_renderer_agent_test_module",
    )
    args = argparse.Namespace(
        animator_output_path="tmp/animator-agent/missing-debug-director.json",
        job_id="debug-renderer",
        session_id="debug-session",
    )

    try:
        module.build_renderer_input(
            args,
            drawing_agent=object(),
            output_dir=Path("tmp/renderer-agent"),
        )
    except FileNotFoundError as error:
        assert (
            "Run scripts/run-animator-agent.py until it writes a validated .json file first."
            in str(error)
        )
    else:  # pragma: no cover - defensive failure branch
        raise AssertionError("Expected FileNotFoundError for missing Animator output JSON")


def test_resolve_director_output_path_auto_detects_matching_file(tmp_path: Path) -> None:
    module = _load_script_module(
        "scripts/run-renderer-agent.py",
        "run_renderer_agent_auto_detect_test_module",
    )
    animator_dir = tmp_path / "animator-agent"
    director_dir = tmp_path / "director-agent"
    animator_dir.mkdir()
    director_dir.mkdir()
    animator_output_path = animator_dir / "debug-story.json"
    animator_output_path.write_text("{}", encoding="utf-8")
    director_output_path = director_dir / "debug-story.json"
    director_output_path.write_text("{}", encoding="utf-8")

    resolved = module.resolve_director_output_path(
        animator_output_path=animator_output_path,
        director_output_argument=None,
    )

    assert resolved == director_output_path


def test_draw_missing_obstacle_svg_reuses_cached_svg(tmp_path: Path) -> None:
    module = _load_script_module(
        "scripts/run-renderer-agent.py",
        "run_renderer_agent_cached_obstacle_test_module",
    )
    generated_dir = tmp_path / "generated-obstacles"
    generated_dir.mkdir()
    (generated_dir / "wolf.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" id="obstacle-root" viewBox="0 0 120 150">'
        '<g id="obstacle-main"><rect x="10" y="20" width="80" height="100" />'
        '<g id="obstacle-animated-part"><rect x="40" y="10" width="10" height="20" />'
        '<animateTransform attributeName="transform" type="rotate" '
        'values="-3 45 20;3 45 20;-3 45 20" dur="2s" repeatCount="indefinite" />'
        "</g></g></svg>",
        encoding="utf-8",
    )

    svg = module.draw_missing_obstacle_svg(
        obstacle_type="wolf",
        job_id="debug-renderer",
        session_id="debug-session",
        drawing_agent=object(),
        output_dir=tmp_path,
    )

    assert 'id="obstacle-root"' in svg


def test_draw_background_svg_ignores_cached_svg_and_redraws(tmp_path: Path) -> None:
    module = _load_script_module(
        "scripts/run-renderer-agent.py",
        "run_renderer_agent_cached_background_test_module",
    )
    generated_dir = tmp_path / "generated-backgrounds"
    generated_dir.mkdir()
    (generated_dir / "act-0.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" id="background-root" viewBox="0 0 800 200">'
        '<g id="background-main"><rect width="800" height="200" fill="#aaccee" />'
        '<g id="background-animated-part"><rect width="800" height="40" fill="#ccddee">'
        '<animate attributeName="opacity" values="0.4;0.7;0.4" dur="3s" repeatCount="indefinite" />'
        "</rect></g></g></svg>",
        encoding="utf-8",
    )

    class _FakeDrawingAgent:
        def __init__(self) -> None:
            self.calls = 0

        def run(
            self,
            _input: object,
            validation_errors: list[str] | None = None,
        ) -> SimpleNamespace:
            self.calls += 1
            return SimpleNamespace(
                svg=(
                    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 200">'
                    '<g id="background-root"><g id="background-main">'
                    '<rect width="800" height="200" fill="#123456" />'
                    '<g id="background-animated-part"><rect width="800" height="40" fill="#abcdef">'
                    '<animate attributeName="opacity" values="0.4;0.7;0.4" dur="3s" '
                    'repeatCount="indefinite" /></rect></g></g></g></svg>'
                )
            )

        def get_last_prompt(self) -> str:
            return "background prompt"

    fake_agent = _FakeDrawingAgent()
    svg = module.draw_background_svg(
        act_index=0,
        background_drawing_prompt="draw a fresh background",
        job_id="debug-renderer",
        session_id="debug-session",
        drawing_agent=fake_agent,
        output_dir=tmp_path,
    )

    assert 'id="background-root"' in svg
    assert "#123456" in svg
    assert fake_agent.calls == 1
    assert "#123456" in (generated_dir / "act-0.svg").read_text(encoding="utf-8")


def test_resolve_background_svgs_reuses_cached_backgrounds(tmp_path: Path) -> None:
    module = _load_script_module(
        "scripts/run-renderer-agent.py",
        "run_renderer_agent_resolve_background_cache_test_module",
    )
    generated_dir = tmp_path / "generated-backgrounds"
    generated_dir.mkdir()
    (generated_dir / "gentle-rolling-hills.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" id="background-root" viewBox="0 0 800 200">'
        '<g id="background-main"><rect width="800" height="200" fill="#aaccee" />'
        '<g id="background-animated-part"><rect width="800" height="40" fill="#ccddee">'
        '<animate attributeName="opacity" values="0.4;0.7;0.4" dur="3s" repeatCount="indefinite" />'
        "</rect></g></g></svg>",
        encoding="utf-8",
    )

    class _FailIfCalledDrawingAgent:
        def run(
            self,
            _input: object,
            validation_errors: list[str] | None = None,
        ) -> SimpleNamespace:
            raise AssertionError(f"Background cache should skip drawing: {validation_errors}")

    clips = [
        ClipManifest(
            act_index=0,
            obstacle_type="obstacle-0",
            branch="approach",
            choice_index=None,
            duration_ms=8000,
            obstacle_x=400,
            keyframes=[
                Keyframe(
                    time_ms=0,
                    character_x=40,
                    character_y=160,
                    support_y=160,
                    is_grounded=True,
                    expression="calm",
                    action="floating",
                ),
                Keyframe(
                    time_ms=8000,
                    character_x=config.MAX_GROUNDED_APPROACH_CHARACTER_X,
                    character_y=160,
                    support_y=160,
                    is_grounded=True,
                    expression="curious",
                    action="stopping",
                ),
            ],
        )
    ]
    director_output = DirectorOutput(
        title="Debug story",
        description="A debug story for local runner tests.",
        acts=[
            Act(
                act_index=0,
                obstacle_type="obstacle-0",
                approach_description="Linai meets obstacle 0.",
                drawing_prompt=_BG_PROMPT,
                background_drawing_prompt=_BG_PROMPT,
                choices=[
                    Choice(label="Try kindly", is_winning=True, outcome_description="It works."),
                    Choice(label="Rush in", is_winning=False, outcome_description="It fails."),
                ],
            )
        ],
    )

    resolved = module.resolve_background_svgs(
        clips=clips,
        director_output=director_output,
        job_id="debug-renderer",
        session_id="debug-session",
        drawing_agent=_FailIfCalledDrawingAgent(),
        output_dir=tmp_path,
    )

    assert resolved[0].background_svg is not None
    assert "#aaccee" in resolved[0].background_svg


def test_run_animator_debug_session_retries_only_failed_act_and_writes_output(
    tmp_path: Path,
) -> None:
    module = _load_script_module(
        "scripts/run-animator-agent.py",
        "run_animator_agent_retry_test_module",
    )
    animator_input = AnimatorInput(
        job_id="debug-animator",
        session_id="debug-session",
        acts=_make_director_output(act_count=2).acts,
        walk_duration_seconds=8,
        canvas_width=800,
        canvas_height=200,
        ground_line_y=160,
        handoff_character_x=config.HANDOFF_CHARACTER_X,
    )
    fake_agent = _FakeAnimatorAgent(
        {
            0: [
                _valid_animator_output_for_act(
                    act_index=0,
                    obstacle_type="obstacle-0",
                    choice_count=2,
                )
            ],
            1: [
                RuntimeError("Read timeout on endpoint URL"),
                _valid_animator_output_for_act(
                    act_index=1,
                    obstacle_type="obstacle-1",
                    choice_count=2,
                    requires_handoff_in=True,
                ),
            ],
        }
    )

    exit_code = module.run_animator_debug_session(
        animator_input=animator_input,
        output_dir=tmp_path,
        output_prefix="debug-director",
        validation_errors=[],
        agent=fake_agent,
    )

    assert exit_code == 0
    assert [call["act_index"] for call in fake_agent.calls].count(0) == 1
    assert [call["act_index"] for call in fake_agent.calls].count(1) == 2
    assert (tmp_path / "debug-director.json").exists()
    assert (tmp_path / "debug-director.act-1.attempt-1.json").exists()
    assert (tmp_path / "debug-director.prompt.txt").exists()
