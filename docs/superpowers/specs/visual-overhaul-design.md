# Visual Overhaul — Design Spec

> Status: draft
> Scope: Remove La Linea attribution, per-agent model config, Director-driven drawing prompts, background SVGs

---

## 1. Summary

This spec covers five interconnected changes to the Linions project:

1. **Remove La Linea / Cavandoli references** — Linai becomes an original character with no external attribution.
2. **Remove visible ground line** — the `<line>` element is removed from the SVG; `y=160` remains as an invisible floor coordinate.
3. **Per-agent model configuration** — each agent gets its own configurable Bedrock model ID instead of sharing one.
4. **Director-driven obstacle drawing prompts** — the Director writes rich, detailed SVG drawing prompts per obstacle (including animation direction), replacing the Drawing agent's generic template.
5. **Background SVGs** — the Director provides a per-act background drawing prompt; the Drawing agent generates full-canvas background SVGs with subtle glow/color animations.

---

## 2. Change 1 — Remove La Linea references

### What changes

All references to "La Linea", "Osvaldo Cavandoli", "inspired by classic Italian animation", "line-art figure", and the legal disclaimer are removed project-wide.

Linai is described as: **an original expressive animated character**.

### Files affected

| File | Change |
|------|--------|
| `REQUIREMENTS.md` | Rewrite section 1 project overview. Remove "inspired by" and "La Linea" from character description. |
| `DESIGN.md` | Remove legal notice in header. Remove all La Linea mentions. |
| `PHASES.md` | Rewrite Phase 0 Linai description. Remove "La Linea-inspired" from Phase 5 drawing brief. Remove style references ("La Linea style", "slightly oversized heads"). |
| `STANDARDS.md` | No La Linea references found — no change needed. |
| `README.md` | Rewrite intro paragraph. Remove legal/attribution notice at bottom. |
| `knowledge-base/characters/linai/linai-character-overview.md` | Remove La Linea style references. Describe Linai's visual style on its own terms. |
| `knowledge-base/shared/tone-all-ages.md` | Remove any La Linea references. |
| `knowledge-base/shared/the-world-is-the-line.md` | Rewrite — the world is no longer defined as "the line". |

---

## 3. Change 2 — Remove visible ground line

### What changes

The horizontal `<line>` element at `y=160` is removed from the Linai SVG template and from the Renderer's output. The `GROUND_LINE_Y` config value stays — it serves as the invisible floor coordinate for all position logic.

### Files affected

| File | Change |
|------|--------|
| `frontend/public/linai-template.svg` | Remove the `<line x1="0" y1="160" x2="800" y2="160" .../>` element. |
| `pipeline/config.py` | Update `GROUND_LINE_Y` comment: "invisible floor coordinate — not rendered as a visible line". |
| `pipeline/agents/renderer/prompt.txt` | Remove `<line>` from the example SVG snippet. Add instruction: "Do not draw a visible ground line." |
| `pipeline/agents/animator/prompt.txt` | Update "ground line" references to say "invisible floor at y={ground_line_y}" for clarity. |
| `knowledge-base/shared/the-world-is-the-line.md` | Rewrite or remove (overlaps with Change 1). |

### What does NOT change

- `GROUND_LINE_Y`, `SUPPORT_Y_TOLERANCE_PX`, `HANDOFF_SUPPORT_Y_TOLERANCE_PX` — all stay.
- Frame validator logic — unchanged, still checks positions relative to `ground_line_y`.
- Animator prompt — still references `ground_line_y` as the baseline coordinate.

---

## 4. Change 3 — Per-agent model configuration

### What changes

Replace the single `BEDROCK_MODEL_ID` with four per-agent model IDs, each with its own environment variable override.

### config.py — new values

```python
# --- Per-agent Bedrock model IDs ---
# Drawing agent uses Opus for highest SVG quality.
# All other agents use Sonnet for cost efficiency.

_BEDROCK_MODEL_ID_DIRECTOR_DEFAULT = "eu.anthropic.claude-sonnet-4-6"
_director_model_from_env = os.getenv("BEDROCK_MODEL_ID_DIRECTOR")
if _director_model_from_env is None:
    print(
        "WARN [config] BEDROCK_MODEL_ID_DIRECTOR not set; "
        f"using default: {_BEDROCK_MODEL_ID_DIRECTOR_DEFAULT}",
        file=sys.stderr,
    )
BEDROCK_MODEL_ID_DIRECTOR: str = _director_model_from_env or _BEDROCK_MODEL_ID_DIRECTOR_DEFAULT

_BEDROCK_MODEL_ID_ANIMATOR_DEFAULT = "eu.anthropic.claude-sonnet-4-6"
_animator_model_from_env = os.getenv("BEDROCK_MODEL_ID_ANIMATOR")
if _animator_model_from_env is None:
    print(
        "WARN [config] BEDROCK_MODEL_ID_ANIMATOR not set; "
        f"using default: {_BEDROCK_MODEL_ID_ANIMATOR_DEFAULT}",
        file=sys.stderr,
    )
BEDROCK_MODEL_ID_ANIMATOR: str = _animator_model_from_env or _BEDROCK_MODEL_ID_ANIMATOR_DEFAULT

_BEDROCK_MODEL_ID_DRAWING_DEFAULT = "eu.anthropic.claude-opus-4-6-v1"
_drawing_model_from_env = os.getenv("BEDROCK_MODEL_ID_DRAWING")
if _drawing_model_from_env is None:
    print(
        "WARN [config] BEDROCK_MODEL_ID_DRAWING not set; "
        f"using default: {_BEDROCK_MODEL_ID_DRAWING_DEFAULT}",
        file=sys.stderr,
    )
BEDROCK_MODEL_ID_DRAWING: str = _drawing_model_from_env or _BEDROCK_MODEL_ID_DRAWING_DEFAULT

_BEDROCK_MODEL_ID_RENDERER_DEFAULT = "eu.anthropic.claude-sonnet-4-6"
_renderer_model_from_env = os.getenv("BEDROCK_MODEL_ID_RENDERER")
if _renderer_model_from_env is None:
    print(
        "WARN [config] BEDROCK_MODEL_ID_RENDERER not set; "
        f"using default: {_BEDROCK_MODEL_ID_RENDERER_DEFAULT}",
        file=sys.stderr,
    )
BEDROCK_MODEL_ID_RENDERER: str = _renderer_model_from_env or _BEDROCK_MODEL_ID_RENDERER_DEFAULT
```

The old `BEDROCK_MODEL_ID` is removed entirely — no backwards compatibility shim.

### Temperature config

Drawing agent uses `temperature=0.5` (already hardcoded in agent.py). Make this a config value:

```python
DRAWING_TEMPERATURE: float = 0.5  # Lower temperature for more consistent SVG output
```

### Files affected

| File | Change |
|------|--------|
| `pipeline/config.py` | Replace `BEDROCK_MODEL_ID` with 4 per-agent values + `DRAWING_TEMPERATURE`. |
| `pipeline/agents/director/agent.py` | Use `config.BEDROCK_MODEL_ID_DIRECTOR`. |
| `pipeline/agents/animator/agent.py` | Use `config.BEDROCK_MODEL_ID_ANIMATOR`. |
| `pipeline/agents/drawing/agent.py` | Use `config.BEDROCK_MODEL_ID_DRAWING` and `config.DRAWING_TEMPERATURE`. |
| `pipeline/agents/renderer/agent.py` | Use `config.BEDROCK_MODEL_ID_RENDERER`. |
| `pipeline/lambdas/orchestrator/pipeline_orchestrator.py` | Update any model ID references. |
| `infra/lib/linions-stack.ts` | Update environment variable names if model ID is passed to Lambda. |
| `tests/cdk/test_linions_stack.py` | Update if it asserts on model env vars. |
| `STANDARDS.md` | Update the config example block in section 2.4. |
| `DESIGN.md` | Update agent contract descriptions to note per-agent model IDs. |
| `REQUIREMENTS.md` | Update constraint section — no longer "Claude Sonnet (latest)" for all agents. |

---

## 5. Change 4 — Director-driven obstacle drawing prompts

### Problem

Today the Drawing agent receives only the bare `obstacle_type` slug (e.g. "knight") and must invent the entire visual concept itself using a generic prompt template. The result quality depends entirely on the Drawing agent's imagination. Testing showed that rich, specific prompts (describing layering, detail, and animation) produce dramatically better SVG output.

### Solution

The Director — the creative brain of the pipeline — writes a complete, detailed drawing prompt for each obstacle that doesn't match the pre-authored library.

### Model changes (obstacle drawing prompt only — see Section 6 for final combined models)

**`pipeline/models/director.py`** — `Act` gets a new optional field: `drawing_prompt: str | None = None`

**`pipeline/models/drawing.py`** — `DrawingInput` gets the Director's prompt: `drawing_prompt: str`

### Drawing prompt contract

When `drawing_prompt` is not None, it must be a complete SVG drawing instruction that includes:

1. **Visual description** — what the obstacle looks like, physical details, pose/stance
2. **Layering order** — back-to-front shape order for depth (e.g. "cape, legs, torso, arms, helmet")
3. **ID assignments** — which visual elements map to required IDs:
   - `obstacle-root` on the root `<svg>` element
   - `obstacle-main` on the `<g>` containing the full obstacle body
   - `obstacle-animated-part` on a naturally self-contained element for idle animation
4. **Animation direction** — which part animates, what animation type, and why that part was chosen
5. **Technical requirements** — valid XML, inline only, no external images/scripts/foreignObject

Example (from testing):

```
Draw a detailed, high-quality SVG illustration of a medieval knight in a heroic
standing pose. The knight should have plate armor, a plumed helmet, a shield, and
a raised sword. Use rich layering of shapes (back-to-front: cape, legs, torso,
arms, weapon, pauldrons, helmet) to create depth and visual detail.

Technical requirements:
Output one complete <svg>...</svg> document with a viewBox attribute
Valid XML, inline only — no external images, scripts, or foreignObject

Assign these IDs to naturally fitting elements:
obstacle-root -> the root <svg> element
obstacle-main -> the <g> containing the full knight body
obstacle-animated-part -> the plume on the helmet only, animated with
<animateTransform type="rotate"> to gently sway back and forth

The plume is chosen as the animated part because it is naturally self-contained,
sits on top of all other elements, and animating it does not disrupt the
z-ordering of any other part of the figure.

Do not return markdown fences, explanations, or any text outside the SVG.
```

### Director prompt changes

The Director prompt (`pipeline/agents/director/prompt.txt`) is updated to:

1. Explain the drawing prompt format with the contract above
2. Include 2 few-shot examples (knight, horse) showing the expected detail level
3. Instruct: if `obstacle_type` matches a name in `preferred_obstacle_library_names`, set `drawing_prompt` to `null`
4. Instruct: the animated part should be naturally self-contained and sit on top of other elements so animation doesn't disrupt z-ordering

### Drawing agent changes

- `_build_prompt` no longer substitutes `{obstacle_type}` into a template
- Instead, uses `input.drawing_prompt` directly as the user-facing prompt
- The system prompt (inline in `agent.py`) remains as technical guardrails
- `prompt.txt` is removed — the Director's prompt replaces it entirely

### ScriptValidator changes

New validation rules in `pipeline/validators/script_validator.py`:

- When `obstacle_type` is NOT in the preferred library names AND `drawing_prompt` is `None` → error
- When `drawing_prompt` is not None: must be non-empty, minimum 50 characters
- When `obstacle_type` IS in the preferred library names AND `drawing_prompt` is not None → warning (not blocking, but logged)

### Orchestrator changes

- When obstacle is not in library: pass `drawing_prompt` from Director output into `DrawingInput`
- No prompt construction in orchestrator — the Director's prompt is used as-is

---

## 6. Change 5 — Background SVGs

### Problem

Currently scenes have no background — just Linai, the obstacle, and empty white space. Adding themed backgrounds (forest, cave, rainy sky) makes the visual output dramatically richer.

### Solution

The Director provides a `background_drawing_prompt` per act. The Drawing agent generates a full-canvas background SVG with subtle glow/color animations. The Renderer layers it behind everything.

### Final combined models (after Changes 4 + 5)

**`pipeline/models/director.py`** — final `Act`:

```python
class Act(BaseModel):
    model_config = ConfigDict(extra="forbid")

    act_index: int
    obstacle_type: ObstacleSlug
    approach_description: str
    choices: list[Choice]
    drawing_prompt: str | None = None       # None when obstacle matches library
    background_drawing_prompt: str          # always required — every act has a background
```

**`pipeline/models/drawing.py`** — final `DrawingInput`:

```python
class DrawingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    session_id: str
    obstacle_type: ObstacleSlug
    drawing_prompt: str                     # rich prompt from Director
    drawing_type: Literal["obstacle", "background"] = "obstacle"
```

**`pipeline/models/animator.py`** — `ClipManifest` addition:

```python
class ClipManifest(BaseModel):
    # ... existing fields ...
    obstacle_svg_override: str | None = None
    background_svg: str | None = None       # full-canvas background, populated by orchestrator
```

### Background SVG contract

- `viewBox="0 0 {canvas_width} {canvas_height}"` (from config, currently `800 200`)
- Required IDs:
  - `background-root` — root `<svg>` element
  - `background-main` — primary background content group
  - `background-animated-part` — group containing 3-4 subtle animations
- Allowed animations: glowing dots, opacity pulses, color transitions, shimmer effects
- NOT allowed: translating/moving elements, rotation, scaling — glow and color only
- Same security rules as obstacle SVGs (no `<script>`, external URLs, etc.)

### Background drawing prompt contract

The Director writes a prompt that includes:

1. **Scene description** — setting, atmosphere, mood, color palette
2. **Composition** — what fills the canvas (sky, trees, buildings, etc.)
3. **ID assignments** — `background-root`, `background-main`, `background-animated-part`
4. **Animation direction** — 3-4 subtle glow/color animations (e.g. "fireflies with gentle opacity pulse", "stars that softly change brightness")
5. **Technical requirements** — valid XML, inline only, full canvas viewBox

Example:

```
Draw a full-canvas SVG background of a dark enchanted forest at twilight. Dense
trees with gnarled trunks fill the sides. A narrow path winds through the center.
The sky above shows deep purple and dark blue gradients with faint stars. Use rich
layering: distant treeline, mid-ground trunks, foreground bushes, sky above.

Technical requirements:
Output one complete <svg>...</svg> document with viewBox="0 0 800 200"
Valid XML, inline only — no external images, scripts, or foreignObject

Assign these IDs:
background-root -> the root <svg> element
background-main -> the <g> containing all background elements
background-animated-part -> a <g> containing 3-4 subtle glow animations:
  - Two fireflies (small circles) with <animate attributeName="opacity"> cycling
    between 0.2 and 0.8 over 3 seconds, staggered
  - One distant star with <animate attributeName="fill"> softly cycling between
    #ffffff and #aaccff over 5 seconds
  - A faint glow on the path with <animate attributeName="opacity"> pulsing
    between 0.05 and 0.15 over 4 seconds

Animations must only use opacity and fill changes — no translate, rotate, or scale.
Do not return markdown fences, explanations, or any text outside the SVG.
```

### Drawing agent changes

- Check `drawing_type` to determine behavior:
  - `"obstacle"` — current behavior, validates `obstacle-*` IDs
  - `"background"` — uses background system prompt variant, validates `background-*` IDs
- System prompt has a background-specific variant emphasizing full-canvas composition and glow-only animation

### Renderer changes

- Renderer prompt updated with new layering order:
  1. Background SVG (full canvas, behind everything)
  2. Obstacle SVG (at fixed embed position)
  3. Linai character (animated per keyframes)
- When `background_svg` is present on a clip manifest, embed it as the first child of the scene SVG
- When `background_svg` is None, scene renders without background (backwards compatible)

### ScriptValidator changes

- `background_drawing_prompt` must be non-empty, minimum 50 characters
- Must be present on every act (it's a required field)

### SvgLinter changes

- Add background SVG validation mode: verify `background-root` ID, verify viewBox matches canvas
- Same security rules as obstacle SVGs
- Reuse existing validation logic with a `validation_mode: Literal["obstacle", "background", "scene"]` parameter or similar

### Orchestrator changes

- Per act: call DrawingAgent with `drawing_type="background"` using the Director's `background_drawing_prompt`
- Can run background + obstacle drawing calls in parallel per act (independent)
- Inject resulting `background_svg` into every `ClipManifest` for that act before passing to Renderer

---

## 7. Data flow — updated

```
Orchestrator receives validated DirectorOutput

Per act:
  obstacle_type in library?
    YES → use pre-authored SVG
    NO  → DrawingAgent(drawing_type="obstacle", drawing_prompt=act.drawing_prompt)

  DrawingAgent(drawing_type="background", drawing_prompt=act.background_drawing_prompt)

  (obstacle + background drawing calls run in parallel per act)

  SvgLinter validates both obstacle and background SVGs

  Inject obstacle_svg_override + background_svg into each ClipManifest for this act

AnimatorAgent choreographs Linai (unchanged)

RendererAgent produces final scene SVGs:
  Layer order: background → obstacle → Linai
```

---

## 8. Doc updates — full list

### REQUIREMENTS.md
- Section 1: rewrite project overview — remove La Linea, describe Linai as original character
- Section 5.4 (AGT-01): mention Drawing agent handles both obstacles and backgrounds
- Section 5.7 (ANI-04): remove "La Linea style" from obstacle description
- Section 7 constraints: replace "Claude Sonnet (latest)" with "per-agent model configuration"
- Add new requirement for background SVGs

### DESIGN.md
- Header: remove legal notice referencing La Linea
- Section 2: update Drawing agent description to include background generation
- Section 3: update data flow diagram with background drawing calls
- Section 4.1: update obstacle library section
- Section 6.2: update Director contract with `drawing_prompt` and `background_drawing_prompt`
- Section 6.4: update Renderer contract with `background_svg` field
- Add new section: background SVG contract (IDs, viewBox, animation rules)
- Update Drawing agent contract with `drawing_type` and `drawing_prompt`

### STANDARDS.md
- Section 2.4: update config example — replace single `BEDROCK_MODEL_ID` with per-agent values
- Remove any La Linea references (none found currently)

### PHASES.md
- Phase 0: rewrite Linai description, remove "line-art figure" and La Linea references
- Phase 5: update scope to include background generation, per-obstacle drawing prompts, per-agent models
- Update drawing brief and style references

### README.md
- Rewrite intro paragraph — remove La Linea attribution
- Remove legal notice at bottom
- Update project description

### Knowledge base
- `characters/linai/linai-character-overview.md` — remove La Linea style references
- `shared/the-world-is-the-line.md` — rewrite (the world is no longer defined by a line)
- `shared/tone-all-ages.md` — remove any La Linea references
- Any other docs referencing the style attribution

---

## 9. Test updates

| Test file | Changes needed |
|-----------|---------------|
| `tests/unit/test_models.py` | Add tests for new `Act` fields (`drawing_prompt`, `background_drawing_prompt`), updated `DrawingInput` fields (`drawing_prompt`, `drawing_type`), new `ClipManifest.background_svg` field |
| `tests/unit/test_script_validator.py` | Add tests: `drawing_prompt` validation (missing when needed, too short, present for library obstacle), `background_drawing_prompt` validation (missing, too short) |
| `tests/unit/test_svg_linter.py` | Add tests: background SVG validation (correct IDs, missing IDs, wrong viewBox) |
| `tests/unit/test_drawing_agent.py` | Update for new `DrawingInput` shape, test obstacle vs background type handling |
| `tests/unit/test_orchestrator_pipeline.py` | Update for background drawing calls, parallel obstacle+background execution, `background_svg` injection |
| `tests/unit/test_animator_agent.py` | Minor — verify `background_svg` field passes through `ClipManifest` |
| `tests/unit/test_debug_runners.py` | Update for per-agent model config |
| `tests/fixtures/valid_episode.json` | Update with new fields |
| `tests/fixtures/invalid/` | Add fixtures for missing `background_drawing_prompt`, short `drawing_prompt` |

---

## 10. Config changes — complete list

| Old value | New value | Notes |
|-----------|-----------|-------|
| `BEDROCK_MODEL_ID` | Removed | Replaced by per-agent values |
| — | `BEDROCK_MODEL_ID_DIRECTOR` | Default: `eu.anthropic.claude-sonnet-4-6` |
| — | `BEDROCK_MODEL_ID_ANIMATOR` | Default: `eu.anthropic.claude-sonnet-4-6` |
| — | `BEDROCK_MODEL_ID_DRAWING` | Default: `eu.anthropic.claude-opus-4-6-v1` |
| — | `BEDROCK_MODEL_ID_RENDERER` | Default: `eu.anthropic.claude-sonnet-4-6` |
| — | `DRAWING_TEMPERATURE` | Default: `0.5` |
| `GROUND_LINE_Y` comment | Updated | "invisible floor coordinate — not rendered" |
