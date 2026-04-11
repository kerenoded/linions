# Plan: Open Obstacle Types — Library Lookup + Agent Drawing

> Status: ready to implement
> When: Phase 5, Day 2 (after Animator, before Renderer)
> Scope: pipeline models, Director prompt, Drawing agent, Renderer agent, CDK bundling

---

## Problem (original approach discarded)

The original plan derived a closed `ObstacleType` list from the SVG folder. This was still
a closed list — just auto-generated instead of hardcoded. It still meant the user could
not write "Linai meets a dragon" or "Linai finds an airplane."

The user's actual goal is: any obstacle the story calls for should appear. The pre-authored
SVG library is a quality shortcut, not a ceiling.

---

## New approach: library lookup with agent drawing fallback

1. The Director writes whatever obstacle makes sense for the story (free string).
2. The orchestrator normalizes the name to a slug and checks if that SVG exists in the bundled
   obstacle library.
3. **If found** — the pre-authored SVG is embedded directly. Fast, consistent, zero LLM cost.
4. **If not found** — the Drawing agent draws a new obstacle SVG from scratch,
   following strict style guidelines derived from the existing library, and the orchestrator
   passes that SVG into the Renderer.

---

## What we learned from examining all 26 existing SVGs

These rules were verified by reading every file in `frontend/public/obstacles/`.
They inform the Drawing agent prompt directly.

### Scene placement (verified by `test-fit.html`)

```
Scene canvas:  viewBox="0 0 800 200", ground line at y=160
Obstacle embed: x=350  y=18  width=120  height=150
```

At these constants, obstacle content at y=142 (typical bottom) maps to scene y=18+142=160 ✓.
The embed constants must go into `config.py` and the Renderer prompt — the LLM must not guess them.

### Structure that never changes across all 26 files

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 150" fill="none">
  <g id="obstacle-root"
     stroke="#1a1a1a" stroke-width="2.5"
     stroke-linecap="round" stroke-linejoin="round">

    <!-- background/base elements first (back-to-front layer order) -->

    <{primary-shape} id="obstacle-main" fill="white" .../>

    <!-- details, features, limbs on top -->

    <g id="obstacle-animated-part">
      <!-- the one element that sways ±4° at idle -->
    </g>

    <!-- optional -->
    <g id="obstacle-animated-part-2"> ... </g>

  </g>
</svg>
```

### Color rules — strictly two colors only

| Use | Value |
|-----|-------|
| All strokes | `#1a1a1a` |
| Fill on closed shapes (to mask overlapping lines) | `white` |
| Fill on root `<g>` | `fill="none"` (inherited, not set explicitly) |
| Fill on `obstacle-root` group | NOT set — inherited |
| Any other color | NEVER |

No gradients. No shadows. No opacity. No `rgba`. No named colors.

### Positioning rules — verified across all 26

- Object **horizontally centered** around x=60 (the viewBox midpoint). Confirmed on every file.
- Object **bottom** at approximately y=140–145. Most characters ground at y=142.
- Object **top** must be **≥ y=5** — including animated parts like antennae.
  The alien (`alien.svg`) violates this: its antenna balls have `cy="0"` and get clipped by
  the viewBox. This is a known defect. **Do not repeat it.** If an object is tall (e.g. balloon,
  alien), the animated part that extends highest must still start at y≥5.
- Object should **fill most of the canvas height** — not tiny, not leaving large empty space.
  Good range: top at y=10–40, bottom at y=140–145.

### Stroke width conventions — observed across files

| Element type | stroke-width |
|-------------|--------------|
| Default (root group) | `2.5` |
| Character legs / animal limbs | `4` to `8` (chunky, readable at small size) |
| Fine detail (eyelashes, waist hint, heart outline) | `1.2` to `1.8` |
| Structural lines (brick rows, speaker grille) | `2.5` (default) |

Examples seen: cat legs `stroke-width="4"`, robot legs use rect (stroke-width inherited).
Thin detail lines give depth without cluttering.

### Layer order — always back-to-front

Observed pattern across character obstacles:
1. Background elements (perch/branch, ground patch, base shapes)
2. Body / torso (large shape, `fill="white"` to mask anything behind it)
3. Head (circle/ellipse, `fill="white"`)
4. Facial features (eyes, nose, mouth)
5. Limbs / appendages that overlap body
6. Animated part last (so it renders on top)

`fill="white"` on body shapes is critical — it masks line overlaps cleanly so strokes
don't show through. Every closed shape that overlaps another must have `fill="white"`.

### Eye pattern — gives characters life

```xml
<!-- eye socket -->
<ellipse cx="44" cy="48" rx="13" ry="16" fill="white"/>
<!-- iris -->
<ellipse cx="44" cy="48" rx="7" ry="9" fill="#1a1a1a"/>
<!-- glint — white circle slightly off-center -->
<circle cx="41" cy="44" r="2.5" fill="white"/>
```

The glint (`fill="white"`, small, slightly up-left from iris center) is what makes eyes
feel alive. Every character in the library uses this pattern.

### Animated part selection — observed patterns

| Obstacle | Animated part | Why it works |
|----------|--------------|--------------|
| wall | top wobbling brick | loose top brick, natural sway |
| bird | flapping wing | organic movement |
| robot | pulsing antenna + ring | mechanical idle |
| balloon | swaying basket | suspended, pendulum-like |
| cat | curling tail | tail pivot at base |
| alien | two antennae together | both in one `<g>` |

Rule: the animated part must have a **natural pivot at its base**. Tails, branches, flames,
antennae, fins, flags all work. The whole body never works. Rigid flat objects (a door)
can use a subtle door-handle jiggle or hinge wobble.

### Path style — organic C-curves, not straight lines

Almost every path uses `C` (cubic bezier) or `c` (relative cubic bezier) curves.
Straight lines (`L`, `H`, `V`) appear only for rigid man-made objects (robot body, wall bricks).
For anything organic (animals, plants, natural objects) use curves throughout.

### What to use as reference examples in the Drawing agent prompt

Best examples to include inline (concise + representative):
- `wall.svg` — simplest geometric object, shows brick layering
- `cat.svg` — character with limbs, eyes with glint, tail as animated part
- `bird.svg` — floating character with wing animation, branch perch

---

## Implementation steps

### Step 1 — Remove `ObstacleType` entirely

**`pipeline/models/shared.py`** — delete the `ObstacleType` Literal. Replace with nothing.

**`pipeline/models/director.py`** — `obstacle_type` becomes a plain `str`:

```python
class Act(BaseModel):
    act_index: int
    obstacle_type: str           # free string — slug format e.g. "wall", "dragon", "airplane"
    approach_description: str
    choices: list[Choice]
```

**`pipeline/models/episode.py`** — same: `obstacle_type: str`.

**`frontend/src/types.ts`** — `ObstacleType = string`.

**`pipeline/validators/script_validator.py`** — remove the obstacle type check entirely.
Add a new rule: `obstacle_type` must be a non-empty string matching `^[a-z0-9-]+$`
(slug format). This ensures clean filenames but imposes no closed list.

**`pipeline/models/__init__.py`** — remove `ObstacleType` from exports.

---

### Step 2 — Update the Director prompt

The Director prompt gets a section that:
- Tells it obstacle_type must be a slug (`lowercase-with-hyphens`, e.g. `wall`, `fire-dragon`)
- Lists the pre-authored library as "preferred names" — if the story fits one of these, use it
  exactly so the pre-drawn SVG is used automatically
- Makes clear it is NOT limited to the list

```
OBSTACLE NAMES
--------------
obstacle_type must be a lowercase slug (e.g. "wall", "fire-dragon", "hot-air-balloon").

Pre-drawn library (use exact name for best visual quality):
alien, balloon, barrel, bicycle, bird, boat, box, bridge, butterfly,
cactus, cat, chest, door, fence, ghost-shock, ghost-smiling, horse,
king, ladder, mountain, mushroom, robot, rocket, signpost, stairs, wall

If the story calls for something not in this list, invent a slug.
The Drawing agent will draw it. Be specific: "dragon" not "creature", "volcano" not "obstacle".
```

---

### Step 3 — Bundle obstacle SVGs with the Lambda

The Lambda needs the SVG files at runtime to embed pre-authored ones. Bundle them
in the Lambda package.

In CDK (`infra/lib/linions-stack.ts`), when defining the orchestrator Lambda, copy
the obstacles folder into the Lambda asset:

```typescript
// Include obstacle SVGs in the Lambda bundle
const orchestratorFn = new lambda.Function(this, 'OrchestratorFn', {
  // ...existing config...
  bundling: {
    // copy frontend/public/obstacles/ into lambda at obstacles/
    commandHooks: {
      afterBundling(inputDir: string, outputDir: string): string[] {
        return [`cp -r ${inputDir}/../frontend/public/obstacles ${outputDir}/obstacles`];
      },
      // ...
    }
  }
});
```

At runtime the Lambda reads SVGs from `Path(__file__).parent / "obstacles"`.

Add a shared helper `pipeline/media/obstacle_library.py`:

```python
import pathlib

_LIBRARY_DIR = pathlib.Path(__file__).parent.parent / "obstacles"

def get_obstacle_svg(slug: str) -> str | None:
    """Return pre-authored SVG content for slug, or None if not in library."""
    path = _LIBRARY_DIR / f"{slug}.svg"
    return path.read_text() if path.exists() else None

def list_library_names() -> list[str]:
    """Return sorted list of obstacle names available in the pre-authored library."""
    return sorted(p.stem for p in _LIBRARY_DIR.glob("*.svg"))
```

The orchestrator calls `list_library_names()` to populate the Director prompt's
"Pre-drawn library" section dynamically — it always reflects the actual files.

---

### Step 4 — Add the Drawing agent (new agent, same Lambda)

Drawing is a separate concern from animation. Rather than asking the Renderer to both
compose scenes AND invent new obstacle visuals, a dedicated `DrawingAgent` handles
obstacle generation. It runs between the Animator and Renderer stages, only when needed.

**Why a separate agent, not a new Lambda:** The drawing task is fast and runs inside the
same orchestrator Lambda. A new Lambda would add cold-start latency and operational
complexity with no benefit. A separate agent keeps the concern isolated (own prompt,
own tests) without the infrastructure overhead.

**Orchestrator flow with Drawing agent:**

```
Director → ScriptValidator → Animator → FrameValidator
  → Drawing (once per unique unknown obstacle slug)
  → Renderer → SvgLinter
```

The orchestrator resolves all obstacle SVGs before building `RendererInput`:

```python
from pipeline.media.obstacle_library import get_obstacle_svg

obstacle_svgs: dict[str, str] = {}
for slug in {act.obstacle_type for act in director_output.acts}:
    svg = get_obstacle_svg(slug)
    if svg is None:
        svg = drawing_agent.run(DrawingInput(obstacle_type=slug, ...))
        # run through SvgLinter immediately — retry on failure
    obstacle_svgs[slug] = svg

# inject into ClipManifest before passing to Renderer
for clip in animator_output.clips:
    clip.obstacle_svg_override = obstacle_svgs.get(clip.obstacle_type)
```

Add `obstacle_svg_override: str | None` to `ClipManifest`.

The Renderer receives every obstacle SVG pre-resolved. It only composes scenes —
it never draws or does file I/O. The Renderer prompt says:

```
For each clip, obstacle_svg_override is a complete SVG string.
Embed it exactly as-is inside the scene. Do not modify it.
```

**Drawing agent prompt** — see `PHASES.md` Phase 5 section for the full prompt content.
The full style guide, reference character SVG, quality checklist, and output rules
are defined there and must be copied verbatim into `pipeline/agents/drawing/prompt.txt`.

---

### Step 5 — Update the SVG linter

The `svg_linter.py` already rejects `<script>`, external URLs, and `data:` URIs.
No new rules needed. The required-IDs check (if any) should not reject generated obstacles
that follow the style guide — the linter checks security rules, not style rules.

If a required-IDs check exists or is added later, scope it to Linai's character SVG,
not to obstacle SVGs.

---

### Step 6 — Update DESIGN.md

In §6.1: remove `ObstacleType = Literal[...]`, replace with:

```
obstacle_type — str, slug format ^[a-z0-9-]+$
  If slug matches a file in the bundled obstacle library, that SVG is used.
  Otherwise the Drawing agent draws a new SVG following the style guide in
  pipeline/agents/drawing/prompt.txt, and the orchestrator passes that SVG to the Renderer.
```

In §6.4 Renderer behavior section: replace the fallback note with the full lookup
→ draw flow.

---

### Step 7 — Update tests

- `script_validator` tests: replace obstacle type membership tests with slug format tests.
- Add `obstacle_library` unit tests: known slug returns SVG, unknown returns None.
- Renderer tests: add a test case where `obstacle_svg_override` is None and the agent
  is expected to generate. Use a fixture for a generated obstacle SVG that passes the
  required-IDs and linter checks.
- Remove all tests referencing the old `ObstacleType` Literal import.

---

## Files changed summary

| File | Change |
|------|--------|
| `pipeline/models/shared.py` | Remove `ObstacleType` Literal |
| `pipeline/models/director.py` | `obstacle_type: str` |
| `pipeline/models/episode.py` | `obstacle_type: str` |
| `pipeline/models/__init__.py` | Remove `ObstacleType` export |
| `pipeline/models/animator.py` | Add `obstacle_svg_override: str \| None` to `ClipManifest` |
| `pipeline/validators/script_validator.py` | Replace type-membership check with slug-format check |
| `pipeline/media/obstacle_library.py` | New — `get_obstacle_svg()`, `list_library_names()` |
| `pipeline/agents/director/prompt.txt` | Add obstacle naming section with dynamic library list |
| `pipeline/agents/drawing/agent.py` | New — `DrawingAgent` with `run(DrawingInput) -> str` |
| `pipeline/agents/drawing/prompt.txt` | New — full style guide (content defined in PHASES.md Phase 5) |
| `pipeline/agents/renderer/prompt.txt` | Remove drawing logic — Renderer only composes scenes now |
| `pipeline/lambdas/orchestrator/` | Library lookup + Drawing agent call before `RendererInput` build |
| `infra/lib/linions-stack.ts` | Bundle `frontend/public/obstacles/` into orchestrator Lambda |
| `frontend/src/types.ts` | `ObstacleType = string` |
| `DESIGN.md` §6.1, §6.4 | Update contracts |
| All tests referencing `ObstacleType` | Update imports and assertions |
