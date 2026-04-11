<!-- AI ASSISTANT: Read in this order before writing any code:
  1. REQUIREMENTS.md
  2. STANDARDS.md  
  3. DESIGN.md
  4. PHASES.md
  Then confirm which phase you are implementing before starting. -->

# Design — Linions

> Version 1.6 | Status: approved
>
> Technical blueprint. REQUIREMENTS.md = what and why. STANDARDS.md = quality rules.
> This document = how.
>
> Every agent contract, JSON schema, and state machine here is the single source of truth.
> Tests, fixtures, and prompt templates must match exactly. Update this document first when
> any contract changes.
>
> Linai and the Linions characters are original creations.

---

## 1. Repository structure

```
linions/
│
├── infra/                          # AWS CDK (TypeScript) — single LinionsStack
│   ├── bin/app.ts
│   ├── lib/linions-stack.ts           # One stack — every deployer gets the full system
│   ├── config.ts
│   ├── tsconfig.json
│   └── package.json
│
├── pipeline/                       # Python — runs on Lambda
│   ├── config.py                   # Single source of truth for all Python config values
│   ├── agents/
│   │   ├── director/
│   │   │   ├── agent.py            # DirectorAgent — storyteller + RAG query
│   │   │   └── prompt.txt
│   │   ├── animator/
│   │   │   ├── agent.py            # AnimatorAgent — keyframe choreographer
│   │   │   └── prompt.txt
│   │   ├── drawing/
│   │   │   └── agent.py            # DrawingAgent — obstacle and background illustrator
│   │   └── renderer/
│   │       ├── agent.py            # RendererAgent — SVG animation coder
│   │       └── prompt.txt
│   ├── models/                     # Pydantic v2 models split by bounded context
│   │   ├── director.py             # DirectorInput, DirectorOutput
│   │   ├── animator.py             # AnimatorInput, AnimatorOutput, Keyframe, ClipManifest
│   │   ├── drawing.py              # DrawingInput, DrawingOutput
│   │   ├── renderer.py             # RendererInput, RendererOutput, SvgClip
│   │   ├── episode.py              # Episode root model, Act, Choice
│   │   └── shared.py               # ValidationResult, ExpressionState, ActionType
│   ├── validators/
│   │   ├── script_validator.py     # Pure function — validates DirectorOutput
│   │   ├── frame_validator.py      # Pure function — validates AnimatorOutput
│   │   └── svg_linter.py           # Pure function — validates + sanitises SVG
│   ├── storage/
│   │   ├── job_store.py            # DynamoDB read/write (orchestrator only)
│   │   └── episode_store.py        # S3 read/write (orchestrator only)
│   ├── media/
│   │   ├── obstacle_library.py     # Bundled obstacle SVG lookup helpers
│   │   └── thumbnail.py            # Shared utility — used by orchestrator, reusable in future v2 deploy automation
│   ├── shared/
│   │   └── logging.py              # Structured logging used by all Lambda packages
│   └── lambdas/                    # One sub-package per Lambda function
│       ├── shared/                 # Cross-Lambda utilities (aws_clients, http helpers)
│       ├── generate/               # linions-generate handler
│       ├── orchestrator/           # linions-orchestrator handler + orchestration flow
│       └── status/                 # linions-status handler
│
├── proxy/                          # Node.js local proxy
│   ├── server.ts                   # Serves local creator UI, reads GitHub username, signs Lambda calls
│   ├── config.ts                   # Proxy tunable values (PORT, etc.)
│   ├── .env.example                # Template — copy to .env and fill with setup-env.sh
│   └── package.json
│
├── frontend/                       # TypeScript browser UI (no framework)
│   ├── src/
│   │   ├── main.ts                 # Bootstraps either local creator UI or public viewer UI
│   │   ├── player.ts               # Shared episode player state machine
│   │   ├── gallery.ts              # Public gallery renderer — reads CloudFront episodes/index.json
│   │   ├── generator.ts            # Local creator prompt input + job polling
│   │   ├── viewer.ts               # Public viewer routing for gallery and /story/* pages
│   │   └── types.ts                # Shared TypeScript types (mirrors models.py)
│   ├── public/
│   │   ├── index.html              # Public viewer shell deployed to S3/CloudFront
│   │   ├── studio.html             # Local creator shell served only by the proxy
│   │   ├── linai-template.svg      # Hand-authored Linai SVG (completed in Phase 0)
│   │   └── obstacles/              # Pre-authored obstacle SVG library
│   └── tsconfig.json
│
├── knowledge-base/                 # RAG source documents (authored in Phase 0)
│   ├── characters/
│   │   └── linai/                  # 27 docs: Linai's personality, sounds, and behaviors
│   └── shared/                     # ~19 docs: world rules, narrative structure, pacing
│
├── scripts/
│   ├── build-index.js              # Scans repo episodes/, generates thumbnails, and rebuilds index.json
│   └── setup-env.sh                # Reads CDK stack outputs and writes .env automatically
│
├── episodes/                       # Seed + owner-managed published episodes (repo content for v1)
│   ├── index.json                  # Gallery index — regenerated locally from repo content
│   └── {username}/
│       └── {uuid}/
│           ├── episode.json
│           └── thumb.svg

├── docs/
│   ├── plans/
│   │   └── dynamic-obstacle-types.md
│   ├── versions/
│   │   └── v2/
│   │       ├── community-contributions-and-canonical-gallery.md
│   │       └── multilanguage-support.md
│   └── superpowers/
│       ├── plans/
│       └── specs/
│
├── tests/
│   ├── unit/
│   ├── cdk/
│   └── fixtures/
│       ├── valid_episode.json
│       └── invalid/
│
├── REQUIREMENTS.md
├── STANDARDS.md
├── DESIGN.md
├── PHASES.md
├── .gitignore
└── README.md
```

---

## 2. What each component does

### Agents

**DirectorAgent — storyteller**  
Takes the user prompt and RAG character knowledge. Writes the complete episode script:
acts, obstacles, choices, win/fail outcomes, episode title, and gallery description.
The only agent that queries the RAG knowledge base.

**AnimatorAgent — choreographer**  
Takes the Director's script. Produces a precise timeline of keyframes for every clip in
every branch: Linai's position, support surface, expression, action, and timing.
Covers one approach clip plus exactly one resolution clip per choice in every act:
`win` for the winning choice and `fail` for each losing choice.

**DrawingAgent — obstacle and background illustrator**
Draws two types of SVG assets: obstacle SVGs (when an obstacle slug does not match a
pre-authored library asset) and background SVGs (one per act, from Director-authored prompts).
Each type uses a separate system prompt embedded in the agent code. Obstacle SVGs are cached
by slug within a generation job; background SVGs are generated once per act. The orchestrator
batches all unresolved Drawing tasks into one bounded parallel pool capped by
`MAX_PARALLEL_DRAWING_TASKS` and retries only failed obstacle/background identities.
The Drawing agent receives a `drawing_prompt` from the Director and a `drawing_type` flag.

**RendererAgent — SVG coder**  
Takes the Animator's keyframes plus pre-resolved obstacle SVGs. Produces complete
self-contained SVG animation clips.
Writes `<animate>` and `<animateTransform>` targeting known character template element IDs.
Embeds the obstacle SVG supplied by the orchestrator for each clip.
No external URLs in output. Every clip is fully portable.

### Validators

**ScriptValidator** — checks Director output: correct act count, correct choice count,
exactly one winning choice per act, all fields within length limits, all obstacle types
from the allowed list. Returns every failed rule, not just the first.

**FrameValidator** — checks Animator output: coordinates within canvas bounds, time values
strictly increasing, all required clips present for every branch.

**SvgLinter** — parses Renderer output as XML, strips dangerous tags and attributes, rejects
external URLs and `data:` URIs, checks file size, verifies character element IDs present.

### thumbnail.py (shared utility)

Extracts a static first-frame SVG from an approach clip by removing all animation elements.
Used by the orchestrator Lambda and designed for reuse by future v2 deploy automation.

---

## 3. System data flow

### 3.1 Generate mode

```
Developer opens localhost:3000 in browser
  [local creator UI only — never deployed to CloudFront]
  │
  │  POST /generate  { "prompt": "..." }
  │  (username injected by proxy — never sent by browser)
  ▼
Local proxy (Node.js)
  │  username read from GitHub CLI / git config at startup
  │  SigV4 signature computed using ~/.aws credentials
  │  credentials and username never reach the browser
  ▼
Lambda Function URL  authType: AWS_IAM
  │  unsigned requests → 403 at AWS infrastructure level, Lambda never runs
  ▼
Lambda 1: linions-generate
  1. validate prompt (length, not empty) → 400, no AWS calls made
  2. username verified present (injected by proxy) → 400 if missing
  3. generate jobId
  4. create DynamoDB item (condition: item must not exist)
  5. PENDING → GENERATING (conditional write)
  6. return 200 { jobId } immediately
  7. invoke Lambda 2 asynchronously (InvocationType: Event)

Lambda 2: linions-orchestrator
  [AWS auto-retries up to 2× on unhandled exception]
  [DLQ captures { jobId, prompt, username } after all retries exhausted]
  [Conditional DynamoDB check prevents double-processing on retry]

  creates AgentCore session

  ├─ DynamoDB: "[1/5] Querying character knowledge base..."
  │  Bedrock KB query #1: obstacle behaviors (prompt as query)
  │  Bedrock KB query #2: tone/style rules (dominant emotion as query)
  │  assemble rag_context from both results

  ├─ DynamoDB: "[2/5] Generating story script..."
  │  DirectorAgent.run(DirectorInput) → uses Bedrock + rag_context
  │  ScriptValidator.validate(output)
  │    success → continue
  │    failure → re-prompt with exact errors (retry up to MAX_AGENT_RETRY_COUNT)
  │    exhausted → DynamoDB FAILED, exit

  ├─ DynamoDB: "[3/5] Validating script structure..."  (label confirms pass)

  ├─ DynamoDB: "[4/5] Designing animation keyframes..."
  │  split validated acts into one AnimatorInput per act
  │  AnimatorAgent.run(one-act AnimatorInput) → uses Bedrock + AgentCore session
  │    launch all act calls in parallel
  │    validate each act output independently
  │    retry only failed acts with exact errors
  │    merge successful act outputs into one AnimatorOutput

  ├─ DynamoDB: "[5/5] Rendering SVG clips..."
  │  resolve obstacle SVGs per act:
  │    library hit → use bundled pre-authored SVG
  │    library miss → enqueue Drawing task once per unique slug
  │  resolve background SVGs per act:
  │    enqueue Drawing task once per act using background_drawing_prompt
  │  run queued Drawing tasks in one bounded parallel pool
  │    validate each output independently
  │    retry only failed task identities with exact errors
  │    inject obstacle_svg_override / background_svg into matching clips
  │  RendererAgent.run(RendererInput) → uses Bedrock + AgentCore session
  │  SvgLinter.validate_and_sanitise(output) → same retry pattern

  ├─ enforce cost guardrails (token counts, file sizes from config)
  ├─ assemble episode JSON (all SVG inline, username populated, schemaVersion set)
  ├─ compute contentHash (SHA-256, contentHash field set to null before hashing)
  ├─ extract thumbnail using thumbnail.py (from first approach clip)
  ├─ write draft episode JSON: drafts/{username}/{uuid}/episode.json
  ├─ write draft thumbnail: drafts/{username}/{uuid}/thumb.svg
  ├─ write supporting SVG assets: drafts/{username}/{uuid}/obstacles/ and /backgrounds/
  │    if any write after episode JSON fails → rollback all written keys → mark FAILED → exit
  └─ DynamoDB: DONE + draftS3Key

Browser polls Lambda 3 every POLLING_INTERVAL_SECONDS
Lambda 3: linions-status → DynamoDB GetItem → { status, stage, draftS3Key }

On DONE:
  browser fetches episode JSON from drafts/ via proxy (SigV4 signed S3 GetObject)
  player renders animation
  inline preview (default) + Download button appear
  [episode is NOT yet in gallery — it is a draft]
```

### 3.2 Repo publication flow

After a draft is generated, the developer can publish it publicly through the repo-managed flow:

```
download episode JSON from localhost studio
add episode JSON under episodes/{username}/ in the repo
run node scripts/build-index.js
redeploy LinionsStack so repo-managed episodes/ content is uploaded to S3/CloudFront
```

Once deployed, the direct public story URL is:

```
https://{developer-cloudfront-domain}/story/{username}/{uuid}
```

This URL opens the public episode page only. It does not include the local creator form,
download/export controls, or any developer-only controls.

### 3.3 View mode

```
Any browser → any LinionsStack CloudFront domain
  /story/{username}/{uuid} → fetches episodes/{username}/{uuid}/episode.json → episode page
  /                        → fetches episodes/index.json → gallery
```

Every `LinionsStack` deployment serves a public viewer site only at its CloudFront URL.
The public viewer has two surfaces:
- a gallery home page that shows published episodes as thumbnail-first cards
- a dedicated episode page focused on the selected story and player

The CloudFront viewer does not include prompt input, generation progress, download/export,
or any creator-only workflow. Those exist only in the localhost creator UI
served by the proxy.

Fully responsive: SVG scales with `width: 100%; height: auto`.
Choice buttons stack vertically below 600px. Gallery uses single-column below 600px.

### 3.4 Community contribution workflow (planned for v2)

Community contributions, canonical owner-gallery sync, GitHub PR validation, and the
Contribute button are intentionally out of scope for v1. The design for that workflow
lives in `docs/versions/v2/community-contributions-and-canonical-gallery.md`.

---

## 4. Episode JSON — self-contained design

Every episode JSON is a complete portable artifact:
- All SVG clips are inline strings — no external URL references
- Username is populated from generation time — never empty, never modified
- Works from any S3 prefix (drafts/ or episodes/), any account, or as a local file
- Any deployment can serve its own published episode file once it is copied to `episodes/`

**Episode lifecycle:** generated → `drafts/{username}/{uuid}/episode.json` (not in gallery) →
downloaded/exported into the repo → `episodes/{username}/{uuid}/episode.json` after repo update and
deploy (in gallery, shareable). Each UUID folder also contains `thumb.svg` and supporting
`obstacles/` and `backgrounds/` SVG assets. The public viewer site and the localhost creator UI are
separate surfaces over the same published episode artifacts.

### 4.1 Pre-authored obstacle library

Obstacle scene assets are pre-authored SVG files stored at:

`frontend/public/obstacles/{name}.svg`

Each obstacle SVG must use:

- `viewBox="0 0 120 150"`
- Required IDs:
  - `obstacle-root` (root group)
  - `obstacle-main` (primary obstacle body)
  - `obstacle-animated-part` (idles with a gentle 4-degree sway animation)
- Optional ID:
  - `obstacle-animated-part-2` (second independently animated element)

Renderer behavior:
- The Renderer agent uses this pre-authored obstacle library as scene background content.
- It does not generate obstacle geometry from scratch when a matching file exists.
- When the obstacle type matches a file in the library, the Renderer embeds that SVG.
- For unknown obstacle types, the orchestrator calls DrawingAgent and passes the
  generated SVG into the Renderer.

---

## 5. Input validation (Lambda 1)

| Rule | Detail |
|------|--------|
| Prompt not empty | After whitespace trim |
| Minimum length | 10 characters |
| Maximum length | `MAX_PROMPT_LENGTH_CHARS` (config, default 500) |
| Username present | Injected by proxy — Lambda validates it is non-empty |
| Language | All languages accepted |
| Adult content | Director system prompt + Bedrock built-in content filters |

On failure: 400 `{ "error": "...", "field": "..." }`. No DynamoDB writes, no cost.

---

## 6. Agent contracts

All I/O is Pydantic v2 models defined in `pipeline/models.py`. No raw dicts between stages.

> **Pydantic v2** — Python data validation library. Define a class with typed fields;
> Pydantic validates any data loaded into it and raises a clear, specific error on mismatch.
> Prevents bad AI output from propagating silently through the pipeline.

### 6.1 Shared types

Obstacle names are **open slugs**, not a closed enum.
Every `obstacle_type` value must be a non-empty string matching `^[a-z0-9-]+$`.
Examples: `wall`, `bird`, `hot-air-balloon`, `fire-dragon`.

Animator creativity is intentionally **open-ended**. `expression` and `action` are not
closed enums anymore; they are short natural-language strings. The only closed values in
this part of the contract are structural fields such as `branch`.

```python
ExpressionState = str          # open creative phrase, e.g. "trying to stay brave"
ActionType = str               # open creative phrase, e.g. "steps back nervously"
CreativeNote = str             # open short note for timing/body/face nuance
LinaiPartId = str              # must match a real SVG id from frontend/public/linai-template.svg
```

### 6.2 Director agent

```python
class DirectorInput(BaseModel):
    prompt: str
    username: str              # developer's GitHub username — used in episode metadata
    job_id: str
    session_id: str            # AgentCore session ID
    rag_context: str           # assembled from two Bedrock KB queries before this call
    preferred_obstacle_library_names: list[str]  # injected by orchestrator for prompt grounding

class Choice(BaseModel):
    label: str                 # shown as button text — max 40 chars
    is_winning: bool
    outcome_description: str   # fed to Animator for this branch

class Act(BaseModel):
    act_index: int             # 0-based sequential
    obstacle_type: str         # slug format, e.g. "wall", "dragon", "hot-air-balloon"
    approach_description: str
    choices: list[Choice]      # 2–3, exactly one is_winning=True
    drawing_prompt: str | None = None  # rich SVG prompt for non-library obstacles (>= 50 chars)
    background_drawing_prompt: str     # rich SVG prompt for the act's background (>= 50 chars)

class DirectorOutput(BaseModel):
    title: str                 # max 60 chars
    description: str           # max 120 chars — shown in gallery card
    acts: list[Act]            # 2–3
```

**ScriptValidator checks:**
- `acts` count: `MIN_OBSTACLE_ACTS` to `MAX_OBSTACLE_ACTS`
- Each act: `MIN_CHOICES_PER_ACT` to `MAX_CHOICES_PER_ACT` choices
- Each act: exactly one `is_winning=True`
- Every `obstacle_type` is a non-empty slug matching `^[a-z0-9-]+$`
- `title` ≤ 60, `description` ≤ 120, `label` ≤ 40 chars
- `act_index`: 0-based, sequential, no duplicates
- Non-library obstacles require a non-null `drawing_prompt` (≥ 50 chars)
- Every act requires a `background_drawing_prompt` (≥ 50 chars)

### 6.3 Animator agent

```python
class AnimatorInput(BaseModel):
    job_id: str
    session_id: str
    acts: list[Act]
    walk_duration_seconds: int   # from config.WALK_DURATION_SECONDS
    canvas_width: int            # from config.CANVAS_WIDTH
    canvas_height: int           # from config.CANVAS_HEIGHT
    ground_line_y: int           # from config.GROUND_LINE_Y
    handoff_character_x: int     # canonical x-position for act-boundary continuation poses
    requires_handoff_in: bool = False   # explicit for one-act parallel Animator calls
    requires_handoff_out: bool = False  # explicit for one-act parallel Animator calls

class PartNote(BaseModel):
    target_id: LinaiPartId       # must target a real id inside the canonical #linai group
    note: CreativeNote           # open part-specific acting note

class Keyframe(BaseModel):
    time_ms: int                 # non-negative, strictly increasing within clip
    character_x: float           # 0 to canvas_width
    character_y: float           # actual vertical position within canvas bounds
    support_y: float             # surface height under Linai for that keyframe
    is_grounded: bool            # lower cloud mass settled near support_y, or airborne if false
    is_handoff_pose: bool = False  # true only for standard act-boundary continuity poses
    expression: ExpressionState
    action: ActionType
    motion_note: CreativeNote | None = None
    part_notes: list[PartNote] = []

class ClipManifest(BaseModel):
    act_index: int
    obstacle_type: str             # copied from the owning Act for downstream stages
    branch: Literal["approach", "win", "fail"]
    choice_index: int | None     # None for approach clips
    duration_ms: int
    keyframes: list[Keyframe]    # min 2
    obstacle_x: float            # 50 to canvas_width - 50
    obstacle_svg_override: str | None = None  # populated by orchestrator before Renderer runs
    background_svg: str | None = None  # full-canvas background SVG, populated by orchestrator

class AnimatorOutput(BaseModel):
    clips: list[ClipManifest]
    # per act: 1 approach + (N choices × 1 resolution clip)
```

**FrameValidator checks:**
- `character_x` within `[0, canvas_width]`
- `character_y` within `[0, canvas_height]`
- `support_y` within `[0, canvas_height]`
- grounded keyframes keep `character_y` near `support_y` within `SUPPORT_Y_TOLERANCE_PX`
- airborne / falling keyframes may move above or below `support_y`
- `is_handoff_pose` may only appear on act-boundary keyframes
- handoff poses must be grounded
- handoff poses keep `character_y` near `support_y` within `HANDOFF_SUPPORT_Y_TOLERANCE_PX`
- handoff poses keep `character_x` near `handoff_character_x` within `HANDOFF_X_TOLERANCE_PX`
- `time_ms` non-negative, strictly increasing per clip
- `part_notes.target_id` must match a real Linai SVG id from the canonical template
- each `part_notes.target_id` appears at most once per keyframe
- `duration_ms` > 0 and ≤ `MAX_EPISODE_DURATION_SECONDS * 1000`
- Each clip references a real `act_index`
- Each clip has at least 2 keyframes
- `approach` clips use `choice_index = None`
- `win` / `fail` clips use a valid choice index for that act
- Each act: exactly one approach clip
- Every act after the first starts with a handoff pose in its approach clip
- For one-act parallel Animator calls, `requires_handoff_in` / `requires_handoff_out`
  are the explicit source of truth for whether the current act slice must start or end on
  a handoff pose
- Every handoff pose uses one canonical `handoff_character_x` so separately generated acts
  join without horizontal snapping
- Each winning choice index: exactly one win clip and no fail clip
- Each losing choice index: exactly one fail clip and no win clip
- Every non-final act ends each resolution clip on a handoff pose
- `obstacle_x` within `[50, canvas_width - 50]`

### 6.35 Drawing agent

```python
class DrawingInput(BaseModel):
    job_id: str
    session_id: str
    obstacle_type: str           # slug — also used for naming background assets
    drawing_prompt: str          # Director-authored rich SVG prompt
    drawing_type: Literal["obstacle", "background"] = "obstacle"

class DrawingOutput(BaseModel):
    svg: str                     # complete standalone SVG string
```

Drawing agent behavior:
- System prompts are embedded in the agent code (no external `prompt.txt`).
- `drawing_type="obstacle"` selects the obstacle system prompt; `"background"` selects
  the background system prompt.
- The agent receives the Director's `drawing_prompt` directly — it does not invent prompts.
- Obstacle SVGs must include IDs: `obstacle-root`, `obstacle-main`, `obstacle-animated-part`.
- Background SVGs must include IDs: `background-root`, `background-main`,
  `background-animated-part`.

### 6.4 Renderer agent

```python
class RendererInput(BaseModel):
    job_id: str
    session_id: str
    clips: list[ClipManifest]
    character_template_id: str = "linai-v1"  # selects which character template is active

class SvgClip(BaseModel):
    act_index: int
    branch: Literal["approach", "win", "fail"]
    choice_index: int | None
    svg: str                     # complete inline SVG — no external URLs, no data: URIs
    duration_ms: int             # must match ClipManifest.duration_ms

class RendererOutput(BaseModel):
    clips: list[SvgClip]
```

Renderer behavior:
- The orchestrator resolves obstacle SVGs and background SVGs before the Renderer runs.
- When the obstacle slug matches a bundled library file, the orchestrator injects that SVG.
- When the obstacle slug is unknown, the orchestrator calls DrawingAgent with
  `drawing_type="obstacle"` and injects the generated SVG as `obstacle_svg_override`.
- Background SVGs are generated per act by the DrawingAgent with `drawing_type="background"`
  using the Director's `background_drawing_prompt`. The orchestrator injects the result as
  `background_svg` on each matching clip.
- To keep prompts compact, the Renderer input may carry sentinel markers instead of full
  obstacle/background markup in the model prompt.
- After the model returns, a deterministic scene-composition step re-inserts the exact approved
  obstacle and background SVG layers before final SVG validation and storage.
- The Renderer stage does not do file I/O for obstacle/background assets.
- The Renderer does not invent geometric fallback obstacles anymore; DrawingAgent owns
  unknown-obstacle generation.

**SvgLinter contract — detect and reject (not detect and repair):**

`validate_and_sanitise_svg` is a **detect-and-reject** validator. When any forbidden content is
found, the function returns `(ValidationResult(is_valid=False, errors=[...]), None)`. The
sanitised second return value is `None` whenever `is_valid` is `False`. The orchestrator must
treat `None` as a hard rejection and re-prompt the Renderer with the exact errors list.

The function name `validate_and_sanitise_svg` reflects that the tree is parsed and
structurally cleaned during validation (forbidden tags and attributes are stripped in-place),
but this cleaned version is only returned as the sanitised output when **no** violations were
detected. A partially-cleaned SVG is never returned — the orchestrator always uses the original
Renderer output on retry, not a partially-sanitised version.

**Checks (all must pass for sanitised output to be returned):**
- Parse with `xml.etree.ElementTree` — malformed XML raises `ParseError` (programmer error, not domain failure)
- Strip forbidden tags: `script`, `iframe`, `object`, `embed`, `foreignObject` — append error per tag
- Strip forbidden attributes: any containing `javascript:` or `data:`, and `href`/`src`/`xlink:href` pointing to external URLs — append error per attribute
- `data:` URIs disallowed entirely — no exceptions
- Reject if `len(svg.encode("utf-8")) > MAX_SVG_FILE_SIZE_BYTES`
- Verify `<svg>` root with `viewBox` attribute
- Verify `id="linai"` element present in tree (namespace-agnostic iterator search)
- Clip count must match `RendererInput.clips` count

---

## 7. Thumbnail extraction

**File:** `pipeline/media/thumbnail.py`  
Used by: orchestrator Lambda (at generation time) and reusable future deploy automation in v2.

```python
import xml.etree.ElementTree as ET
from pipeline.validators._xml_utils import _local_name, _find_parent

ANIMATION_TAGS = {"animate", "animateTransform", "animateMotion", "set"}

def extract_thumbnail(approach_svg: str) -> str:
    """
    Strip all animation elements from an approach SVG clip.
    Returns a static first-frame SVG string.
    Raises ValueError if SVG is malformed or missing required elements.
    """
    # ET.fromstring raises ParseError on malformed XML — caller gets a ValueError wrapper
    root = ET.fromstring(approach_svg)
    # Collect all animation nodes first to avoid mutation during iteration
    animation_nodes = [
        el for el in root.iter() if _local_name(el.tag) in ANIMATION_TAGS
    ]
    for node in animation_nodes:
        parent = _find_parent(root, node)
        if parent is not None:
            parent.remove(node)
    # Iterate the tree to find id="linai" — namespace-agnostic and avoids
    # relying on exact attribute serialisation order in ET.tostring output.
    has_linai = any(el.attrib.get("id") == "linai" for el in root.iter())
    if not has_linai:
        raise ValueError('Thumbnail SVG is missing required id="linai" element')
    return ET.tostring(root, encoding="unicode")
```

The orchestrator calls this immediately after SvgLinter passes on the first act's approach clip.
If extraction fails the entire job is marked FAILED — no episode is saved without a thumbnail.

---

## 8. Episode JSON schema

**S3 path (all deployments):** `episodes/{username}/{uuid}/episode.json`
**Schema version:** `"1.0"`

```json
{
  "schemaVersion": "1.0",
  "uuid": "a3f8c2d1-...",
  "username": "somedev",
  "title": "The Dragon Who Wanted to Dance",
  "description": "Linai encounters a surprisingly emotional dragon.",
  "generatedAt": "2026-03-27T10:00:00Z",
  "contentHash": "sha256:abc123...",
  "actCount": 2,
  "acts": [
    {
      "actIndex": 0,
      "obstacleType": "wall",
      "approachText": "Linai drifts toward a wall and studies the top edge for a way over.",
      "clips": {
        "approach": "<svg>...</svg>",
        "choices": [
          {
            "choiceIndex": 0,
            "label": "Knock politely",
            "isWinning": false,
            "outcomeText": "The wall boings back and leaves Linai wobbling.",
            "winClip": null,
            "failClip": "<svg>...</svg>"
          },
          {
            "choiceIndex": 1,
            "label": "Climb over it",
            "isWinning": true,
            "outcomeText": "Linai catches an updraft and glides over the top.",
            "winClip": "<svg>...</svg>",
            "failClip": null
          }
        ]
      }
    }
  ]
}
```

**contentHash computation:**

```python
import hashlib, json

def compute_hash(episode: dict) -> str:
    body = {**episode, "contentHash": None}  # username IS included in hash
    serialised = json.dumps(body, sort_keys=True, ensure_ascii=False)
    return "sha256:" + hashlib.sha256(serialised.encode()).hexdigest()
```

`username` is always present from generation time, so it is included in the hash.
The hash only excludes the `contentHash` field itself.

**Schema rules:**
- `schemaVersion` must match `config.py`. Unknown versions rejected.
- `username` is always populated — never empty string.
- `approachText` stores the Director's pre-choice narrative for that act.
- `outcomeText` stores the Director's narrative for the selected choice result.
- Each act has exactly one winning choice. `winClip` non-null for winner; `failClip` non-null for losers.
- All SVG values are complete inline SVG strings — no URLs.

---

## 9. Gallery index schema

**S3 path:** `episodes/index.json`  
**Regenerated by:** `node scripts/build-index.js` or equivalent repo curation in v1.

```json
[
  {
    "path": "episodes/somedev/a3f8c2d1.json",
    "thumbPath": "episodes/somedev/a3f8c2d1-thumb.svg",
    "username": "somedev",
    "title": "The Dragon Who Wanted to Dance",
    "description": "Linai encounters a surprisingly emotional dragon.",
    "createdAt": "2026-03-27T10:00:00Z"
  }
]
```

`node scripts/build-index.js` scans the repo `episodes/` folder, reads metadata from each
episode JSON, generates the matching thumbnail SVG from the first approach clip, and writes
a fresh `index.json`.

---

## 10. DynamoDB schema

**Table:** `linions-jobs` | **Billing:** PAY_PER_REQUEST | **TTL:** `ttl`

| Attribute | Type | Notes |
|-----------|------|-------|
| `job-id` | String PK | `job-{uuid}` |
| `status` | String | `PENDING` / `GENERATING` / `DONE` / `FAILED` |
| `stage` | String | Current progress label for polling UI |
| `draft-s3-key` | String | Set on DONE: `drafts/{username}/{uuid}/episode.json` |
| `error-message` | String | Set on FAILED |
| `created-at` | String | ISO 8601 |
| `ttl` | Number | Unix timestamp: `createdAt + JOB_TTL_SECONDS` |

Legal state transitions enforced via `ConditionExpression` — see STANDARDS.md §3.4.
`DONE` and `FAILED` are terminal. Any write attempt on terminal state raises and logs ERROR.

---

## 11. Lambda handlers

**3 Lambdas total.** All in LinionsStack. The orchestrator runs all three agents sequentially
in one Lambda — one IAM role, shared AgentCore session in memory. Correct for a 60-second
sequential pipeline. Agent code is cleanly separated into classes regardless of deployment.

### Lambda 1 — linions-generate

```
Trigger:      Function URL POST /  authType: AWS_IAM
Memory:       256 MB | Timeout: 10s
Idempotency:  New jobId per click. AWS retry handled by conditional DynamoDB write.

Flow:
  1. validate prompt and username → 400, no AWS calls on failure
  2. generate jobId
  3. DynamoDB PutItem (condition: not exists)
  4. PENDING → GENERATING (conditional update)
  5. return 200 { jobId }
  6. invoke linions-orchestrator async (InvocationType: Event)

Errors: unexpected → log structured context → 500 safe message
```

### Lambda 2 — linions-orchestrator

```
Trigger:      Async invoke from linions-generate
Memory:       512 MB | Timeout: 120s (= JOB_DEADLINE_SECONDS)
Retries:      AWS auto-retries async invocations up to 2× on unhandled exception
DLQ:          linions-dlq — captures { jobId, prompt, username } after all retries fail
Idempotency:  Checks status = GENERATING before starting. Conditional writes throughout.
Errors:       propagate unhandled exceptions — required for AWS retry + DLQ

Writes to:    drafts/{username}/{uuid}/episode.json, thumb.svg, obstacles/, backgrounds/
              (repo publication happens later outside runtime)
```

### Lambda 3 — linions-status

```
Trigger:      Function URL GET /status/{jobId}  authType: AWS_IAM
Memory:       128 MB | Timeout: 5s
Idempotency:  Read-only.
Response:     { jobId, status, stage, draftS3Key, errorMessage }
Errors:       not found → 404 | unexpected → 500 + structured log
```

---

## 12. Local proxy

**File:** `proxy/server.ts` | **Port:** `3000` | **Runtime:** Node.js 20+

**Startup sequence:**
1. Read GitHub username: try `gh api user --jq .login` first, fall back to
   `git config user.email` (strip domain, use as username). If neither works → exit with
   clear error: "Could not determine GitHub username. Install GitHub CLI or configure git."
2. Validate AWS credentials exist for `AWS_PROFILE` (default: `default`).
3. Start HTTP server on port 3000.

**Routes:**
- `GET /*` → serves the compiled local creator frontend only
- `POST /generate` → adds `username` field to body, computes SigV4, forwards to Lambda 1 URL
- `GET /status/*` → computes SigV4, forwards to Lambda 3 URL
- `GET /drafts/*` → computes SigV4 and reads draft episode artifacts from S3 for local preview/download only
- `GET /episodes/*` → forwards request to the developer's own CloudFront domain (no signing needed — CloudFront is public read for episodes)
- All other routes → 404

**What the proxy must NOT do:**
- Mutate S3, DynamoDB, or any other AWS resource directly
- Expose credentials in response headers or bodies
- Serve the public CloudFront viewer bundle at `localhost:3000`
- Forward requests to any URL other than the configured Lambda Function URLs, CloudFront domain, and local draft S3 object URLs

**First-time setup — auto-generate .env from CDK outputs:**

After running `cdk deploy`, all required values are available as CloudFormation stack
outputs. Run the setup script once to write the `.env` automatically:

```bash
./scripts/setup-env.sh
# reads: aws cloudformation describe-stacks --stack-name LinionsStack
# writes: proxy/.env with all required values
```

**`scripts/setup-env.sh`** reads the following CDK output keys and writes them to `proxy/.env`:

| CDK Output Key | .env Variable |
|----------------|--------------|
| `GenerateFunctionUrl` | `LINIONS_GENERATE_URL` |
| `StatusFunctionUrl` | `LINIONS_STATUS_URL` |
| `CloudFrontDomain` | `CLOUDFRONT_DOMAIN` |
| `EpisodesBucketName` | `EPISODES_BUCKET` |
| `KnowledgeBaseBucketName` | used when running `LINIONS_SYNC_KB=1 bash scripts/setup-env.sh` |

The `.env` file is gitignored and must never be committed.

**`proxy/.env` (generated by setup-env.sh, never manually edited):**
```
AWS_PROFILE=default
LINIONS_GENERATE_URL=https://abc123.lambda-url.eu-west-1.on.aws
LINIONS_STATUS_URL=https://def456.lambda-url.eu-west-1.on.aws
CLOUDFRONT_DOMAIN=https://xyz789.cloudfront.net
EPISODES_BUCKET=linions-episodes-123456789012
```

---

## 13. Character SVG template

**File:** `frontend/public/linai-template.svg`  
**Authored in:** Phase 0 — before any agent or animation development.  
**Author:** Project owner, by hand.

**Phase 1 character: Linai** now uses the v2 ecto-cloud form rather than the old humanoid
body. Future characters (Linoi, Linions kids) will each have their own template file
following the same element ID convention with their own prefix (e.g. `#linoi`,
`#linoi-body` etc.). The architecture and agent contracts are character-agnostic — the
`character_template_id` field in `RendererInput` selects which template is active.

Linai's design is a translucent floating energy creature. Motion reads through cloud
deformation, eye acting, inner patterns, particles, and vapor trails rather than limbs.

Required element IDs for Linai (Renderer agent targets these in generated animation code):

| ID | Description |
|----|-------------|
| `#linai` | Root group for staging the whole character in the scene |
| `#linai-body` | Main ecto-cloud body mass |
| `#linai-eye-left` / `#linai-eye-right` | Eye groups for gaze and squint acting |
| `#linai-mouth` | Mouth group or path for expression changes |
| `#linai-inner-patterns` | Emotion-dependent internal symbols or energy swirls |
| `#linai-particles` | Secondary floating particles inside the cloud |
| `#linai-trails` | Lower vapor trails that flare, droop, stretch, or pool |

The Renderer writes `<animate>` and `<animateTransform>` on these IDs.
It does not create new character geometry, except that the contents of
`#linai-inner-patterns` may be replaced to show emotion-specific symbols.

---

## 14. CDK stack — LinionsStack

One stack. Every developer who clones and deploys gets the complete system.

**Resources:**

| Resource | Config |
|----------|--------|
| `S3Bucket` linions-episodes | `BLOCK_ALL`, `enforceSSL`, `S3_MANAGED` |
| `S3Bucket` linions-kb | Knowledge base source documents |
| `BucketDeployment` | Uploads the compiled public viewer bundle to linions-episodes root on `cdk deploy` |
| `CfnKnowledgeBase` | Bedrock KB referencing linions-kb |
| `DynamoDBTable` linions-jobs | `PAY_PER_REQUEST`, TTL on `ttl` |
| `SqsQueue` linions-dlq | 14-day retention, DLQ for orchestrator |
| `LambdaFunction` linions-generate | 256 MB, 10s, Python 3.11 |
| `LambdaFunction` linions-orchestrator | 512 MB, 120s, Python 3.11, `onFailure: linions-dlq`, writes to `drafts/` only |
| `LambdaFunction` linions-status | 128 MB, 5s, Python 3.11 |
| `LambdaFunctionUrl` (generate, status) | `authType: AWS_IAM` |
| `CloudFrontDistribution` | OAC origin on linions-episodes, `TLS_V1_2_2021`, serves public viewer only |
| `ResponseHeadersPolicy` | SEC-11 security headers |

**IAM roles:**

| Lambda | Permissions |
|--------|-------------|
| linions-generate | DynamoDB PutItem + UpdateItem on linions-jobs; Lambda InvokeFunction on linions-orchestrator |
| linions-orchestrator | Bedrock InvokeModel; AgentCore session ops; Bedrock KB RetrieveAndGenerate; DynamoDB UpdateItem + GetItem on linions-jobs; S3 PutObject + DeleteObject on linions-episodes `drafts/` prefix only |
| linions-status | DynamoDB GetItem on linions-jobs only |

**CloudFront cache behaviour:**
- `episodes/*` and `episodes/index.json` → TTL 24 hours
- Public viewer frontend assets (`*.js`, `*.css`) → TTL 7 days
- `index.html` → TTL 0 (always fresh so viewers get the latest public site)

---

## 15. RAG knowledge base

Source documents in `knowledge-base/`. Authored in Phase 0. Synced to linions-kb S3 during
`cdk deploy`. Bedrock Knowledge Bases handles chunking and embedding automatically.

**`characters/linai/`** (27 docs, 4–6 sentences each)
Linai's character overview, personality, emotional range, expressive sounds, visual vocabulary,
world-builder awareness, per-obstacle reaction patterns (7 docs), and emotional situation
patterns (14 docs).
Example filenames: `linai-character-overview.md`, `obstacle-wall.md`, `situation-small-victory.md`, `no-spoken-words.md`

**`shared/`** (19 docs)
World rules, narrative structure, pacing, tone, and episode design patterns that apply to
any Linions character. Example filenames: `episode-world.md`, `arc-setup-obstacle-resolution.md`,
`pacing-clip-duration.md`

**Director agent RAG query strategy (two queries per generation):**

```python
# Query 1: obstacle and situation-specific behavior
kb_result_1 = bedrock_kb.retrieve(query=input.prompt, max_results=5)

# Query 2: tone and style rules
dominant_tone = extract_dominant_tone(input.prompt)  # e.g. "excited", "curious", "worried"
kb_result_2 = bedrock_kb.retrieve(query=dominant_tone, max_results=3)

rag_context = format_context(kb_result_1, kb_result_2)
```

---

## 16. Prompt templates

**Location:** `pipeline/agents/{director|animator|renderer}/prompt.txt`  
Plain text with `{variable}` placeholders.

Each file header documents:
- Agent name and version
- All `{variable}` placeholders and their types
- Exact JSON output format expected (inline schema)
- Last-updated date

Each agent's `_build_prompt()` method substitutes variables from typed input.
No f-string concatenation in agent business logic.

Changing output shape requires: Pydantic model update → validator update →
`tests/fixtures/valid_episode.json` update → `schemaVersion` bump if episode JSON changes.

---

## 17. Deferred v2 workflow

Community contributions, PR validation, canonical owner-gallery sync, and any contribution
helper script are deferred to v2. See:

- `docs/versions/v2/community-contributions-and-canonical-gallery.md`
