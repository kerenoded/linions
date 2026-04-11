<!-- AI ASSISTANT: Read in this order before writing any code:
  1. REQUIREMENTS.md
  2. STANDARDS.md  
  3. DESIGN.md
  4. PHASES.md
  Then confirm which phase you are implementing before starting. -->

# Phases — Linions

> Version 1.2 | Status: approved
>
> This document defines what to build, in what order, and what "done" means for each phase.
> No phase begins until the previous phase gate passes. No phase is done until its gate passes.
>
> At the start of every AI coding session, tell the assistant:
> "Read REQUIREMENTS.md, STANDARDS.md, DESIGN.md, and PHASES.md before writing any code.
>  We are implementing Phase N only. Do not touch anything outside Phase N scope."

---

## How to use this document

Each phase has:
- **Scope** — exactly what gets built. Nothing outside this list.
- **Deliverables** — files and artifacts that must exist when the phase is done.
- **Gate** — what you must manually verify before moving to the next phase.

All phases assume STANDARDS.md rules apply in full. The definition of done in STANDARDS.md §9
must be satisfied at the end of every phase.

---

## Phase 0 — Foundation (design work, no code)


**Who:** Project owner only. No AI coding assistant for this phase.

### Scope

This phase is entirely design and authoring work. It produces the two assets that every
subsequent phase depends on: the character SVG template and the RAG knowledge base documents.
Getting these right saves significant debugging time in later phases.

### Deliverables

**1. Linai character SVG template**

File: `frontend/public/linai-template.svg`

Hand-draw Linai as a simple expressive ecto-cloud character in any vector tool (Inkscape,
Figma, or directly in SVG). She should feel alive and readable, not like a geometric
placeholder. Simple is better. The Renderer agent will animate her using SVG animation on
known element IDs, so the structure matters more than visual complexity.

Required element IDs — every one of these must be present and correctly named:
- `#linai` — root `<g>` group for the whole character
- `#linai-body` — main cloud body mass
- `#linai-eye-left`, `#linai-eye-right` — eye groups
- `#linai-mouth` — mouth group or path
- `#linai-inner-patterns` — emotion-dependent internal patterns
- `#linai-particles` — floating particle group
- `#linai-trails` — lower vapor trails

The invisible floor is at `y=160`. Linai should hover with her lower cloud mass and trails
reading against that support line rather than standing on feet.
The canvas `viewBox` should be `0 0 800 200`. No visible ground line is drawn.

Test: open the SVG in a browser — Linai should be visible, hovering against the line,
with all required IDs present (verify with browser DevTools).

**2. RAG knowledge base documents**

Folder: `knowledge-base/`

Write approximately 40–50 short plain-text or markdown documents across three categories.
Each document should be 3–8 sentences. Write them in the voice of a character bible —
specific, behavioural, not generic.

`characters/linai/` (27 documents):
- `linai-character-overview.md` — who she is, her personality, how she moves and sounds
- One doc per obstacle type (7 total): `obstacle-wall.md`, `obstacle-hole.md`,
  `obstacle-tree.md`, `obstacle-puddle.md`, `obstacle-elevated-platform.md`,
  `obstacle-bird.md`, `obstacle-second-character.md`
- 14 emotional situation docs: `situation-being-chased.md`, `situation-confusion.md`,
  `situation-small-victory.md`, `situation-dramatic-failure.md`,
  `situation-fourth-wall-frustration.md`, `situation-delight.md`,
  `situation-encountering-beauty.md`, `situation-surprise.md`,
  `situation-creative-problem-solving.md`, `situation-waiting.md`,
  `situation-being-watched.md`, `situation-examining-object.md`,
  `situation-tiredness.md`, `situation-end-of-episode.md`
- 5 Linai-specific style docs: `no-spoken-words.md`, `emotional-range.md`,
  `visual-vocabulary.md`, `world-builder-awareness.md`, `linai-never-gives-up.md`

`shared/` (19 documents):
- Narrative arcs: `arc-setup-obstacle-resolution.md`, `structure-multi-act-escalation.md`
- Comedy beats: `beat-wrong-choice-comedy.md`, `beat-surprise-win.md`
- Pacing: `pacing-approach-walk.md`, `pacing-obstacle-tension.md`,
  `pacing-resolution-satisfaction.md`, `pacing-clip-duration.md`
- Episode structure: `structure-branching-choices.md`, `structure-choice-labelling.md`,
  `structure-retry-loop.md`, `structure-prompt-to-episode.md`
- Tone: `tone-warm-ending.md`, `tone-comedy-without-cruelty.md`, `tone-all-ages.md`
- World rules: `episode-world.md`, `scale-is-comic.md`, `obstacles-are-absurd.md`
- Technical: `animation-style-constraints.md`

Test: read all documents as a set — does it feel like a coherent character bible?
Would someone reading only these documents be able to generate a consistent Linai episode?

**3. Repository skeleton**

Create the full folder structure defined in DESIGN.md §1 with:
- All folders created (even if empty)
- `README.md` with project name, brief description, legal notice, and getting-started
  instructions (deploy CDK, run setup-env.sh, run proxy)
- `.gitignore` per STANDARDS.md §8.4
- `pyproject.toml` with ruff config
- `.eslintrc.json` with TypeScript plugin config
- `episodes/index.json` as an empty array `[]`
- `pipeline/config.py` with all values from STANDARDS.md §2.4
- `infra/config.ts` with CDK-side config values

**4. Episode JSON schema fixture**

File: `tests/fixtures/valid_episode.json`

Write one canonical valid episode JSON by hand, following the schema in DESIGN.md §8
exactly. This is the ground truth used by all tests. Include 2 acts, 2 choices each,
realistic SVG placeholders (a minimal `<svg viewBox="0 0 800 200"><g id="linai"/></svg>`),
real title and description, computed contentHash.

Also create at minimum these invalid fixtures in `tests/fixtures/invalid/`:
- `missing-uuid.json`
- `empty-username.json`
- `act-count-exceeds-maximum.json`
- `missing-winning-choice.json`
- `svg-with-script-tag.json`
- `svg-with-external-url.json`
- `invalid-schema-version.json`

### Gate ✓

- [ ] `linai-template.svg` opens in browser, Linai is visible, all required IDs present in DevTools
- [ ] All 7 obstacle documents exist in `knowledge-base/characters/linai/` and are substantive (not placeholder text)
- [ ] `knowledge-base/shared/` and `knowledge-base/characters/linai/` together cover personality, world rules, and narrative structure
- [ ] `pipeline/config.py` contains all values from STANDARDS.md §2.4, every value has a comment
- [ ] `tests/fixtures/valid_episode.json` is valid against the schema defined in DESIGN.md §8
- [ ] All 7 invalid fixtures exist
- [ ] `episodes/index.json` exists as `[]`
- [ ] `ruff check pipeline/` exits clean
- [ ] `eslint infra/` exits clean

---

## Phase 1 — Validators and models (pure Python, no AWS)



### Scope

All Pydantic models, all three validators, the SVG linter, and the thumbnail utility.
Pure Python. No AWS, no Bedrock, no Lambda. Everything in this phase is testable offline.

### Deliverables

- `pipeline/models.py` — all Pydantic v2 models from DESIGN.md §6:
  open obstacle slug fields, `ExpressionState`, `ActionType`, `Choice`, `Act`,
  `DirectorInput`, `DirectorOutput`, `AnimatorInput`, `Keyframe`, `ClipManifest`,
  `AnimatorOutput`, `RendererInput`, `SvgClip`, `RendererOutput`,
  `ValidationResult` dataclass, episode JSON schema model
- `pipeline/validators/script_validator.py` — pure function, all rules from DESIGN.md §6.2
- `pipeline/validators/frame_validator.py` — pure function, all rules from DESIGN.md §6.3
- `pipeline/validators/svg_linter.py` — pure function, all rules from DESIGN.md §6.4
- `pipeline/media/thumbnail.py` — `extract_thumbnail()` per DESIGN.md §7
- `tests/unit/test_script_validator.py` — 100% coverage, every rule tested passing and failing
- `tests/unit/test_frame_validator.py` — 100% coverage
- `tests/unit/test_svg_linter.py` — 100% coverage
- `tests/unit/test_thumbnail.py` — with animations, without animations, malformed XML
- `tests/unit/test_models.py` — all Pydantic models: required fields, optional fields, type constraints

### Implementation notes for AI assistant

- Validators are pure stateless functions. No classes. No side effects. See STANDARDS.md §3.2.
- `ValidationResult` is a `@dataclass`, not a Pydantic model.
- `validate_script`, `validate_frames`, `validate_and_sanitise_svg` are the primary entry points.
- All validator functions must return `ValidationResult` for domain failures and raise for
  programmer errors (e.g. `None` input). See STANDARDS.md §3.2.
- `extract_thumbnail` uses `xml.etree.ElementTree` only — no external XML libraries.
- Tests must mock nothing — these are pure functions with no dependencies.
- Use `tests/fixtures/valid_episode.json` and `tests/fixtures/invalid/` for test inputs.

### Gate ✓

- [ ] `pytest tests/unit/ -v` exits 0
- [ ] `pytest --cov=pipeline --cov-report=term-missing tests/unit/` shows 100% on all validators and thumbnail.py
- [ ] Every validator rule from DESIGN.md §6 has a corresponding failing test case
- [ ] `ruff check pipeline/` exits clean
- [ ] No AWS SDK imported anywhere in this phase

---

## Phase 2 — CDK infrastructure (no agents yet)



### Scope

The complete `LinionsStack` CDK stack. All AWS resources defined, synthesizable, and
deployable. No agent code runs in this phase — Lambdas are stubbed with placeholder
handlers that return `{"statusCode": 200}`. The goal is to have a working AWS environment
that subsequent phases deploy into.

### Deliverables

- `infra/lib/linions-stack.ts` — complete `LinionsStack` with all resources from DESIGN.md §14:
  - `S3Bucket` linions-episodes (BLOCK_ALL, enforceSSL, S3_MANAGED)
  - `S3Bucket` linions-kb (knowledge base source documents)
  - `BucketDeployment` — uploads the public viewer bundle (`frontend/dist-public/`) and `episodes/index.json`
  - `CfnKnowledgeBase` — Bedrock Knowledge Base referencing linions-kb
    **Decision: deferred to Phase 4.** `CfnKnowledgeBase` requires Bedrock vector store
    resources that are not needed until the Director agent runs. The `linions-kb` S3 bucket
    and IAM role ARE created in Phase 2. The `CfnKnowledgeBase` construct and its data source
    are wired in Phase 4 alongside the agent code that queries it. This is an explicit scope
    decision, not a gap. The Phase 2 gate passes without `CfnKnowledgeBase` in the stack.
  - `DynamoDBTable` linions-jobs (PAY_PER_REQUEST, TTL on `ttl`)
  - `SqsQueue` linions-dlq (14-day retention)
  - 3 `LambdaFunction` resources (stubbed handlers) with correct memory/timeout/description
  - 2 `LambdaFunctionUrl` resources (generate, status — authType: AWS_IAM)
  - `CloudFrontDistribution` with OAC origin, TLS_V1_2_2021, cache behaviours from DESIGN.md §14
  - `ResponseHeadersPolicy` with SEC-11 headers
  - All CDK stack outputs: `GenerateFunctionUrl`, `StatusFunctionUrl`, `CloudFrontDomain`,
    `EpisodesBucketName`
  - All IAM roles scoped exactly as in DESIGN.md §14 — no `*` resources
- `infra/bin/app.ts` — CDK app entry point instantiating `LinionsStack`
- `scripts/setup-env.sh` — reads CDK outputs, writes `proxy/.env`
- `tests/cdk/test_linions_stack.py` — CDK assertion tests for security-critical properties:
  - S3 `blockPublicAccess` is `BLOCK_ALL`
  - Lambda Function URLs have `authType: AWS_IAM`
  - No IAM policy has `*` as resource
  - CloudFront has `minimumProtocolVersion: TLS_V1_2_2021`
  - DynamoDB has TTL configured
  - SQS DLQ is attached to orchestrator Lambda

### Implementation notes for AI assistant

- Use CDK v2. Import from `aws-cdk-lib`, not individual `@aws-cdk/*` packages.
- All CDK construct IDs must be descriptive PascalCase strings.
- Use `Stack.of(this).account` and `Stack.of(this).region` — never hardcode.
- Stub Lambda handlers are inline Python strings in the CDK code — not separate files yet.
  Example: `code: lambda_.Code.fromInline("def handler(event, context): return {'statusCode': 200}")`
- The Bedrock Knowledge Base (`CfnKnowledgeBase`) requires a Bedrock-supported embedding model.
  Use `amazon.titan-embed-text-v1` as the embedding model ARN.
- Knowledge base source documents are synced to `linions-kb` bucket using `BucketDeployment`
  from `knowledge-base/` folder.
- `setup-env.sh` uses `aws cloudformation describe-stacks --stack-name LinionsStack` and `jq`
  to extract outputs and write the `.env` file.

### Gate ✓

- [ ] `cdk synth` exits clean with no errors or warnings
- [ ] `pytest tests/cdk/ -v` exits 0 — all security properties asserted
- [ ] `cdk deploy` succeeds in a real AWS account
- [ ] `scripts/setup-env.sh` runs successfully and produces a valid `proxy/.env`
- [ ] CloudFront URL is reachable in a browser (serves placeholder index.html)
- [ ] Lambda Function URLs return 403 when called without SigV4 signature
- [ ] No hardcoded account IDs, ARNs, or region strings in CDK code
- [ ] `eslint infra/` exits clean

---

## Phase 3 — Split frontend shell: local creator + public viewer

### Scope

The local proxy server plus two browser shells:
- a localhost creator UI for generating and previewing drafts
- a separate CloudFront public viewer shell for gallery + episode playback

No agents yet — the creator UI still calls the stubbed Lambda which returns a fake
`jobId`. The goal is to establish the product split early so CloudFront never ships the
same site as `localhost:3000`.

### Deliverables

- `proxy/server.ts` — complete proxy per DESIGN.md §12:
  - Startup: reads GitHub username via `gh api user --jq .login` (fallback: git config)
  - Startup: validates AWS credentials exist for `AWS_PROFILE`
  - Startup: exits with clear error if either fails
  - Routes: `GET /*` serves the local creator build only, `POST /generate`, `GET /status/*`,
    `GET /episodes/*` forwards to CloudFront domain
  - SigV4 signing for Lambda routes using `@aws-sdk/signature-v4`
  - Logs every proxied request: method, path, status, duration ms
- `frontend/src/types.ts` — all TypeScript types mirroring `pipeline/models.py`
- `frontend/src/generator.ts` — localhost creator flow: prompt input form, polling loop,
  and creator-state UI
- `frontend/src/player.ts` — shared episode player: loads JSON, plays clips, handles choices,
  win/fail/retry flow, and Download/export action for locally generated drafts
- `frontend/src/gallery.ts` — fetches `episodes/index.json` from CloudFront,
  renders public episode cards with thumbnail, title, username, description
- `frontend/src/viewer.ts` — public viewer routing between gallery home and direct story page
- `frontend/src/main.ts` — bootstraps either creator or viewer mode
- `frontend/public/studio.html` — localhost creator shell
- `frontend/public/index.html` — public CloudFront viewer shell
- `tests/unit/test_frontend_state_machine.ts` — all `PlayerState` transitions and error paths

### Implementation notes for AI assistant

- The `PlayerState` union type is defined in STANDARDS.md §3.9 — implement it exactly.
- The player renders episode SVG inside `<iframe sandbox>` — never `innerHTML`.
- All episode metadata is rendered with `textContent` — never `innerHTML`. See SEC-04.
- Treat the creator UI and public viewer as distinct surfaces, not one page with controls
  hidden conditionally. The CloudFront build must not contain the add-story form.
- The public viewer fetches `{CLOUDFRONT_DOMAIN}/episodes/index.json`. The domain is
  injected at build time from an environment variable — not hardcoded.
- The proxy reads Lambda Function URLs from `.env` written by `setup-env.sh`.
  It must not start if `.env` is missing — print a clear message directing the developer
  to run `scripts/setup-env.sh` first.
- For this phase, the generate endpoint returns a fake `jobId` and the status endpoint
  returns a fake `DONE` response after a few polls. This lets the frontend flow be
  tested without real agents.
- The public viewer should already reserve a dedicated direct story route shape:
  `/story/{username}/{uuid}`.
- Responsive breakpoints: single-column gallery below 600px, SVG `width: 100%; height: auto`.

### Gate ✓

- [ ] `npm run dev` starts proxy without errors (with valid `.env`)
- [ ] Opening `localhost:3000` shows the localhost creator UI, not the public gallery
- [ ] Typing a prompt and clicking Generate shows the progress indicator cycling through all 5 stages
- [ ] After fake DONE, the episode player renders (with placeholder SVG)
- [ ] Creator-only download/export action appears correctly in localhost
- [ ] CloudFront root shows the public gallery shell and does not expose add-story controls
- [ ] Gallery loads `episodes/index.json` from CloudFront and renders cards
- [ ] Clicking a gallery card opens the public player and plays the episode
- [ ] Direct route `/story/{username}/{uuid}` opens the public player page without creator controls
- [ ] Layout is usable on a 375px wide mobile viewport
- [ ] `eslint frontend/` exits clean
- [ ] All frontend state machine transitions tested and passing

---

## Phase 4 — Director agent and script validator (end-to-end first agent)



### Scope

The Director agent, its prompt template, and the full orchestrator skeleton wired to
Lambda. At the end of this phase, typing a prompt generates a real validated story script
via Bedrock + AgentCore + RAG. The Animator and Renderer are not built yet — the
orchestrator stops after Director succeeds and returns the script JSON for inspection.

This is the hardest phase because it involves the most prompt engineering. Budget the
second day entirely for prompt tuning.

### Deliverables

- `pipeline/agents/director/agent.py` — `DirectorAgent` class per DESIGN.md §6.2
- `pipeline/agents/director/prompt.txt` — Director prompt template with header documentation
- `pipeline/orchestrator.py` — orchestrator skeleton:
  - Creates AgentCore session
  - Calls RAG KB twice (obstacle query + tone query)
  - Calls `DirectorAgent.run()`
  - Calls `ScriptValidator.validate()`
  - Retry loop up to `MAX_AGENT_RETRY_COUNT`
  - Updates DynamoDB stage labels at each step
  - On Phase 4 only: stops after Director, writes script JSON to DynamoDB for inspection,
    marks job DONE (temporary — will be extended in Phase 5)
- `pipeline/lambda_handlers.py` — real implementations of `handle_generate` and
  `handle_status` replacing CDK stubs
- `pipeline/job_store.py` — DynamoDB read/write with all state transitions from DESIGN.md §10
- `tests/unit/test_director_agent.py` — mocked Bedrock calls, tests prompt construction,
  tests that bad model output triggers retry
- `tests/unit/test_orchestrator_director.py` — mocked Director + validator, tests retry
  loop, budget ceiling, FAILED state transition

### Implementation notes for AI assistant

- AgentCore session is created in `orchestrator.py` and passed as `session_id` into
  `DirectorInput`. The Director agent uses this session for context management.
- RAG queries use `bedrock-agent-runtime` client's `retrieve()` method.
  The Knowledge Base ID comes from an environment variable set in the CDK stack.
- The Director prompt must include:
  - The system prompt instructing family-friendly, Linai-consistent output
  - The RAG context (`{rag_context}` placeholder)
  - The user prompt (`{prompt}`)
  - The required JSON output format inline (copy the schema from DESIGN.md §6.2)
- Instruct the model to return ONLY valid JSON with no preamble, no markdown fences.
- The retry prompt must include the original prompt AND the exact validation errors.
- `job_store.py` must use `ConditionExpression` on every state transition. See DESIGN.md §10.
- `handle_generate` receives `{ prompt, username }` — username is injected by proxy.
- Cost guardrail: check token counts from Bedrock response metadata. If
  `output_tokens >` the stage-specific `MAX_OUTPUT_TOKENS_*_STAGE` ceiling, mark job FAILED immediately.

### Gate ✓

- [ ] Run 10 different prompts through the full flow — all produce schema-valid `DirectorOutput`
- [ ] Run 3 prompts in non-English — all produce valid output
- [ ] Manually inject a validator failure — confirm retry happens and error is in the re-prompt
- [ ] After 2 forced failures, job transitions to FAILED state in DynamoDB
- [ ] DynamoDB stage labels update correctly (visible in AWS Console during generation)
- [ ] CloudWatch logs show structured JSON entries for each agent call
- [ ] `pytest tests/unit/ -v` exits 0 (all phases 1–4 tests pass)
- [ ] No raw dicts passed between orchestrator and agent — only typed Pydantic models

---

## Phase 5 — Animator agent, Drawing agent, and Renderer agent



### Scope

The Animator, Drawing, and Renderer agents, their prompt templates, and the complete
orchestrator pipeline. At the end of this phase, a prompt generates a complete episode
JSON with real SVG animation clips (including newly drawn obstacles), saved to `drafts/`
in S3. The thumbnail is extracted and saved. This is the core creative output of the
entire project.

Day 1: Animator agent + frame validator integration.
Day 2: Drawing agent + obstacle library lookup logic.
Day 3: Renderer agent + SVG linter integration + thumbnail + S3 writes.

See `docs/plans/dynamic-obstacle-types.md` for the full Drawing agent architecture and prompt.

### Deliverables

- `pipeline/agents/animator/agent.py` — `AnimatorAgent` per DESIGN.md §6.3
- `pipeline/agents/animator/prompt.txt`
- `pipeline/agents/drawing/agent.py` — `DrawingAgent` — draws obstacle and background SVGs
  (system prompts embedded in agent code, no external prompt.txt)
- `pipeline/agents/renderer/agent.py` — `RendererAgent` per DESIGN.md §6.4
- `pipeline/agents/renderer/prompt.txt`
- `scripts/run-renderer-agent.py` — local Renderer debug runner for laptop testing
- `pipeline/media/obstacle_library.py` — `get_obstacle_svg()`, `list_library_names()`
- `pipeline/lambdas/orchestrator/pipeline_orchestrator.py` — complete pipeline:
  - All 5 DynamoDB stage updates
  - Director → ScriptValidator → Animator → FrameValidator → Drawing (obstacles + backgrounds) → Renderer → SvgLinter
  - Cost guardrail enforcement at each stage
  - Episode JSON assembly with contentHash computation
  - Thumbnail extraction via `thumbnail.py`
  - S3 writes: episode JSON then thumbnail (with cleanup on thumbnail failure)
  - DynamoDB: DONE + draftS3Key
- `pipeline/storage/episode_store.py` — S3 PutObject, DeleteObject, GetObject (drafts/ prefix only)
- `tests/unit/test_animator_agent.py` — mocked Bedrock, tests keyframe structure
- `tests/unit/test_drawing_agent.py` — mocked Bedrock, tests required IDs present, SVG valid
- `tests/unit/test_obstacle_library.py` — known slug returns SVG, unknown returns None
- `tests/unit/test_renderer_agent.py` — mocked Bedrock, tests SVG structure
- `tests/unit/test_orchestrator_pipeline.py` — full pipeline with all agents mocked,
  tests happy path, retry at each stage, budget ceiling, S3 write sequence,
  drawing agent called for unknown obstacle, library hit skips obstacle drawing,
  background drawing agent called for every act

### Obstacle idle animation (applied by the frontend, not the Renderer)

The `obstacle-animated-part` element in every obstacle SVG — pre-authored or drawn — is
animated by the frontend player with this CSS. The Renderer does not embed this animation;
it is applied globally by the player stylesheet:

```css
@keyframes idle {
  0%, 100% { transform: rotate(-4deg); }
  50%       { transform: rotate(4deg); }
}
#obstacle-animated-part {
  animation: idle 2s ease-in-out infinite;
  transform-box: fill-box;
  transform-origin: center bottom;
}
```

Design the `obstacle-animated-part` knowing it will sway ±4° around its bottom center.
Good candidates: branches, flames, tails, flags, antennae, wands, fins, feathers.
Bad candidates: the entire body, rigid objects with no natural pivot.

### Drawing agent prompts

The Drawing agent no longer uses an external `prompt.txt` file. System prompts are embedded
directly in `pipeline/agents/drawing/agent.py` as class constants:

- `_OBSTACLE_SYSTEM_PROMPT` — for `drawing_type="obstacle"`: specifies required IDs
  (`obstacle-root`, `obstacle-main`, `obstacle-animated-part`), viewBox, style, and output rules.
- `_BACKGROUND_SYSTEM_PROMPT` — for `drawing_type="background"`: specifies required IDs
  (`background-root`, `background-main`, `background-animated-part`), viewBox `0 0 800 200`,
  and output rules.

The Drawing agent receives its `drawing_prompt` from the Director output — it does not invent
prompts. The Director's `drawing_prompt` (for non-library obstacles) and
`background_drawing_prompt` (for every act) are rich, Director-authored descriptions that
include visual details, layering order, ID assignments, and animation direction.

### Implementation notes for AI assistant

- The Drawing agent is called by the orchestrator for two purposes:
  1. Obstacle SVGs: once per unique `obstacle_type` not found in the library. If three acts
     all use `"dragon"`, draw once and reuse. Cache by slug within the orchestrator run.
  2. Background SVGs: once per act, using the Director's `background_drawing_prompt`.
     Injected into matching clips as `background_svg` before the Renderer runs.
- The orchestrator should batch missing obstacle SVGs and per-act background SVGs into one
  bounded parallel Drawing stage using at most `MAX_PARALLEL_DRAWING_TASKS` workers.
- If one Drawing task fails validation or invocation, retry only that obstacle/background
  identity instead of re-running the entire Drawing batch.
- `obstacle_type` is an open slug string in Phase 5, not a closed enum. Use exact library
  names when they fit, otherwise invent a specific slug and let the Drawing agent handle it.
- The Director generates `drawing_prompt` for non-library obstacles and
  `background_drawing_prompt` for every act. The Drawing agent receives these prompts
  directly via `DrawingInput.drawing_prompt`.
- The Drawing agent returns `DrawingOutput(svg: str)`. Run the `svg` value through `SvgLinter`
  immediately after generation — treat a linter failure as a validation failure and retry
  with the exact errors (same retry logic as other agents, up to `MAX_AGENT_RETRY_COUNT`).
- Use different required/animated IDs for validation depending on `drawing_type`:
  obstacle → `obstacle-root/main/animated-part`, background → `background-root/main/animated-part`.
- The Animator prompt must include the canvas dimensions from config, the ground line Y,
  the full `Act` list from Director output, and the real targetable Linai SVG ids from the
  canonical template. It must output `AnimatorOutput` JSON only, with open creative
  `action`/`expression` text plus optional `motion_note`, `support_y`, `is_grounded`,
  `is_handoff_pose`, and per-part notes.
- Animator clips should follow the Director choice truth exactly: one `win` clip for the
  single winning choice in an act and one `fail` clip for each losing choice.
- Animator should use a standard grounded handoff pose at act boundaries so non-final acts
  end in a clean continuation state and later acts start from one.
- Grounded expressive poses may drift slightly around `support_y`, but handoff poses should
  stay more tightly anchored so separately generated acts stitch without a vertical pop.
- Because Animator now runs one act at a time in parallel, each one-act `AnimatorInput`
  should carry explicit `requires_handoff_in` / `requires_handoff_out` booleans plus one
  canonical `handoff_character_x` so the prompt can tell Bedrock exactly whether that act
  slice must start or end on a handoff pose and where that pose must land horizontally.
- The orchestrator should split the validated Director acts into one-act Animator inputs and
  run those Bedrock calls in parallel. Validate and retry failed acts independently, then
  merge the successful per-act manifests back into one `AnimatorOutput`.
- The Renderer prompt must:
  - Reference Linai's element IDs (`#linai`, `#linai-body`, etc.) explicitly
  - Explain what `<animate>` and `<animateTransform>` do and how to use them
  - Give a small working SVG animation example in the prompt for reference
  - Specify `viewBox="0 0 800 200"` and ground line at y=160
  - Treat obstacle/background layers as system-composed assets; the prompt may use compact
    sentinel markers instead of inlining the full SVG payloads
  - Request one complete SVG string per clip, no markdown, no explanation
- After the Renderer returns, the orchestrator should deterministically re-compose the exact
  approved obstacle/background layers into the scene before final SVG validation.
- After `SvgLinter.validate_and_sanitise()` returns sanitised SVG, the orchestrator uses
  the sanitised version — not the raw Renderer output.
- The contentHash computation: see DESIGN.md §8. Set `contentHash` to `null`, serialise
  with `json.dumps(body, sort_keys=True, ensure_ascii=False)`, SHA-256, then set the field.
- S3 write sequence: episode JSON first. If thumbnail extraction raises → delete episode
  JSON → mark FAILED. See STANDARDS.md §3.3.
- The `episode_store.py` `put_draft()` method must use `ConditionExpression: attribute_not_exists(key)`
  to prevent overwriting an existing draft.

### Gate ✓

- [ ] 5 different prompts produce complete episode JSONs in `drafts/` in S3
- [ ] Every episode JSON passes `ScriptValidator`, `FrameValidator`, and `SvgLinter`
- [ ] Every episode JSON has a valid `contentHash` (re-compute and compare)
- [ ] Every episode has a thumbnail SVG at `drafts/{username}/{uuid}-thumb.svg`
- [ ] Open each episode JSON in the browser player — all clips play, all choices work
- [ ] A prompt that causes Renderer to produce invalid SVG triggers retry and eventual repair
- [ ] CloudWatch logs show all 5 stage labels and structured entries for all 3 agents
- [ ] `pytest tests/unit/ -v` exits 0 — all phases 1–5 tests pass
- [ ] Episode JSON file size is within `MAX_EPISODE_JSON_SIZE_BYTES`

---

## Phase 6 — Local export flow and polished public viewer

### Scope

The real localhost creator UI wired to generation, plus the real CloudFront public viewer
site. At the end of this phase the full v1 journey works end-to-end for the runtime slice:
generate locally → preview draft → download/export artifact. Public release remains
repo-driven and is completed in Phase 7.

This phase also upgrades the public-facing UI quality. The CloudFront site should feel
like a professional story website, not like the localhost tool with a few controls hidden.

### Deliverables

- Real localhost creator UI wired to real Lambda URLs (replacing Phase 3 stubs):
  - Generate calls real `linions-generate` Lambda
  - Status polling calls real `linions-status` Lambda
  - Download/export action fetches the generated draft episode JSON
  - Studio copy explains the repo-driven publication path for v1
  - No Contribute button in v1
- Separate public viewer site deployed to S3/CloudFront:
  - Gallery home page renders real episodes from `episodes/index.json`
  - Episode route `/story/{username}/{uuid}` renders the published episode without creator controls
  - Public site design is polished, appealing, and professional
- The S3-deployed frontend bundle contains only the public viewer site, not the localhost creator UI

### Implementation notes for AI assistant

- v1 intentionally has no publish API and no publish Lambda.
- The Download/export action should save the generated draft artifact so a developer can
  later add it to the repo's `episodes/` folder.
- Build the public viewer and localhost creator as two distinct entry points. Do not deploy
  the creator entry point to S3 and do not rely on runtime feature flags to hide creator controls.
- The public viewer home page should emphasize title + thumbnail cards and feel curated.
  The direct story page should focus on the selected episode and its player with minimal chrome.

### Gate ✓

- [ ] Full runtime flow works: type prompt → generate → preview → download/export artifact
- [ ] Download button downloads the correct generated episode JSON
- [ ] CloudFront home page contains no add-story, generate, publish, or download controls
- [ ] Direct story URL opens a dedicated public episode page with no creator section
- [ ] Public viewer layout works on a smartphone
- [ ] `pytest tests/unit/ -v` exits 0 — all phases 1–6 tests pass

---

## Phase 7 — Seed episodes and public launch prep

### Scope

The three pre-generated seed episodes that ship with the repo plus final polish for the
public viewer launch. Community contributions and CI/CD are no longer part of v1 and move
to `docs/versions/v2/`.

### Deliverables

- `scripts/build-index.js` — scans `episodes/` folder, generates thumbnails, rebuilds `index.json`
- 3 pre-generated seed episodes in `episodes/{owner-username}/` with real SVG content,
  valid schema, correct contentHash
- `episodes/index.json` updated with all 3 seed episodes
- Public viewer content/layout polish pass using those seed episodes as the real launch content

### Implementation notes for AI assistant

- The 3 seed episodes must be real — actually generated by running the pipeline. They are
  the primary demo content for anyone who clones the repo without deploying.
- Use the seed episodes to sanity-check the public gallery layout, card density, thumbnail
  quality, and direct story page composition on desktop and mobile.
- Community contribution workflow, GitHub Actions validation, deploy workflows, and the
  Contribute button are explicitly deferred to v2.

### Gate ✓

- [ ] `scripts/build-index.js` runs cleanly and produces a correct `episodes/index.json` plus matching thumbnail SVG files
- [ ] All 3 seed episodes play correctly in the browser from the public CloudFront URL
- [ ] Public gallery cards look polished and readable on desktop and smartphone
- [ ] Direct story page looks production-ready on desktop and smartphone
- [ ] `pytest tests/unit/ -v` exits 0 — all phases 1–7 tests pass

---

## Phase 8 — Public-launch hardening, showcase README, and documentation

**This is the final phase before the project is published as a public repository.**

### Scope

No new features. The goal is to make the repository look impressive and professional to
anyone who lands on it — a "wow, this is a real project" first impression. This means a
showcase-quality README, clean separation of developer docs from the main pitch, an
architecture diagram, and final quality gates on code, tests, and infrastructure.

---

### Deliverable 1 — Showcase README.md

Rewrite `README.md` from scratch as a public-facing showcase document. The current README
is an internal developer reference — it should become a compelling project page that makes
visitors want to explore the repo.

**Structure and content:**

1. **Hero section**
   - Project name: **Linions**
   - One-line tagline: AI-powered interactive animated stories — generated entirely by AI,
     including all SVG art and animations.
   - Immediately below: a clickable thumbnail image (use `episodes/kerenoded/cee4bcd2-3572-4788-8e94-1a705f4f7ecd/thumb.svg`
     — "Linai and the Cosmos") linking to the live episode at
     `https://linions.odedkeren.dev/story/kerenoded/cee4bcd2-3572-4788-8e94-1a705f4f7ecd`.
     GitHub strips iframes from rendered markdown, so use a markdown image-link:
     `[![Play episode](thumb.svg)](https://linions.odedkeren.dev/story/kerenoded/cee4bcd2-3572-4788-8e94-1a705f4f7ecd)`.
     Add a caption: *"Click to play — runs in any browser, no setup required"*.
   - Link to the full live gallery: `https://linions.odedkeren.dev/`

2. **What is this?**
   - A short (3–5 sentence) paragraph explaining: a developer types a natural language prompt,
     a pipeline of AI agents on AWS generates a short branching animated episode, the viewer
     plays it interactively in a browser with no setup.
   - Emphasize: **this is a pure AI project** — the story script, the choreography, every SVG
     obstacle, every background, and every frame of animation are generated by Claude on
     Amazon Bedrock. No images were created externally and vectorized. The hand-drawing
     aesthetic is intentional — the project explores what happens when you ask a language model
     to draw freehand SVGs, and it turns out the results have real character and charm.
   - Note on model quality: different Claude models produce noticeably different drawing quality.
     Claude Opus 4.6 consistently produced the best hand-drawn SVG results for this project.

3. **Architecture diagram**
   - A section titled "Architecture" with an embedded image `docs/architecture-diagram.png`
     (the owner will create this in draw.io from the detailed description below).
   - Brief caption explaining the pipeline stages.

4. **Production-quality patterns — not a toy**
   - A bulleted list highlighting the engineering maturity of the project, making it clear
     this is production-grade code despite being a personal project. Include:
     - **Multi-agent orchestration** — 4 specialized AI agents (Director, Animator, Drawing,
       Renderer) coordinated by a single orchestrator Lambda
     - **Deterministic validation at every stage** — pure-function validators
       (`ScriptValidator`, `FrameValidator`, `SvgLinter`) gate every AI output before it
       proceeds; nothing from an LLM goes anywhere raw
     - **Automatic retry with exact error feedback** — when validation fails, the exact errors
       are fed back to the model in a retry prompt (up to configurable retry count)
     - **SVG repair pipeline** — the SVG linter doesn't just reject; it sanitises and repairs
       common model mistakes (tag stripping, namespace cleanup, size enforcement)
     - **Caching for cost and latency** — obstacle SVGs are cached by slug across episodes;
       background SVGs are cached per act; the bundled obstacle library (26 pre-drawn SVGs)
       avoids redundant Bedrock calls entirely
     - **RAG-augmented character consistency** — a Bedrock Knowledge Base with ~50 hand-authored
       character documents ensures Linai's personality, reactions, and visual vocabulary are
       consistent across all generated episodes
     - **Dead Letter Queue** — failed orchestrator invocations are captured in SQS for
       inspection and replay, not silently lost
     - **AgentCore session management** — all agents in a generation job share a single
       AgentCore session ID, preparing the architecture for cross-episode memory in future
       versions
     - **Parallel per-act generation** — the Animator and Renderer fan out one Bedrock call per
       act/clip in parallel with independent retry, reducing end-to-end latency
     - **Cost guardrails** — per-stage token ceilings prevent runaway Bedrock spend; the
       entire infrastructure has near-zero idle cost (< $1/month with no generation)
     - **Structured observability** — every agent call emits structured JSON logs with agent
       name, token count, validation result, retry count, and duration
     - **Security by default** — Lambda Function URLs with IAM auth, S3 blocked from public
       access, CloudFront OAC, SVG sanitisation before any S3 write, all episode content
       escaped before DOM insertion
     - **100% test coverage on validators** — all validators are pure functions tested with
       passing and failing cases; CDK assertion tests verify security-critical properties
     - **Single-stack deployment** — one `cdk deploy` gives any developer the complete system
       in their own AWS account

5. **How it works (pipeline overview)**
   - A numbered list summarizing the generation flow from prompt to playable episode:
     1. Developer types a prompt in the local creator studio
     2. RAG retrieval from Bedrock Knowledge Base (character context)
     3. Director agent generates a branching story script (2–3 acts, choices, outcomes)
     4. Script validator gates the output
     5. Animator agent generates keyframe choreography (one Bedrock call per act, in parallel)
     6. Frame validator gates each act
     7. Drawing agent generates obstacle + background SVGs for any not in the cache/library
     8. Renderer agent composes final SVG clips with full animation
     9. SVG linter sanitises every clip
     10. Episode JSON + thumbnail assembled and saved

6. **Live gallery**
   - Link to `https://linions.odedkeren.dev/`
   - Mention: 10 published episodes, all generated by the pipeline, playable by anyone in a
     browser with no setup

7. **About this project**
   - This is a personal project built to explore production-quality AI agent architecture on
     AWS. It is not a toy or a demo — it is a complete, tested, deployable system. However, it
     is not maintained as a product and comes with no guarantees.
   - The repo serves as a reference implementation for: multi-agent orchestration,
     deterministic validation of AI output, RAG-augmented generation with Bedrock
     Knowledge Bases, and serverless infrastructure with near-zero idle cost.

8. **For developers**
   - Brief prerequisites list: AWS account with Bedrock access, Node.js 20+, Python 3.11+,
     GitHub CLI
   - Quickstart (4 lines): `cdk deploy` → `bash scripts/setup-env.sh` →
     `npm --prefix frontend run build` → `npm --prefix proxy start`
   - Link to `SCRIPTS.md` for the full command reference, local development flow, debug
     runners, and publication workflow
   - Link to `DESIGN.md` for agent contracts, JSON schemas, and data flow

9. **Tech stack**
   - A clean table or list: AWS CDK, Lambda, S3, CloudFront, DynamoDB, SQS, Bedrock
     (Claude models), Bedrock Knowledge Bases, AgentCore, Python 3.11,
     TypeScript, pure SVG/CSS animation

10. **Legal notice**
    - Linai and the Linions characters are original creations. All rights reserved.

---

### Deliverable 2 — SCRIPTS.md (developer reference)

Move all the operational/developer content currently in `README.md` into a new `SCRIPTS.md`.
Read the current `README.md` first — everything below the "Requirements" heading through
"Quick answers" moves here. The new file should have this structure:

1. **Title and purpose** — "Developer Reference — Linions" with a one-line note:
   "This document covers local setup, development workflow, scripts, and debug runners.
   See [README.md](README.md) for the project overview."
2. **Prerequisites** — Node.js 20+, Python 3.11+, AWS CLI, `jq`, AWS account with CDK
   bootstrap, GitHub CLI
3. **Repo packages** — the table of `infra/`, `proxy/`, `frontend/` with install commands
4. **First-time setup** — the 5-line install block
5. **Local development flow** — the full section: two web surfaces, setup-env, build
   frontend, start proxy, publish workflow (all 5 subsections from the current README)
6. **Generation pipeline detail** — "Current generation flow" section (the 7-step
   description) and "Where Bedrock is called today" section — moved verbatim
7. **Command reference** — the full table from the current README
8. **Debug runners** — all 4 runner sections (Director, Animator, Drawing, Renderer) with
   their full examples and option lists, plus the publish-local section
9. **Local preview** — the "Preview the repo-managed public site locally" section
10. **Quick answers** — the FAQ-style section from the current README

This keeps the main README clean as a showcase while preserving all developer docs.

---

### Deliverable 3 — Architecture diagram specification (for draw.io)

The project owner will create the diagram in draw.io. Write the specification below
**verbatim** into `docs/architecture-diagram-spec.md` (extract it from this file, do not
rewrite or summarize):

**Diagram layout: left-to-right flow with three swim lanes**

**Swim lane 1 — "Developer laptop" (left side)**
- Box: "Local Creator Studio" (`localhost:3000`)
  - Sub-label: "Prompt input → Preview → Download"
- Box: "Local Proxy" (Node.js)
  - Arrow from Creator Studio → Proxy, label: "POST /generate"
  - Arrow from Proxy → Creator Studio, label: "Poll /status"
  - Note: "SigV4 signing, GitHub username injection"

**Swim lane 2 — "AWS (LinionsStack)" (center, largest area)**

Sub-section: "Compute"
- Box: "Generate Lambda"
  - Arrow from Proxy → Generate Lambda, label: "HTTPS (IAM auth)"
  - Arrow from Generate Lambda → DynamoDB, label: "Create job (PENDING)"
  - Arrow from Generate Lambda → Orchestrator Lambda, label: "Async invoke"
- Box: "Orchestrator Lambda" (largest box, pipeline stages inside)
  - Inside the orchestrator, show the pipeline as a vertical flow:
    1. "RAG Retrieval" → arrow to Bedrock KB
    2. "Director Agent" → arrow to Bedrock (Claude)
    3. "Script Validator" (gate icon / checkpoint)
    4. "Animator Agent (per-act parallel)" → arrow to Bedrock (Claude)
    5. "Frame Validator" (gate icon)
    6. "Drawing Agent (parallel batch)" → arrow to Bedrock (Claude)
    7. "Renderer Agent (per-clip parallel)" → arrow to Bedrock (Claude)
    8. "SVG Linter" (gate icon)
    9. "Episode Assembly + Thumbnail"
  - Each validator shown as a diamond/gate between stages
  - Retry arrows looping back from each validator to its preceding agent, label: "retry with errors"
  - Arrow from pipeline end → S3, label: "Write drafts/"
  - Arrow from Orchestrator → DynamoDB, label: "Update stage labels"
- Box: "Status Lambda"
  - Arrow from Proxy → Status Lambda, label: "HTTPS (IAM auth)"
  - Arrow from Status Lambda → DynamoDB, label: "GetItem"

Sub-section: "AI Services"
- Box: "Amazon Bedrock" (Claude models)
  - Arrows from Director, Animator, Drawing, Renderer agents
- Box: "Bedrock Knowledge Base"
  - Arrow from RAG Retrieval
  - Arrow from KB → S3 KB bucket, label: "~50 character docs"
- Box: "AWS AgentCore"
  - Dashed line to Orchestrator, label: "Shared session ID"

Sub-section: "Storage"
- Box: "S3 — Episodes Bucket"
  - Two prefixes shown: `drafts/{user}/{uuid}/` and `episodes/{user}/{uuid}/`
  - Arrow from S3 episodes prefix → CloudFront
- Box: "DynamoDB — Jobs"
  - Label: "TTL: 24h"
- Box: "SQS — Dead Letter Queue"
  - Arrow from Orchestrator Lambda → SQS, label: "Failed jobs"

Sub-section: "CDN"
- Box: "CloudFront"
  - Arrow from CloudFront → S3, label: "OAC origin"

**Swim lane 3 — "Viewers" (right side)**
- Box: "Public Viewer Site" (`cloudfront-domain`)
  - Sub-label: "Gallery → Episode → Interactive player"
  - Arrow from CloudFront → Public Viewer
- Icon: "Any browser, no setup"

**Visual notes:**
- Use color coding: blue for compute, green for AI/ML services, orange for storage,
  purple for CDN/networking
- Validator gates should be visually distinct (diamond shape or shield icon)
- Retry arrows should be dashed and red
- The orchestrator box should be the visual center of gravity
- Show parallelism with fork/join notation for Animator (per-act) and Renderer (per-clip)

---

### Deliverable 4 — Code and infrastructure hardening

**Agent-executable tasks:**
- All `TODO`, `FIXME`, and `HACK` comments resolved or removed (grep for them)
- CloudWatch log groups: set retention to 14 days in `infra/lib/linions-stack.ts`
  (look for `LogGroup` or `logRetention` properties on Lambda constructs)
- Lambda `description` fields: verify all 3 Lambdas (generate, orchestrator, status) in
  `infra/lib/linions-stack.ts` have meaningful `description` strings, not placeholder text
- Run `pytest --cov=pipeline --cov-report=term-missing tests/` and fix any failures
- Run `ruff check pipeline/ scripts/` and fix any violations
- Run `npm run lint` and fix any violations
- Run `npm --prefix infra run cdk -- synth --quiet` and verify zero errors

**Manual verification by owner (not agent-executable):**
- `[MANUAL]` Verify all 10 published episodes play correctly at `https://linions.odedkeren.dev/`
- `[MANUAL]` Verify episodes play on a smartphone viewport
- `[MANUAL]` Full end-to-end flow works on a clean AWS account (fresh `cdk deploy`)
- `[MANUAL]` Verify STANDARDS.md §9 (Definition of done) — every item checked

---

### Implementation notes for AI assistant

**Execution order:** Do these in sequence — each step depends on the previous:
1. Read the current `README.md` in full.
2. Write `SCRIPTS.md` first (Deliverable 2) — move all developer content out of README.
3. Write `docs/architecture-diagram-spec.md` (Deliverable 3) — extract the spec from
   the Deliverable 3 section in this file verbatim.
4. Write the new `README.md` (Deliverable 1) — complete replacement, not incremental edit.
5. Run Deliverable 4 hardening tasks (lint, test, CDK synth, TODO grep).

**README writing guidelines:**
- The README is a **complete replacement**, not an incremental edit.
- GitHub strips `<iframe>` tags from rendered markdown. Use a clickable image-link instead
  (see Deliverable 1 hero section for the exact syntax).
- The "production-quality patterns" list is the key selling point. Write it with enough
  detail that a senior engineer recognizes real engineering, not buzzwords.
- Do not include setup instructions or command reference in the main README beyond the
  4-line quickstart. All operational detail goes in SCRIPTS.md.
- The tone should be confident and specific — "here is what this does and why it's
  well-built" — not apologetic or hedging. This is a showcase, not documentation.
- Do not invent information. All facts (episode count, service names, patterns) are
  documented in REQUIREMENTS.md, DESIGN.md, and this file.

---

### Gate ✓ (project is done when all of these pass)

**Agent-verifiable (run these and confirm output):**
- [ ] `pytest --cov=pipeline --cov-report=term-missing tests/` — all coverage requirements from STANDARDS.md §6.1 met
- [ ] `ruff check pipeline/ scripts/` — zero violations
- [ ] `npm run lint` — zero violations
- [ ] `npm --prefix infra run cdk -- synth --quiet` — zero errors or warnings
- [ ] `grep -rn 'TODO\|FIXME\|HACK' pipeline/ scripts/ frontend/src/ infra/lib/ proxy/` — zero matches
- [ ] `README.md` is a showcase document with: hero + clickable episode link, "what is this" narrative, architecture diagram placeholder, production-quality patterns list (14 items), pipeline overview, live gallery link, about section, quickstart, tech stack, legal notice
- [ ] `SCRIPTS.md` exists and contains: prerequisites, repo packages, first-time setup, local dev flow, generation pipeline detail, command reference table, all 4 debug runner sections, preview instructions, quick answers
- [ ] `docs/architecture-diagram-spec.md` exists with the full draw.io specification (extracted from this file)
- [ ] CloudWatch log retention is set to 14 days in `infra/lib/linions-stack.ts`
- [ ] All 3 Lambda `description` fields in `infra/lib/linions-stack.ts` are meaningful

**Manual verification by owner:**
- [ ] `[MANUAL]` Full end-to-end flow works on a clean AWS account (fresh `cdk deploy`)
- [ ] `[MANUAL]` All 10 published episodes play on `https://linions.odedkeren.dev/` and on a smartphone
- [ ] `[MANUAL]` Every item in STANDARDS.md §9 (Definition of done) is checked
- [ ] `[MANUAL]` Create architecture diagram in draw.io from `docs/architecture-diagram-spec.md`, export as `docs/architecture-diagram.png`

---

## Phase summary

| Phase | What |
|-------|------|
| 0 | Linai SVG, knowledge base, repo skeleton, fixtures |
| 1 | Validators, models, thumbnail utility (pure Python) |
| 2 | CDK infrastructure (stubbed Lambdas) |
| 3 | Split frontend shell: local creator + public viewer (fake data) |
| 4 | Director agent + orchestrator skeleton |
| 5 | Animator + Drawing + Renderer agents + S3 writes |
| 6 | Local export flow + polished public viewer |
| 7 | Seed episodes + public launch prep |
| 8 | Public-launch hardening, showcase README, documentation |

> Community contributions, CI/CD workflows, and canonical-gallery sync are deferred to v2.
