# Visual Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove La Linea references, add per-agent model config, Director-driven drawing prompts, and background SVGs.

**Architecture:** The Director agent becomes the creative brain for obstacle and background visuals by writing rich drawing prompts. The Drawing agent executes those prompts for both obstacles and backgrounds. Each agent gets its own configurable Bedrock model ID. The visible ground line is removed from the SVG template.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest, ruff

**Spec:** `docs/superpowers/specs/visual-overhaul-design.md`

---

## File Map

### Modified files

| File | Responsibility |
|------|---------------|
| `pipeline/config.py` | Replace single model ID with 4 per-agent model IDs + drawing temperature |
| `pipeline/models/director.py` | Add `drawing_prompt` and `background_drawing_prompt` to `Act` |
| `pipeline/models/drawing.py` | Add `drawing_prompt` and `drawing_type` to `DrawingInput` |
| `pipeline/models/animator.py` | Add `background_svg` to `ClipManifest` |
| `pipeline/agents/director/agent.py` | Use `BEDROCK_MODEL_ID_DIRECTOR` |
| `pipeline/agents/director/prompt.txt` | Add drawing prompt instructions, background prompt instructions, remove La Linea |
| `pipeline/agents/animator/agent.py` | Use `BEDROCK_MODEL_ID_ANIMATOR` |
| `pipeline/agents/animator/prompt.txt` | Replace "ground line" with "invisible floor" |
| `pipeline/agents/drawing/agent.py` | Use Director's prompt, handle obstacle vs background, use `BEDROCK_MODEL_ID_DRAWING` |
| `pipeline/agents/renderer/agent.py` | Use `BEDROCK_MODEL_ID_RENDERER` |
| `pipeline/agents/renderer/prompt.txt` | Add background layering, remove visible ground line |
| `pipeline/validators/script_validator.py` | Validate `drawing_prompt` and `background_drawing_prompt` |
| `pipeline/lambdas/orchestrator/pipeline_orchestrator.py` | Call DrawingAgent for backgrounds, inject `background_svg`, pass `drawing_prompt` |
| `frontend/public/linai-template.svg` | Remove visible `<line>` element |
| `REQUIREMENTS.md` | Remove La Linea, add background concept, update model constraint |
| `DESIGN.md` | Update all contracts, add background SVG spec |
| `STANDARDS.md` | Update config example |
| `PHASES.md` | Update Phase 0/5 descriptions |
| `README.md` | Remove La Linea, update project description |
| `knowledge-base/characters/linai/linai-character-overview.md` | Remove La Linea style references |
| `knowledge-base/shared/the-world-is-the-line.md` | Rewrite — world no longer defined by a line |
| `knowledge-base/shared/tone-all-ages.md` | Remove La Linea references |

### Modified test files

| File | Responsibility |
|------|---------------|
| `tests/unit/test_models.py` | New fields on `Act`, `DrawingInput`, `ClipManifest` |
| `tests/unit/test_script_validator.py` | Validate `drawing_prompt` and `background_drawing_prompt` rules |
| `tests/unit/test_drawing_agent.py` | New `DrawingInput` shape, obstacle vs background handling |
| `tests/unit/test_orchestrator_pipeline.py` | Background drawing calls, `background_svg` injection |
| `tests/fixtures/valid_episode.json` | Add new fields to fixture |

### Deleted files

| File | Reason |
|------|--------|
| `pipeline/agents/drawing/prompt.txt` | Replaced by Director-provided prompts |

---

## Task 1: Per-agent model configuration in config.py

**Files:**
- Modify: `pipeline/config.py`

- [ ] **Step 1: Replace single BEDROCK_MODEL_ID with per-agent values**

In `pipeline/config.py`, replace the entire `BEDROCK_MODEL_ID` block (lines 28-37) with:

```python
# --- Per-agent Bedrock model IDs ---
# Drawing agent uses Opus for highest SVG quality.
# All other agents use Sonnet for cost efficiency.
# Each agent reads its own env var; warn on fallback per STANDARDS.md §1.

_BEDROCK_MODEL_ID_DIRECTOR_DEFAULT = "eu.anthropic.claude-sonnet-4-6"
_director_model_from_env = os.getenv("BEDROCK_MODEL_ID_DIRECTOR")
if _director_model_from_env is None:
    print(
        "WARN [config] BEDROCK_MODEL_ID_DIRECTOR not set; "
        f"using default: {_BEDROCK_MODEL_ID_DIRECTOR_DEFAULT}",
        file=sys.stderr,
    )
BEDROCK_MODEL_ID_DIRECTOR: str = (
    _director_model_from_env or _BEDROCK_MODEL_ID_DIRECTOR_DEFAULT
)

_BEDROCK_MODEL_ID_ANIMATOR_DEFAULT = "eu.anthropic.claude-sonnet-4-6"
_animator_model_from_env = os.getenv("BEDROCK_MODEL_ID_ANIMATOR")
if _animator_model_from_env is None:
    print(
        "WARN [config] BEDROCK_MODEL_ID_ANIMATOR not set; "
        f"using default: {_BEDROCK_MODEL_ID_ANIMATOR_DEFAULT}",
        file=sys.stderr,
    )
BEDROCK_MODEL_ID_ANIMATOR: str = (
    _animator_model_from_env or _BEDROCK_MODEL_ID_ANIMATOR_DEFAULT
)

_BEDROCK_MODEL_ID_DRAWING_DEFAULT = "eu.anthropic.claude-opus-4-6-v1"
_drawing_model_from_env = os.getenv("BEDROCK_MODEL_ID_DRAWING")
if _drawing_model_from_env is None:
    print(
        "WARN [config] BEDROCK_MODEL_ID_DRAWING not set; "
        f"using default: {_BEDROCK_MODEL_ID_DRAWING_DEFAULT}",
        file=sys.stderr,
    )
BEDROCK_MODEL_ID_DRAWING: str = (
    _drawing_model_from_env or _BEDROCK_MODEL_ID_DRAWING_DEFAULT
)

_BEDROCK_MODEL_ID_RENDERER_DEFAULT = "eu.anthropic.claude-sonnet-4-6"
_renderer_model_from_env = os.getenv("BEDROCK_MODEL_ID_RENDERER")
if _renderer_model_from_env is None:
    print(
        "WARN [config] BEDROCK_MODEL_ID_RENDERER not set; "
        f"using default: {_BEDROCK_MODEL_ID_RENDERER_DEFAULT}",
        file=sys.stderr,
    )
BEDROCK_MODEL_ID_RENDERER: str = (
    _renderer_model_from_env or _BEDROCK_MODEL_ID_RENDERER_DEFAULT
)

DRAWING_TEMPERATURE: float = 0.5  # Lower temperature for more consistent SVG output
```

Also remove the old `BEDROCK_MODEL_ID` variable and its comment block entirely.

- [ ] **Step 2: Update GROUND_LINE_Y comment**

Change the comment on `GROUND_LINE_Y` from:

```python
GROUND_LINE_Y: int = 160               # y-coordinate of the support line Linai hovers against
```

to:

```python
GROUND_LINE_Y: int = 160               # Invisible floor coordinate — not rendered as a visible line
```

- [ ] **Step 3: Run ruff**

Run: `ruff check pipeline/config.py && ruff format pipeline/config.py`
Expected: clean

---

## Task 2: Wire per-agent model IDs into all four agents

**Files:**
- Modify: `pipeline/agents/director/agent.py`
- Modify: `pipeline/agents/animator/agent.py`
- Modify: `pipeline/agents/drawing/agent.py`
- Modify: `pipeline/agents/renderer/agent.py`

- [ ] **Step 1: Update DirectorAgent default model_id**

In `pipeline/agents/director/agent.py` line 50, change:

```python
        model_id: str = config.BEDROCK_MODEL_ID,
```

to:

```python
        model_id: str = config.BEDROCK_MODEL_ID_DIRECTOR,
```

- [ ] **Step 2: Update AnimatorAgent default model_id**

In `pipeline/agents/animator/agent.py`, find the `__init__` signature line with `model_id: str = config.BEDROCK_MODEL_ID` and change to:

```python
        model_id: str = config.BEDROCK_MODEL_ID_ANIMATOR,
```

- [ ] **Step 3: Update DrawingAgent default model_id and temperature**

In `pipeline/agents/drawing/agent.py` line 30, change:

```python
        model_id: str = config.BEDROCK_MODEL_ID,
```

to:

```python
        model_id: str = config.BEDROCK_MODEL_ID_DRAWING,
```

Also in the `_invoke_model` method, change the hardcoded temperature:

```python
                "temperature": 0.5,
```

to:

```python
                "temperature": config.DRAWING_TEMPERATURE,
```

- [ ] **Step 4: Update RendererAgent default model_id**

In `pipeline/agents/renderer/agent.py`, find the `__init__` signature line with `model_id: str = config.BEDROCK_MODEL_ID` and change to:

```python
        model_id: str = config.BEDROCK_MODEL_ID_RENDERER,
```

- [ ] **Step 5: Fix any remaining references to old BEDROCK_MODEL_ID**

Run: `ruff check pipeline/agents/ && ruff format pipeline/agents/`

Then search for any remaining references:

```bash
grep -r "config.BEDROCK_MODEL_ID[^_]" pipeline/
```

Fix any hits. The orchestrator (`pipeline/lambdas/orchestrator/pipeline_orchestrator.py`) may pass the model ID when constructing agents — update those too.

- [ ] **Step 6: Run tests**

Run: `pytest tests/unit/ -v -x`
Expected: all pass (tests use mock clients, not real model IDs)

- [ ] **Step 7: Commit**

```bash
git add pipeline/config.py pipeline/agents/
git commit -m "feat(config): replace single BEDROCK_MODEL_ID with per-agent model IDs

Each agent now reads its own config value and env var override.
Drawing uses Opus 4.6; Director, Animator, Renderer use Sonnet 4.6.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 3: Add drawing_prompt and background_drawing_prompt to Director models

**Files:**
- Modify: `pipeline/models/director.py`
- Modify: `tests/unit/test_models.py`

- [ ] **Step 1: Write failing tests for new Act fields**

Add to `tests/unit/test_models.py`:

```python
def test_act_drawing_prompt_defaults_to_none():
    """drawing_prompt is optional and defaults to None for library obstacles."""
    act = Act(
        act_index=0,
        obstacle_type="wall",
        approach_description="Linai floats up to a wall.",
        choices=[
            Choice(label="Climb", is_winning=True, outcome_description="She climbs over."),
            Choice(label="Kick", is_winning=False, outcome_description="It doesn't budge."),
        ],
        background_drawing_prompt="Draw a forest background with tall trees.",
    )
    assert act.drawing_prompt is None


def test_act_drawing_prompt_accepts_string():
    """drawing_prompt accepts a rich prompt string for non-library obstacles."""
    prompt = "Draw a detailed knight with plate armor and a plumed helmet."
    act = Act(
        act_index=0,
        obstacle_type="knight",
        approach_description="A knight blocks the path.",
        choices=[
            Choice(label="Fight", is_winning=True, outcome_description="She wins."),
            Choice(label="Run", is_winning=False, outcome_description="She trips."),
        ],
        drawing_prompt=prompt,
        background_drawing_prompt="Draw a castle courtyard background.",
    )
    assert act.drawing_prompt == prompt


def test_act_background_drawing_prompt_required():
    """background_drawing_prompt is required on every act."""
    import pytest
    from pydantic import ValidationError

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_models.py -v -k "drawing_prompt or background_drawing_prompt"`
Expected: FAIL — `Act` doesn't have these fields yet

- [ ] **Step 3: Add fields to Act model**

In `pipeline/models/director.py`, update the `Act` class:

```python
class Act(BaseModel):
    """One obstacle act in an episode script."""

    model_config = ConfigDict(extra="forbid")

    act_index: int
    obstacle_type: ObstacleSlug
    approach_description: str
    choices: list[Choice]
    drawing_prompt: str | None = None
    background_drawing_prompt: str
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_models.py -v -k "drawing_prompt or background_drawing_prompt"`
Expected: PASS

- [ ] **Step 5: Fix any other test failures from the new required field**

Run: `pytest tests/unit/ -v -x`

Any test that constructs an `Act` without `background_drawing_prompt` will now fail. Fix each by adding the field. Common locations:
- `tests/unit/test_script_validator.py` — fixture helpers
- `tests/unit/test_models.py` — existing Act tests
- `tests/unit/test_animator_agent.py` — Act construction
- `tests/unit/test_orchestrator_pipeline.py` — Act construction
- `tests/fixtures/valid_episode.json` — add `background_drawing_prompt` to each act

For each, add `background_drawing_prompt="Draw a simple background."` (or appropriate value).

- [ ] **Step 6: Run ruff and full tests**

Run: `ruff check pipeline/models/ tests/ && ruff format pipeline/models/ tests/ && pytest tests/unit/ -v`
Expected: all clean, all pass

- [ ] **Step 7: Commit**

```bash
git add pipeline/models/director.py tests/
git commit -m "feat(models): add drawing_prompt and background_drawing_prompt to Act

drawing_prompt is optional (None for library obstacles).
background_drawing_prompt is required on every act.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 4: Add drawing_prompt and drawing_type to DrawingInput

**Files:**
- Modify: `pipeline/models/drawing.py`
- Modify: `tests/unit/test_models.py`

- [ ] **Step 1: Write failing tests for new DrawingInput fields**

Add to `tests/unit/test_models.py`:

```python
def test_drawing_input_requires_drawing_prompt():
    """DrawingInput now requires a drawing_prompt string."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DrawingInput(
            job_id="job-1",
            session_id="sess-1",
            obstacle_type="knight",
            # drawing_prompt intentionally omitted
        )


def test_drawing_input_obstacle_type_default():
    """DrawingInput drawing_type defaults to 'obstacle'."""
    di = DrawingInput(
        job_id="job-1",
        session_id="sess-1",
        obstacle_type="knight",
        drawing_prompt="Draw a knight.",
    )
    assert di.drawing_type == "obstacle"


def test_drawing_input_background_type():
    """DrawingInput accepts drawing_type='background'."""
    di = DrawingInput(
        job_id="job-1",
        session_id="sess-1",
        obstacle_type="forest-bg",
        drawing_prompt="Draw a forest background.",
        drawing_type="background",
    )
    assert di.drawing_type == "background"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_models.py -v -k "drawing_input"`
Expected: FAIL

- [ ] **Step 3: Update DrawingInput model**

In `pipeline/models/drawing.py`:

```python
"""Drawing-stage models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from pipeline.models.shared import ObstacleSlug


class DrawingInput(BaseModel):
    """Full input package handed to the Drawing agent."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    session_id: str
    obstacle_type: ObstacleSlug
    drawing_prompt: str
    drawing_type: Literal["obstacle", "background"] = "obstacle"


class DrawingOutput(BaseModel):
    """Standalone SVG returned by the Drawing agent."""

    model_config = ConfigDict(extra="forbid")

    svg: str
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_models.py -v -k "drawing_input"`
Expected: PASS

- [ ] **Step 5: Fix any other test failures from the new required field**

Run: `pytest tests/unit/ -v -x`

Any test constructing `DrawingInput` without `drawing_prompt` will fail. Fix each by adding the field. Key locations:
- `tests/unit/test_drawing_agent.py` — helper functions that build `DrawingInput`
- `tests/unit/test_orchestrator_pipeline.py` — DrawingInput construction

- [ ] **Step 6: Run ruff and full tests**

Run: `ruff check pipeline/models/ tests/ && ruff format pipeline/models/ tests/ && pytest tests/unit/ -v`
Expected: all clean, all pass

- [ ] **Step 7: Commit**

```bash
git add pipeline/models/drawing.py tests/
git commit -m "feat(models): add drawing_prompt and drawing_type to DrawingInput

drawing_prompt is now required (comes from Director).
drawing_type discriminates obstacle vs background SVG generation.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 5: Add background_svg to ClipManifest

**Files:**
- Modify: `pipeline/models/animator.py`
- Modify: `tests/unit/test_models.py`

- [ ] **Step 1: Write failing test**

Add to `tests/unit/test_models.py`:

```python
def test_clip_manifest_background_svg_defaults_to_none():
    """ClipManifest.background_svg is optional and defaults to None."""
    clip = ClipManifest(
        act_index=0,
        obstacle_type="wall",
        branch="approach",
        choice_index=None,
        duration_ms=8000,
        keyframes=[
            Keyframe(
                time_ms=0, character_x=40, character_y=160, support_y=160,
                is_grounded=True, expression="neutral", action="walking",
            ),
            Keyframe(
                time_ms=8000, character_x=320, character_y=160, support_y=160,
                is_grounded=True, expression="surprised", action="stopping",
            ),
        ],
        obstacle_x=400,
    )
    assert clip.background_svg is None


def test_clip_manifest_background_svg_accepts_string():
    """ClipManifest.background_svg accepts an SVG string."""
    bg = '<svg viewBox="0 0 800 200"><rect fill="#336"/></svg>'
    clip = ClipManifest(
        act_index=0,
        obstacle_type="wall",
        branch="approach",
        choice_index=None,
        duration_ms=8000,
        keyframes=[
            Keyframe(
                time_ms=0, character_x=40, character_y=160, support_y=160,
                is_grounded=True, expression="neutral", action="walking",
            ),
            Keyframe(
                time_ms=8000, character_x=320, character_y=160, support_y=160,
                is_grounded=True, expression="surprised", action="stopping",
            ),
        ],
        obstacle_x=400,
        background_svg=bg,
    )
    assert clip.background_svg == bg
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_models.py -v -k "background_svg"`
Expected: FAIL — `ClipManifest` doesn't have `background_svg` yet

- [ ] **Step 3: Add background_svg to ClipManifest**

In `pipeline/models/animator.py`, add after the `obstacle_svg_override` field:

```python
    background_svg: str | None = None  # Full-canvas background SVG, populated by orchestrator
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_models.py -v -k "background_svg" && pytest tests/unit/ -v -x`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add pipeline/models/animator.py tests/unit/test_models.py
git commit -m "feat(models): add background_svg to ClipManifest

Orchestrator populates this field before passing clips to the Renderer.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 6: Script validator — validate drawing_prompt and background_drawing_prompt

**Files:**
- Modify: `pipeline/validators/script_validator.py`
- Modify: `tests/unit/test_script_validator.py`

- [ ] **Step 1: Write failing tests for new validation rules**

Add to `tests/unit/test_script_validator.py`:

```python
def test_validate_script_fails_when_drawing_prompt_missing_for_non_library_obstacle():
    """Non-library obstacles must have a drawing_prompt."""
    script = _make_valid_script()
    script.acts[0].obstacle_type = "dragon"
    script.acts[0].drawing_prompt = None
    result = validate_script(script, preferred_obstacle_library_names=["wall", "hole"])
    assert not result.is_valid
    assert any("drawing_prompt" in e for e in result.errors)


def test_validate_script_fails_when_drawing_prompt_too_short():
    """drawing_prompt must be at least 50 characters when present."""
    script = _make_valid_script()
    script.acts[0].obstacle_type = "dragon"
    script.acts[0].drawing_prompt = "Draw a dragon."
    result = validate_script(script, preferred_obstacle_library_names=["wall", "hole"])
    assert not result.is_valid
    assert any("50 characters" in e for e in result.errors)


def test_validate_script_passes_when_drawing_prompt_null_for_library_obstacle():
    """Library obstacles may have drawing_prompt=None."""
    script = _make_valid_script()
    script.acts[0].obstacle_type = "wall"
    script.acts[0].drawing_prompt = None
    result = validate_script(script, preferred_obstacle_library_names=["wall", "hole"])
    assert result.is_valid


def test_validate_script_fails_when_background_drawing_prompt_too_short():
    """background_drawing_prompt must be at least 50 characters."""
    script = _make_valid_script()
    script.acts[0].background_drawing_prompt = "Short."
    result = validate_script(script, preferred_obstacle_library_names=["wall"])
    assert not result.is_valid
    assert any("background_drawing_prompt" in e for e in result.errors)


def test_validate_script_passes_with_valid_drawing_and_background_prompts():
    """Valid prompts pass validation."""
    script = _make_valid_script()
    script.acts[0].obstacle_type = "dragon"
    script.acts[0].drawing_prompt = "Draw a detailed dragon with scales, wings, and a long tail. " * 2
    script.acts[0].background_drawing_prompt = "Draw a mountain landscape with snow-capped peaks and a river. " * 2
    result = validate_script(script, preferred_obstacle_library_names=["wall"])
    assert result.is_valid
```

Note: These tests assume `validate_script` gains a `preferred_obstacle_library_names` parameter. The helper `_make_valid_script()` must return a `DirectorOutput` with valid `background_drawing_prompt` values (at least 50 chars each). Update the helper accordingly.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_script_validator.py -v -k "drawing_prompt or background_drawing_prompt"`
Expected: FAIL — `validate_script` doesn't accept `preferred_obstacle_library_names` yet

- [ ] **Step 3: Update validate_script signature and add rules**

In `pipeline/validators/script_validator.py`, update the function signature:

```python
def validate_script(
    script: DirectorOutput,
    *,
    preferred_obstacle_library_names: list[str] | None = None,
) -> ValidationResult:
```

Add these rules inside the `for act in script.acts:` loop, after the existing checks:

```python
        # Rule: non-library obstacles must provide a drawing_prompt.
        _library_names = set(preferred_obstacle_library_names or [])
        is_library_obstacle = act.obstacle_type in _library_names
        if not is_library_obstacle and act.drawing_prompt is None:
            errors.append(
                f"act {act.act_index} obstacle_type '{act.obstacle_type}' is not in the "
                "pre-authored library; drawing_prompt is required"
            )

        # Rule: drawing_prompt, when present, must be at least 50 characters.
        if act.drawing_prompt is not None and len(act.drawing_prompt) < 50:
            errors.append(
                f"act {act.act_index} drawing_prompt must be at least 50 characters; "
                f"got {len(act.drawing_prompt)}"
            )

        # Rule: background_drawing_prompt must be at least 50 characters.
        if len(act.background_drawing_prompt) < 50:
            errors.append(
                f"act {act.act_index} background_drawing_prompt must be at least "
                f"50 characters; got {len(act.background_drawing_prompt)}"
            )
```

Move `_library_names` computation outside the loop for efficiency:

```python
    _library_names = set(preferred_obstacle_library_names or [])
```

- [ ] **Step 4: Update _make_valid_script helper and existing tests**

Update the test helper to include valid `background_drawing_prompt` values on all acts. Every existing call to `validate_script(script)` must be updated to also pass `preferred_obstacle_library_names` if testing library-aware rules, or left as-is (the param defaults to `None`, which means no library check).

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_script_validator.py -v`
Expected: all PASS

- [ ] **Step 6: Run ruff and full suite**

Run: `ruff check pipeline/validators/ tests/ && ruff format pipeline/validators/ tests/ && pytest tests/unit/ -v`
Expected: all clean, all pass

- [ ] **Step 7: Commit**

```bash
git add pipeline/validators/script_validator.py tests/unit/test_script_validator.py
git commit -m "feat(validator): validate drawing_prompt and background_drawing_prompt

Non-library obstacles require drawing_prompt >= 50 chars.
Every act requires background_drawing_prompt >= 50 chars.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 7: Update Drawing agent to use Director's prompt and handle background type

**Files:**
- Modify: `pipeline/agents/drawing/agent.py`
- Delete: `pipeline/agents/drawing/prompt.txt`
- Modify: `tests/unit/test_drawing_agent.py`

- [ ] **Step 1: Write failing tests for new DrawingAgent behavior**

Add to `tests/unit/test_drawing_agent.py`:

```python
def test_drawing_agent_uses_drawing_prompt_from_input():
    """Drawing agent sends the Director's drawing_prompt as the user message."""
    svg_response = '<svg viewBox="0 0 120 150"><g id="obstacle-root"><g id="obstacle-main"><g id="obstacle-animated-part"/></g></g></svg>'
    client = _FakeModelClient(response_text=svg_response)
    agent = DrawingAgent(model_client=client)
    director_prompt = "Draw a detailed knight with plate armor and a plumed helmet. " * 3
    inp = DrawingInput(
        job_id="job-1",
        session_id="sess-1",
        obstacle_type="knight",
        drawing_prompt=director_prompt,
        drawing_type="obstacle",
    )
    agent.run(inp)
    sent_message = client.calls[0]["messages"][0]["content"][0]["text"]
    assert director_prompt in sent_message


def test_drawing_agent_background_type_uses_background_system_prompt():
    """Background drawing uses a different system prompt mentioning background IDs."""
    svg_response = '<svg viewBox="0 0 800 200"><g id="background-root"><g id="background-main"><g id="background-animated-part"/></g></g></svg>'
    client = _FakeModelClient(response_text=svg_response)
    agent = DrawingAgent(model_client=client)
    inp = DrawingInput(
        job_id="job-1",
        session_id="sess-1",
        obstacle_type="forest-bg",
        drawing_prompt="Draw a dark enchanted forest background with fireflies. " * 3,
        drawing_type="background",
    )
    agent.run(inp)
    system_text = client.calls[0]["system"][0]["text"]
    assert "background-root" in system_text
    assert "background-main" in system_text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_drawing_agent.py -v -k "drawing_prompt or background_type"`
Expected: FAIL

- [ ] **Step 3: Rewrite DrawingAgent._build_prompt and system prompt logic**

In `pipeline/agents/drawing/agent.py`:

1. Remove the `prompt_path` parameter from `__init__` and all template loading logic.
2. Replace `_build_prompt` to use `input.drawing_prompt` directly:

```python
    _OBSTACLE_SYSTEM_PROMPT = (
        "You are an expert SVG illustrator. When asked to draw something:\n"
        "- Output only raw SVG markup, no explanation, no markdown fences\n"
        "- Use hardcoded hex colors for physical scenes\n"
        "- Layer overlapping opaque shapes to create depth\n"
        "- Keep proportions plausible but artistic, not strictly to scale\n"
        "- Use <path>, <ellipse>, <polygon> for organic forms\n"
        "- Include fine details: highlights, shadows via darker fills, texture via repeated shapes\n"
        "- Fill the canvas richly — avoid sparse compositions\n"
        "- Your response must be only <svg> and nothing else\n"
        "- All coordinates must stay within the viewBox bounds"
    )

    _BACKGROUND_SYSTEM_PROMPT = (
        "You are an expert SVG illustrator specializing in full-canvas backgrounds.\n"
        "- Output only raw SVG markup, no explanation, no markdown fences\n"
        "- Use hardcoded hex colors\n"
        "- Layer overlapping opaque shapes to create depth and atmosphere\n"
        "- Fill the entire canvas — no empty space\n"
        "- Animations must only use opacity and fill changes — no translate, rotate, or scale\n"
        "- Use <animate attributeName='opacity'> and <animate attributeName='fill'> only\n"
        "- Your response must be only <svg> and nothing else\n"
        "- All coordinates must stay within the viewBox bounds"
    )
```

Update `_build_prompt`:

```python
    def _build_prompt(
        self,
        input: DrawingInput,
        validation_errors: list[str] | None,
    ) -> str:
        prompt = input.drawing_prompt

        if validation_errors:
            error_block = "\n".join(f"- {error}" for error in validation_errors)
            prompt += (
                "\n\nPrevious attempt failed deterministic validation. "
                "You MUST fix these exact errors:\n"
                f"{error_block}\n"
            )
        return prompt
```

Update `_invoke_model` to select the system prompt based on drawing type (pass `drawing_type` through or store on instance):

```python
    def _get_system_prompt(self, drawing_type: str) -> str:
        if drawing_type == "background":
            return self._BACKGROUND_SYSTEM_PROMPT
        return self._OBSTACLE_SYSTEM_PROMPT
```

And in `_invoke_model`, use `self._get_system_prompt(drawing_type)` for the system message.

The `run` method needs to thread `drawing_type` through:

```python
    def run(self, input: DrawingInput, validation_errors: list[str] | None = None) -> DrawingOutput:
        prompt = self.build_prompt(input=input, validation_errors=validation_errors)
        self._last_prompt = prompt
        response_text, usage = self._invoke_model(
            prompt=prompt, job_id=input.job_id, drawing_type=input.drawing_type,
        )
        # ... rest unchanged
```

- [ ] **Step 4: Delete prompt.txt**

```bash
rm pipeline/agents/drawing/prompt.txt
```

- [ ] **Step 5: Fix remaining DrawingAgent tests**

Update all existing tests that construct `DrawingInput` to include `drawing_prompt`. Update any test that checks prompt template loading behavior.

- [ ] **Step 6: Run tests**

Run: `pytest tests/unit/test_drawing_agent.py -v && pytest tests/unit/ -v -x`
Expected: all PASS

- [ ] **Step 7: Run ruff**

Run: `ruff check pipeline/agents/drawing/ tests/ && ruff format pipeline/agents/drawing/ tests/`
Expected: clean

- [ ] **Step 8: Commit**

```bash
git add pipeline/agents/drawing/ tests/unit/test_drawing_agent.py
git commit -m "feat(drawing): use Director's drawing_prompt, support background type

Drawing agent no longer uses a prompt template file.
System prompt varies by drawing_type (obstacle vs background).

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 8: Update orchestrator — background drawing + injection

**Files:**
- Modify: `pipeline/lambdas/orchestrator/pipeline_orchestrator.py`
- Modify: `tests/unit/test_orchestrator_pipeline.py`

- [ ] **Step 1: Write failing tests for background drawing flow**

Add to `tests/unit/test_orchestrator_pipeline.py`:

```python
def test_orchestrator_calls_drawing_agent_for_background():
    """Orchestrator calls DrawingAgent with drawing_type='background' for each act."""
    # Set up a mock DrawingAgent that records calls
    # Build a DirectorOutput with background_drawing_prompt on each act
    # Run the orchestrator's obstacle/background resolution step
    # Assert DrawingAgent was called with drawing_type="background"
    # Assert background_svg is injected into each ClipManifest
    ...


def test_orchestrator_passes_drawing_prompt_to_drawing_agent():
    """Orchestrator passes Director's drawing_prompt to DrawingAgent for non-library obstacles."""
    # Build DirectorOutput with drawing_prompt on a non-library act
    # Run resolution
    # Assert DrawingInput.drawing_prompt matches Director's drawing_prompt
    ...
```

(Fill in with the project's existing mock patterns — `_FakeModelClient`, mock orchestrator setup.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_orchestrator_pipeline.py -v -k "background or drawing_prompt"`
Expected: FAIL

- [ ] **Step 3: Update _resolve_obstacle_svgs to also resolve backgrounds**

In `pipeline/lambdas/orchestrator/pipeline_orchestrator.py`:

1. Add background ID constants near the existing obstacle ID constants:

```python
_BACKGROUND_REQUIRED_IDS: set[str] = {"background-root", "background-main", "background-animated-part"}
_BACKGROUND_ANIMATED_IDS: set[str] = {"background-animated-part"}
```

2. Add a new method `_resolve_background_svgs` that:
   - Iterates over each act in `director_output.acts`
   - Calls `DrawingAgent.run()` with `DrawingInput(drawing_type="background", drawing_prompt=act.background_drawing_prompt, ...)`
   - Validates result with `validate_and_sanitise_svg(svg, required_ids=_BACKGROUND_REQUIRED_IDS, animated_ids=_BACKGROUND_ANIMATED_IDS)`
   - Retries on validation failure (same pattern as obstacle drawing)
   - Returns a dict mapping `act_index` to background SVG string

3. Update the existing obstacle drawing call to pass `drawing_prompt` from the Director:

```python
DrawingInput(
    job_id=job_id,
    session_id=session_id,
    obstacle_type=obstacle_type,
    drawing_prompt=act.drawing_prompt,  # from Director
    drawing_type="obstacle",
)
```

4. After both obstacle and background SVGs are resolved, inject `background_svg` into each clip:

```python
for clip in animator_output.clips:
    clip.obstacle_svg_override = obstacle_svgs[clip.obstacle_type]
    clip.background_svg = background_svgs[clip.act_index]
```

- [ ] **Step 4: Update validate_script call to pass preferred_obstacle_library_names**

Find where the orchestrator calls `validate_script(director_output)` and update to:

```python
validate_script(
    director_output,
    preferred_obstacle_library_names=preferred_obstacle_library_names,
)
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/unit/test_orchestrator_pipeline.py -v && pytest tests/unit/ -v -x`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add pipeline/lambdas/orchestrator/ tests/unit/test_orchestrator_pipeline.py
git commit -m "feat(orchestrator): resolve background SVGs and pass drawing_prompt

Orchestrator calls DrawingAgent for backgrounds per act.
Director's drawing_prompt is passed through for non-library obstacles.
background_svg injected into each ClipManifest before Renderer runs.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 9: Update Director prompt with drawing prompt instructions

**Files:**
- Modify: `pipeline/agents/director/prompt.txt`

- [ ] **Step 1: Update the Director prompt**

Rewrite `pipeline/agents/director/prompt.txt` to:

1. Remove any La Linea references (none currently, but verify)
2. Add `drawing_prompt` and `background_drawing_prompt` to the output JSON schema
3. Add instructions explaining how to write rich drawing prompts
4. Add 2 few-shot examples (knight, horse)
5. Add instructions for background drawing prompts
6. Update the output JSON schema section to include the new fields

The output JSON schema section should become:

```
Output JSON schema:
{
  "title": "string, max 60 chars",
  "description": "string, max 120 chars",
  "acts": [
    {
      "act_index": "integer, starts at 0 and increments by 1",
      "obstacle_type": "lowercase slug, e.g. wall, bird, dragon, hot-air-balloon",
      "approach_description": "string",
      "choices": [
        {
          "label": "string, max 40 chars",
          "is_winning": "boolean",
          "outcome_description": "string"
        }
      ],
      "drawing_prompt": "string or null — null when obstacle_type matches a bundled name",
      "background_drawing_prompt": "string — always required, rich SVG drawing prompt for background"
    }
  ]
}
```

Add a new section before the output schema:

```
Drawing prompt rules:
- If the obstacle_type matches a bundled name from the list above, set drawing_prompt to null.
- Otherwise, write a rich, detailed SVG drawing prompt for the obstacle.
- The drawing_prompt must include:
  1. Visual description — what it looks like, physical details, pose/stance
  2. Layering order — back-to-front shape order for depth
  3. ID assignments:
     - obstacle-root on the root <svg> element
     - obstacle-main on the <g> containing the full body
     - obstacle-animated-part on a naturally self-contained element for idle animation
  4. Animation direction — which part animates, what type, and why that part was chosen
  5. Technical requirements: valid XML, inline only, no external images/scripts/foreignObject

Example drawing_prompt for a knight:
"Draw a detailed, high-quality SVG illustration of a medieval knight in a heroic standing pose. The knight should have plate armor, a plumed helmet, a shield, and a raised sword. Use rich layering of shapes (back-to-front: cape, legs, torso, arms, weapon, pauldrons, helmet) to create depth and visual detail. Technical requirements: Output one complete <svg>...</svg> document with a viewBox attribute. Valid XML, inline only — no external images, scripts, or foreignObject. Assign these IDs: obstacle-root on the root <svg>, obstacle-main on the <g> containing the full knight, obstacle-animated-part on the plume (a small <g> of feather shapes on the helmet), animated with <animateTransform type='rotate'> to gently sway. The plume is chosen because it is self-contained and sits on top without disrupting z-ordering. Do not return markdown fences or text outside the SVG."

Example drawing_prompt for a horse:
"Draw a detailed, high-quality SVG illustration of a medieval horse. The horse should have a muscular build, flowing mane, a long tail, defined legs with hooves, and a bridle with reins. Use rich layering of shapes (back-to-front: tail, body, legs, neck, head, mane, bridle) to create depth. Technical requirements: Output one complete <svg>...</svg> document with a viewBox attribute. Valid XML, inline only. Assign these IDs: obstacle-root on the root <svg>, obstacle-main on the <g> containing the full horse body, obstacle-animated-part on the mane only (a small <g> of flowing hair strands along the top of the neck), animated with <animateTransform type='rotate'> to gently sway. The mane is chosen because it is self-contained and sits on top. Do not return markdown fences or text outside the SVG."

Background drawing prompt rules:
- Every act MUST have a background_drawing_prompt. It is never null.
- Write a rich prompt describing a full-canvas SVG background for the scene.
- The background_drawing_prompt must include:
  1. Scene description — setting, atmosphere, mood, color palette
  2. Composition — what fills the canvas
  3. ID assignments: background-root, background-main, background-animated-part
  4. Animation direction — 3-4 subtle glow/color animations (opacity pulses, color cycling only — no translate, rotate, or scale)
  5. Technical requirements: valid XML, viewBox="0 0 800 200", inline only

Example background_drawing_prompt:
"Draw a full-canvas SVG background of a dark enchanted forest at twilight. Dense trees with gnarled trunks fill the sides. A narrow path winds through the center. The sky shows deep purple and dark blue gradients with faint stars. Use rich layering: distant treeline, mid-ground trunks, foreground bushes, sky above. Technical requirements: Output one complete <svg>...</svg> document with viewBox='0 0 800 200'. Valid XML, inline only. Assign these IDs: background-root on the root <svg>, background-main on the <g> containing all elements, background-animated-part on a <g> with 3-4 subtle animations: two fireflies with <animate attributeName='opacity'> cycling between 0.2 and 0.8 over 3s staggered, one star with <animate attributeName='fill'> cycling between #ffffff and #aaccff over 5s, a faint path glow with <animate attributeName='opacity'> pulsing between 0.05 and 0.15 over 4s. Animations must only use opacity and fill — no translate, rotate, or scale. Do not return markdown fences or text outside the SVG."
```

- [ ] **Step 2: Verify the prompt template still has required placeholders**

Check that `{rag_context}`, `{prompt}`, and `{preferred_obstacle_library_names}` are still present.

- [ ] **Step 3: Run Director agent tests**

Run: `pytest tests/unit/test_director_agent.py -v`
Expected: all PASS (tests check prompt building, which still uses the same placeholders)

- [ ] **Step 4: Commit**

```bash
git add pipeline/agents/director/prompt.txt
git commit -m "feat(director): add drawing prompt and background prompt instructions

Director now writes rich per-obstacle drawing prompts and per-act
background drawing prompts as part of its output.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 10: Update Renderer prompt — background layering, remove ground line

**Files:**
- Modify: `pipeline/agents/renderer/prompt.txt`

- [ ] **Step 1: Update Renderer prompt**

In `pipeline/agents/renderer/prompt.txt`:

1. Add background layering instructions after the "Scene geometry" section:

```
Background layering:
- If the clip manifest includes background_svg, embed it as the FIRST child of the scene SVG.
- The background fills the entire canvas and sits behind all other content.
- Layer order (back to front): background SVG → obstacle SVG → Linai character.
- Preserve any animations inside the background SVG as-is.
- If background_svg is absent, render the scene without a background layer.
```

2. Remove the `<line>` from the example SVG snippet. Change:

```
<line x1=\"0\" y1=\"{ground_line_y}\" x2=\"{canvas_width}\" y2=\"{ground_line_y}\" stroke=\"#1a1a1a\" stroke-width=\"2\"/>
```

Remove this line entirely from the example.

3. Add instruction: "Do not draw a visible ground line. The floor at y={ground_line_y} is invisible."

4. Update "ground line" references to say "invisible floor" where appropriate.

- [ ] **Step 2: Run Renderer agent tests**

Run: `pytest tests/unit/test_renderer_agent.py -v`
Expected: all PASS

- [ ] **Step 3: Commit**

```bash
git add pipeline/agents/renderer/prompt.txt
git commit -m "feat(renderer): add background layering, remove visible ground line

Renderer now embeds background SVG as first layer in scene.
Ground line at y=160 is invisible — not drawn in output.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 11: Update Animator prompt — invisible floor language

**Files:**
- Modify: `pipeline/agents/animator/prompt.txt`

- [ ] **Step 1: Update "ground line" references**

In `pipeline/agents/animator/prompt.txt`, replace references to "ground line" with "invisible floor":

- "The baseline ground line is at y={ground_line_y}" → "The invisible floor is at y={ground_line_y}"
- "ground line" → "invisible floor" throughout (but keep the `{ground_line_y}` placeholder name unchanged)

Do NOT change the placeholder name `{ground_line_y}` — it's a code reference. Only change the natural language descriptions.

- [ ] **Step 2: Run Animator agent tests**

Run: `pytest tests/unit/test_animator_agent.py -v`
Expected: all PASS

- [ ] **Step 3: Commit**

```bash
git add pipeline/agents/animator/prompt.txt
git commit -m "docs(animator): replace 'ground line' with 'invisible floor' in prompt

The floor coordinate is still used for positioning but is no longer rendered.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 12: Remove visible ground line from Linai SVG template

**Files:**
- Modify: `frontend/public/linai-template.svg`

- [ ] **Step 1: Remove the `<line>` element**

Open `frontend/public/linai-template.svg` and remove the horizontal `<line>` element at `y="160"`. It will look something like:

```xml
<line x1="0" y1="160" x2="800" y2="160" stroke="..." stroke-width="..."/>
```

Remove the entire element. Leave everything else unchanged.

- [ ] **Step 2: Verify Linai template tests still pass**

Run: `pytest tests/unit/test_linai_template.py -v`

If tests check for the line element, update them to no longer expect it.

- [ ] **Step 3: Commit**

```bash
git add frontend/public/linai-template.svg tests/unit/test_linai_template.py
git commit -m "feat(template): remove visible ground line from Linai SVG

The floor at y=160 is now invisible. Linai still stands at that coordinate.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 13: Remove La Linea references from all project docs

**Files:**
- Modify: `REQUIREMENTS.md`
- Modify: `DESIGN.md`
- Modify: `PHASES.md`
- Modify: `README.md`
- Modify: `STANDARDS.md`
- Modify: `knowledge-base/characters/linai/linai-character-overview.md`
- Modify: `knowledge-base/shared/the-world-is-the-line.md`
- Modify: `knowledge-base/shared/tone-all-ages.md`

- [ ] **Step 1: Find all La Linea references**

```bash
grep -rn "La Linea\|Cavandoli\|line-art\|line art\|floats along a line\|world is the line" --include="*.md" --include="*.txt"
```

- [ ] **Step 2: Update REQUIREMENTS.md**

Rewrite section 1 project overview. Replace:

> Linai — an original expressive line-art figure inspired by the visual style of classic Italian animation (most famously the "La Linea" series by Osvaldo Cavandoli). Linai floats along a line that forms her entire world

With:

> Linai — an original expressive animated character. Linai encounters obstacles, and reacts to choices the viewer makes.

Update the constraint section (section 7) — replace "Claude Sonnet (latest) via Amazon Bedrock" with "Claude models via Amazon Bedrock (per-agent configuration)".

Add a new requirement in section 5.7 for background SVGs:

> ANI-08 | Each scene clip shall include a full-canvas background SVG generated per act by the Drawing agent from a Director-provided prompt. Backgrounds may contain subtle glow and color-change animations but no translating or rotating elements.

- [ ] **Step 3: Update DESIGN.md**

- Remove the legal notice in the header (lines 21-22)
- Update section 2 Drawing agent description to mention background generation
- Update section 6.2 Director contract to show the new `Act` fields
- Update section 6.4 Renderer contract to mention `background_svg`
- Add a subsection for background SVG contract (IDs, viewBox, animation rules)
- Update section 4.1 to clarify per-agent model configuration

- [ ] **Step 4: Update PHASES.md**

- Phase 0: rewrite Linai description, remove "line-art" and La Linea references
- Phase 5: update scope to mention background generation, per-obstacle drawing prompts, per-agent model config

- [ ] **Step 5: Update README.md**

- Rewrite intro paragraph — remove La Linea attribution
- Remove legal notice at bottom (the "inspired by La Linea" disclaimer)

- [ ] **Step 6: Update STANDARDS.md**

- Update the config example in section 2.4 — replace single `BEDROCK_MODEL_ID` with per-agent values

- [ ] **Step 7: Update knowledge base docs**

- `knowledge-base/characters/linai/linai-character-overview.md` — remove La Linea style references, describe Linai's visual style on its own terms
- `knowledge-base/shared/the-world-is-the-line.md` — rewrite to describe Linai's world without "the line" as a defining concept
- `knowledge-base/shared/tone-all-ages.md` — remove any La Linea references

- [ ] **Step 8: Verify no remaining references**

```bash
grep -rn "La Linea\|Cavandoli" --include="*.md" --include="*.txt" --include="*.py" --include="*.ts"
```

Expected: zero matches

- [ ] **Step 9: Commit**

```bash
git add REQUIREMENTS.md DESIGN.md PHASES.md README.md STANDARDS.md knowledge-base/
git commit -m "docs: remove La Linea references, add background SVG and per-agent model docs

Linai is now described as an original character with no external attribution.
Updated all agent contracts, config examples, and knowledge base docs.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 14: Update test fixtures

**Files:**
- Modify: `tests/fixtures/valid_episode.json`
- Modify: any invalid fixtures that reference Act structure

- [ ] **Step 1: Update valid_episode.json**

Add `background_drawing_prompt` (a valid 50+ char string) to each act in the fixture. Add `drawing_prompt` to any act whose `obstacle_type` is not in the library. Example:

```json
{
  "act_index": 0,
  "obstacle_type": "wall",
  "approach_description": "Linai floats up to a tall wall.",
  "choices": [...],
  "drawing_prompt": null,
  "background_drawing_prompt": "Draw a full-canvas SVG background of a sunny meadow with rolling green hills, scattered wildflowers, and a bright blue sky with fluffy white clouds."
}
```

- [ ] **Step 2: Run full test suite**

Run: `pytest tests/unit/ -v`
Expected: all PASS

- [ ] **Step 3: Commit**

```bash
git add tests/fixtures/
git commit -m "test(fixtures): update valid_episode.json with new Act fields

Added background_drawing_prompt and drawing_prompt to fixture acts.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 15: Final verification

- [ ] **Step 1: Run ruff on entire pipeline**

Run: `ruff check pipeline/ tests/ && ruff format --check pipeline/ tests/`
Expected: clean

- [ ] **Step 2: Run full test suite**

Run: `pytest tests/unit/ -v`
Expected: all PASS

- [ ] **Step 3: Verify no old BEDROCK_MODEL_ID references remain**

```bash
grep -rn "config\.BEDROCK_MODEL_ID[^_]" pipeline/ tests/
```

Expected: zero matches

- [ ] **Step 4: Verify no La Linea references remain**

```bash
grep -rn "La Linea\|Cavandoli" --include="*.md" --include="*.txt" --include="*.py"
```

Expected: zero matches (except possibly the spec/plan docs themselves)

- [ ] **Step 5: Verify ground line removed from template**

```bash
grep -n "<line" frontend/public/linai-template.svg
```

Expected: no horizontal ground line at y=160
