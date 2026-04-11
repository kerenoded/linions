# Codex Agent Prompt: Linai v2 Character Redesign

## Task

Replace Linai's humanoid character (v1) with an ecto-cloud energy creature (v2). The full design spec is at `docs/superpowers/specs/linai-v2-character-redesign-design.md` — read it first.

## Context

Linions is an AI-powered animated episode generator. A pipeline of AI agents (Director, Animator, DrawingAgent, Renderer) produces SVG animation episodes featuring a character called Linai. Linai v1 is a humanoid with legs, arms, dress, eyelashes. The legs animate poorly, so we're replacing her with a floating ectoplasm cloud creature — no legs, no arms, expresses through eyes + internal energy patterns + color shifts.

The project uses Python (pipeline, agents, validators, tests), TypeScript (frontend, infra), and SVG. Tests use pytest. Linting uses ruff.

**Critical architecture detail**: `pipeline/media/linai_template.py` dynamically extracts part IDs from the SVG template file (`frontend/public/linai-template.svg`) by parsing the `<g id="linai">` group and collecting all descendant IDs. The Animator and Renderer agent prompts use `{linai_part_ids_json}` and `{linai_template_svg}` placeholders that are auto-populated from this module. This means once the SVG file is correctly structured with the right IDs, the prompt placeholders auto-update — no code changes needed for placeholder injection.

## Implementation Steps (in order)

### Step 1: Restructure and replace the SVG template

1. Read `frontend/public/ecto-cloud.raw.svg` — this is the approved new character SVG
2. Restructure it:
   - Add a top-level `<g id="linai">` wrapping ALL visual content (required by `linai_template.py` parser)
   - Rename `id="character-body"` to `id="linai-body"`
   - Rename `id="character-eye-left"` to `id="linai-eye-left"`
   - Rename `id="character-eye-right"` to `id="linai-eye-right"`
   - Find the mouth path (small smile curve, around line 110: `M112 98 Q118 104 125 100`) and wrap it in `<g id="linai-mouth">`
   - Find the swirling energy wisp paths (the `<!-- Swirling energy patterns inside -->` section) and wrap them in `<g id="linai-inner-patterns">`
   - Find the floating particle circles (the `<!-- Floating glowing particles inside body -->` section) and wrap them in `<g id="linai-particles">`
   - Find the vapor trail paths at the bottom (the `<!-- Wispy vapor trails -->` and `<!-- Dissolving bottom wisps -->` sections) and wrap them in `<g id="linai-trails">`
3. Back up the old template: copy `frontend/public/linai-template.svg` to `frontend/public/characters-v2/linai-v1-backup.svg`
4. Write the restructured SVG to `frontend/public/linai-template.svg`
5. Verify: the file must contain `id="linai"` as a top-level group, and the 7 expected IDs inside it: `linai-body`, `linai-eye-left`, `linai-eye-right`, `linai-mouth`, `linai-inner-patterns`, `linai-particles`, `linai-trails`

### Step 2: Update favicon

Replace `frontend/public/favicon.svg` with a minimal simplified version of the ecto-cloud — just the cloud silhouette outline and two simple eyes. Keep it under 20 elements total so it renders well at 32x32. You can hand-author this as a simple SVG.

### Step 3: Update the Renderer model

In `pipeline/models/renderer.py`, change the default value of `character_template_id` from `"linai-v1"` to `"linai-v2"`.

### Step 4: Update hardcoded part ID lists

Two files have hardcoded sets of Linai part IDs that are used for SVG validation:

1. `pipeline/lambdas/orchestrator/pipeline_orchestrator.py` (around lines 74-77) — find the hardcoded set of Linai IDs and replace with: `{"linai-body", "linai-eye-left", "linai-eye-right", "linai-mouth", "linai-inner-patterns", "linai-particles", "linai-trails"}`

2. `scripts/run-renderer-agent.py` (around lines 43-46) — same update

Search for other hardcoded sets of `linai-` IDs outside of tests and update them too.

### Step 5: Update validators

1. **`pipeline/validators/renderer_motion_validator.py`**: Remove all validation specific to `linai-leg-left-group`, `linai-leg-right-group`, and any leg-animation requirements. The new character has no legs. Update any part ID validation to use the v2 set.

2. **`pipeline/validators/frame_validator.py`**: Update the valid `part_notes.target_id` validation. The validator checks that target_ids in part_notes match valid Linai IDs. Since `linai_template.py` extracts IDs dynamically, check how the validator gets its valid ID list — if it calls `get_linai_part_ids()` then no change needed; if it has a hardcoded list, update it to the v2 IDs.

3. **`pipeline/validators/svg_linter.py`**: Check if it validates required character element IDs. If so, update to the v2 set.

### Step 6: Update Director prompt

Edit `pipeline/agents/director/prompt.txt`. Add a section after the rules that describes Linai's physical form:

```
Character form:
Linai is a translucent floating ectoplasm cloud creature — NOT a humanoid. She has:
- Two large expressive eyes (primary emotion tool)
- A cloud-like body that can expand, contract, stretch, and shift color
- Internal energy patterns that change with emotion (hearts when in-love, lightning when angry, sparkles when happy)
- Vapor trails below her body that react to movement and mood
- NO arms, legs, hands, feet, hair, dress, or eyelashes

Linai CANNOT: walk, step, stride, grab, hold, carry, pick up, kick, stomp, wave, point, climb, or crawl.
Linai CAN: float, drift, stream, surge upward, settle downward, pulse, glow, expand, contract, dissolve, radiate, phase through things.

When describing obstacle interactions, use ecto-cloud verbs:
- Instead of "climbs over wall" → "surges over wall" or "phases through crack"
- Instead of "jumps across hole" → "floats across" or "dissolves into hole"
- Instead of "steps through puddle" → "floats over" or "absorbs water and shifts color"
- Instead of "grabs object" → "envelops object" or "pulses energy at object"
```

Also search the Director prompt for any existing references to walking, arms, legs, or humanoid descriptions and remove/replace them.

### Step 7: Update Animator prompt

Edit `pipeline/agents/animator/prompt.txt`:

1. Replace all references to "Linai walking" with "Linai floating"
2. Remove lines about leg animation:
   - The guidance about "alternating steps, clear weight shifts" for grounded travel
   - The guidance about "step pattern explicit enough that the Renderer can animate both legs"
   - The guidance about targeting `linai-leg-left-group` and `linai-leg-right-group`
   - The guidance about `linai-feet-left` / `linai-feet-right` never detaching
   - The instruction "stepping rather than floating" — flip it: floating IS the default
3. Remove example part_notes that reference `linai-leg-*`, `linai-arm-*`, `linai-neck`
4. Replace with guidance for the new character:
   - For gaze: target `linai-eye-left` and `linai-eye-right` (the eye groups contain pupils+highlights)
   - For emotion patterns: target `linai-inner-patterns` to describe what patterns should appear (hearts, lightning, sparkles, question marks)
   - For vapor trails: target `linai-trails` to describe trail behavior (flaring, drooping, scattering)
   - For body expression: target `linai-body` with notes about expansion, contraction, color shift
5. Update the example keyframes to show ecto-cloud style part_notes
6. Change "her" pronouns if used in context of physical descriptions to match the new form
7. Keep the `{linai_part_ids_json}` placeholder — it auto-populates from the SVG

### Step 8: Update Renderer prompt

Edit `pipeline/agents/renderer/prompt.txt`:

1. Remove all guidance about animating legs, arms, eyelashes, dress
2. Add guidance for ecto-cloud animation:
   - Body: animate `transform` (translate for position, scale for expand/contract), `opacity` for glow effects, `fill` transitions for color shifting
   - Eyes: animate `transform` (scale for squint/widen, translate for gaze), `opacity`
   - Mouth: animate `d` attribute for path morphing (smile shapes)
   - Inner patterns: the Renderer MAY replace the content inside `<g id="linai-inner-patterns">` with emotion-appropriate SVG elements (hearts, lightning bolts, sparkles, etc.). This is the ONE exception to the "no new character elements" rule.
   - Particles: animate `transform` (translate for scatter/cluster) and `opacity`
   - Trails: animate `transform` (translate, scale for flare/droop) and `opacity`
3. Keep the `{linai_template_svg}` and `{linai_part_ids_json}` placeholders — they auto-populate

### Step 9: Update knowledge base documents

**`knowledge-base/characters/linai/`** — 27 documents. For each:

- `visual-vocabulary.md` — REWRITE fully. New action states: float, hover, surge, settle, pulse, dissolve, radiate. Same 7 expression states but achieved through eyes + internal patterns + color, not body posture. Define combinations using the new vocabulary.
- `emotional-range.md` — REWRITE fully. Same emotional range (no aggression, no cruelty), but expressed through: eye size/shape/glow, internal patterns, color shifting, body expand/contract, vapor trail behavior. Remove all references to fists, body language of limbs.
- `no-spoken-words.md` — Keep as-is.
- `linai-never-gives-up.md` — Keep personality, remove/replace physical descriptions involving limbs.
- `world-builder-awareness.md` — Update physical references.
- All `obstacle-*.md` files (wall, hole, tree, puddle, elevated-platform, bird, second-character) — REWRITE interactions for floating ecto-cloud form. No climbing, grabbing, stepping. Use floating, surging, phasing, dissolving, pulsing.
- All `situation-*.md` files (being-chased, encountering-beauty, confusion, small-victory, dramatic-failure, waiting, surprise, fourth-wall-frustration, creative-problem-solving, being-watched, examining-object, tiredness, delight, end-of-episode) — REWRITE physical descriptions. How does an ecto-cloud express tiredness? (dims, sinks, trails droop). How does it express surprise? (eyes widen, body pulses, particles scatter). Etc.

**`knowledge-base/shared/`** — update these:

- `pacing-approach-walk.md` — Rename to `pacing-approach-float.md`. Rewrite: "approach float" replaces "approach walk". Same 8-second default, same pacing philosophy, but character drifts/flows instead of walks. No arm swings, no stride.
- `animation-style-constraints.md` — REWRITE for ecto-cloud model. Key changes: movement is through translate/scale/opacity, not limb movement. Body parts are semi-independent (eyes react before body). Add exception: Renderer may inject content into `linai-inner-patterns` group for emotion symbols. Character template element set is the v2 set.

### Step 10: Update all tests

Run `pytest tests/ -v` to see what fails, then fix each:

1. **`tests/unit/test_linai_template.py`** — Rewrite to assert the 7 new IDs exist in the template: `linai-body`, `linai-eye-left`, `linai-eye-right`, `linai-mouth`, `linai-inner-patterns`, `linai-particles`, `linai-trails`. Remove assertions for old IDs (legs, arms, eyelashes, etc.).

2. **`tests/unit/test_orchestrator_pipeline.py`** — Update all SVG fixture strings that contain old `linai-*` element markup. Replace with simplified ecto-cloud SVG snippets that contain the v2 IDs.

3. **`tests/unit/test_renderer_motion_validator.py`** — Remove leg-animation tests. Add tests verifying the new character IDs are accepted. Remove any test that asserts leg groups must be animated for grounded movement.

4. **`tests/unit/test_renderer_scene_composer.py`** — Update SVG fixture strings to use v2 template markup.

5. **`tests/unit/test_frame_validator.py`** — Update valid part ID assertions. Old IDs like `linai-arm-left` should now be invalid. New IDs like `linai-inner-patterns` should be valid.

6. **`tests/unit/test_models.py`** — Update PartNote examples to use v2 IDs (e.g., `linai-inner-patterns` instead of `linai-arm-left`). Update `character_template_id` assertions from `"linai-v1"` to `"linai-v2"`.

7. **`tests/unit/test_animator_agent.py`** — Update prompt expectation tests. The generated prompt should now contain v2 IDs, not v1.

8. **`tests/unit/test_renderer_agent.py`** — Update SVG fixture strings to v2 template.

### Step 11: Lint and verify

```bash
ruff check pipeline/ scripts/ tests/
ruff format pipeline/ scripts/ tests/
pytest tests/ -v
```

All must pass with zero errors.

## Important Rules

- Do NOT commit anything or push to GitHub
- Do NOT deploy anything to AWS
- Do NOT modify files outside the scope described above
- The character name is still "Linai" — do not rename it
- The project names "Linions" and "Linoi" stay unchanged
- Keep the `viewBox="0 0 200 200"` on the new SVG template
- When rewriting knowledge base docs, maintain the same tone and style as existing docs — authoritative, specific, constraint-focused
- For knowledge base rewrites: each doc should be self-contained, describing one behavior/situation. Keep them roughly the same length as the originals.
- The `{linai_part_ids_json}` and `{linai_template_svg}` placeholders in prompt files auto-populate at runtime from `pipeline/media/linai_template.py` — do NOT hardcode the IDs into the prompt text where these placeholders appear
- Run `ruff check` and `pytest` after making changes — fix any failures before moving on
