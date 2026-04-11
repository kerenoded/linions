# Developer Reference -- Linions

This document covers local setup, development workflow, scripts, and debug runners.
See [README.md](README.md) for the project overview.

---

## Prerequisites

- Node.js 20+
- Python 3.11+
- AWS CLI and `jq`
- An AWS account with CDK bootstrap completed if you are working on infra
- For local proxy usage: GitHub CLI (`gh`) authenticated, or `git user.email` configured

## Repo packages

This repo does **not** use npm workspaces. Each package has its own `package.json`, so
`npm install` at the repo root does **not** install dependencies for `infra/`, `proxy/`,
or `frontend/`.

| Path | Purpose | Install command |
| --- | --- | --- |
| repo root | shared dev tools such as eslint and tsx | `npm install` |
| `infra/` | AWS CDK app | `npm install --prefix infra` |
| `proxy/` | local development proxy server | `npm install --prefix proxy` |
| `frontend/` | browser app build | `npm install --prefix frontend` |

## First-time setup

Run these once after cloning:

```bash
pip install -r requirements.lock
npm install
npm install --prefix infra
npm install --prefix proxy
npm install --prefix frontend
```

Re-run an install command only for the package whose dependencies changed.

## Local development flow

### Two web surfaces

- `http://localhost:3000` is the local creator studio. It is for prompt entry, generation,
  draft preview, download/export, and other developer-only controls.
- `https://<cloudfront-domain>` is the public viewer site. It should show only published
  episodes, their gallery cards, and direct story pages. It should not contain add-story
  or generation controls.

### 1. Make sure the AWS stack already exists

The local proxy reads deployed stack outputs from AWS. This means the stack needs to be
deployed at least once before local generation can work.

> The stack simply needs to exist before local generation can work. Use whatever deployment
> workflow you are using for this repo; the important part here is that the stack outputs are available.

### 2. Refresh local env from deployed stack outputs

```bash
bash scripts/setup-env.sh
```

Run this:

- after the first successful stack deployment
- after any later deployment that changes stack outputs such as function URLs, bucket names, or the CloudFront domain
- any time `proxy/.env` is missing or stale

This script reads CloudFormation outputs and writes `proxy/.env`. It also triggers and waits
for a Bedrock Knowledge Base ingestion job so retrieval is ready before generation starts.

If you changed files under `knowledge-base/` or need to repopulate an emptied KB bucket,
run the same script with KB sync enabled:

```bash
LINIONS_SYNC_KB=1 bash scripts/setup-env.sh
```

That syncs `knowledge-base/` into the deployed KB bucket, then triggers the normal
ingestion wait.

For debugging only, you can skip the ingestion wait:

```bash
LINIONS_SKIP_KB_INGEST=1 bash scripts/setup-env.sh
```

### 3. Build the frontend

```bash
npm --prefix frontend run build
```

Run this:

- before starting the local proxy if `frontend/dist-studio` does not exist
- after changing files in `frontend/src/` or `frontend/public/`

This is **not** something you run only after deployment. It now produces two outputs:

- `frontend/dist-studio` for the localhost creator studio served by the proxy
- `frontend/dist-public` for the public viewer bundle deployed to S3/CloudFront

If you want to bake the real CloudFront domain into the generated frontend bundle, set it at
build time:

```bash
CLOUDFRONT_DOMAIN=https://abc123.cloudfront.net npm --prefix frontend run build
```

If `CLOUDFRONT_DOMAIN` is not set, the frontend falls back to proxy-relative URLs, which is
fine for local development.

### 4. Start the local proxy

```bash
npm --prefix proxy start
```

Run this only after:

- `bash scripts/setup-env.sh` has created `proxy/.env`
- `npm --prefix frontend run build` has created `frontend/dist-studio`

Open `http://localhost:3000` in your browser for the creator studio.
Use the CloudFront domain for the public viewer site.
Use `http://localhost:3000/preview` for a localhost copy of the public viewer that reads only from the repo's local `episodes/` folder.

### 5. Publish publicly in v1

v1 does not have a runtime publish API. The public site is repo-driven.

**From the local debug pipeline (recommended for local development):**

1. Run the full local pipeline: Director -> Animator -> Renderer.
2. Verify the renderer output looks correct.
3. Run `python scripts/publish-local.py tmp/renderer-agent/debug-director.json` to assemble
   `episode.json` and `thumb.svg` and place them under `episodes/<username>/<uuid>/`, then
   rebuild `episodes/index.json` automatically.
4. Open `http://localhost:3000/preview` to verify the published viewer experience against only your local `episodes/` files.
5. Redeploy the stack so the repo-managed `episodes/` content is uploaded to S3/CloudFront.

**From the studio (manual flow):**

1. Generate and preview an episode in the local studio.
2. Download the episode JSON from the studio.
3. Add the episode JSON under `episodes/{username}/` using the filename `{uuid}.json`.
4. Run `node scripts/build-index.js` to generate the thumbnail SVG and rebuild `episodes/index.json`.
5. Redeploy the stack so the repo-managed `episodes/` content is uploaded to S3/CloudFront.

## Generation pipeline detail

### Current generation flow

This is the current implemented pipeline, summarized from browser request to stored draft.

1. Browser -> proxy -> generate Lambda
- The browser sends a generation request with `{ prompt, username }`.
- Only the localhost creator UI calls the generate endpoint.
- The generate Lambda creates a pending job record in DynamoDB and asynchronously invokes the orchestrator Lambda.

2. Orchestrator -> Bedrock Knowledge Base retrieval
- Before any story-writing model call, the orchestrator retrieves character/style context from the Bedrock Knowledge Base.
- This retrieval is used only to assemble `rag_context` for the Director prompt.
- This is not the Director agent itself; it is a pre-step performed by the orchestrator.

3. Director agent -> Bedrock model call
- The orchestrator builds `DirectorInput` from:
  - the user prompt
  - the username
  - the retrieved `rag_context`
  - the current prepared obstacle library names
- Then it calls Bedrock once through the Director agent.
- Purpose: generate the branching story script as typed `DirectorOutput` JSON:
  - episode title
  - 2-3 acts
  - 2-3 choices per act
  - open obstacle slugs
  - descriptions and outcomes
- After the model returns, deterministic script validation runs. If validation fails, the orchestrator retries the Director with the exact validation errors.

4. Animator agent -> parallel Bedrock model calls, one per act
- If the Director output passes validation, the orchestrator builds `AnimatorInput` from the acts plus config values like canvas size and ground line.
- Then it splits the validated acts and launches one Animator Bedrock call per act in parallel.
- Each one-act Animator input also carries explicit `requires_handoff_in` / `requires_handoff_out` flags plus one canonical `handoff_character_x` so Bedrock knows whether that act slice must begin or end on a continuity handoff pose and where that boundary pose should land.
- Each act is validated on its own, and successful act manifests are merged back into one `AnimatorOutput`.
- Purpose: generate typed `AnimatorOutput` JSON for clip choreography:
  - approach / win / fail clips
  - duration and obstacle placement
  - Linai keyframes
  - open-text `action` and `expression`
  - optional `motion_note`
  - optional `part_notes` targeting real Linai SVG ids
- If one act fails deterministic validation, only that act is retried with the exact validation errors.

5. Obstacle resolution
- After Animator succeeds, the orchestrator resolves each obstacle slug used by the clips.
- First it checks the prepared obstacle SVG library in `frontend/public/obstacles/`.
- If one or more prepared files exist for that slug, one is selected and reused.
- If no prepared file exists, the orchestrator falls back to the Drawing agent.

6. Drawing agent -> Bedrock model calls for obstacles and backgrounds
- For obstacles: called only for obstacle slugs that do not already exist in the prepared library.
  The Director's `drawing_prompt` is passed through to the Drawing agent.
  Successful drawn obstacles are cached by slug and injected as `obstacle_svg_override`.
- For backgrounds: called once per act using the Director's `background_drawing_prompt`.
  Each background SVG is injected into all clips for that act as `background_svg`.
- The orchestrator batches missing obstacle slugs plus per-act backgrounds into one Drawing
  stage and runs up to `MAX_PARALLEL_DRAWING_TASKS` Bedrock calls in parallel.
- If one Drawing task fails validation, only that obstacle/background identity is retried.
- Purpose: generate standalone SVGs as typed `DrawingOutput(svg: str)`.
- After the model returns, the SVG is sanitised and validated. If validation fails, the orchestrator retries the Drawing agent with the exact SVG errors.

7. Renderer agent -> parallel Bedrock model calls, one per clip
- The orchestrator builds `RendererInput` from the Animator output plus resolved obstacle/background SVGs.
- It fans out one Renderer call per clip in parallel.
- Each Renderer call receives keyframe choreography, the obstacle SVG, and the background SVG, and produces a complete self-contained SVG scene clip.
- The SVG linter sanitises and validates every clip before acceptance.
- Sanitised clips are merged back into the final episode-ordered JSON artifact.
- Episode JSON and thumbnail are assembled and written to `drafts/` in S3.

### Where Bedrock is called today

- Bedrock Knowledge Base retrieval:
  - used by the orchestrator before Director
  - purpose: fetch `rag_context`
- Director Bedrock model call:
  - purpose: generate branching story script JSON
- Animator Bedrock model calls:
  - purpose: generate Linai choreography JSON
  - one Bedrock call per act, launched in parallel
- Drawing Bedrock model calls:
  - purpose: generate obstacle SVG when the library has no prepared match (drawing_type="obstacle")
  - purpose: generate background SVG per act from Director's background_drawing_prompt (drawing_type="background")
  - launched in one bounded parallel pool shared by missing obstacle slugs and act backgrounds
- Renderer Bedrock model call:
  - purpose: generate final self-contained SVG scene clips from keyframes plus resolved obstacle SVGs

The local debug runners mirror these same responsibilities:

- `python scripts/run-director-agent.py ...`
  - retrieves or accepts `rag_context`, then calls the real Director agent with the same deterministic-validation retry loop as the orchestrator
- `python scripts/run-animator-agent.py ...`
  - reads a real Director JSON file, then launches one real Animator call per act in parallel
- `python scripts/run-drawing-agent.py <slug> "<prompt>" [--drawing-type background]`
  - builds the real Drawing input with a Director-authored prompt and calls the real Drawing agent
- `python scripts/run-renderer-agent.py ...`
  - reads a real Animator JSON file, resolves `obstacle_svg_override`, then the bundled
    obstacle library, then cached generated SVGs in `tmp/renderer-agent/`, and only draws the
    remaining obstacle/background assets in bounded parallel
  - auto-detects a matching `tmp/director-agent/<same filename>.json` when `--director-output`
    is omitted and the standard debug file layout is used
  - runs one real Renderer call per clip in parallel, then re-composes the exact approved
    obstacle/background layers into the final SVG before validation and retries truncated or
    invalid clip responses with exact retry guidance
- `python scripts/publish-local.py tmp/renderer-agent/debug-director.json`
  - reads the renderer output from `tmp/renderer-agent/` and the director output from
    `tmp/director-agent/`, assembles `episode.json` and `thumb.svg` identically to the
    orchestrator, writes them to `episodes/<git-username>/<uuid>/`, and rebuilds
    `episodes/index.json`

## Command reference

| Command | When to run it | Notes |
| --- | --- | --- |
| `pytest` | for normal test runs | Fast by default. Synth-backed CDK tests are skipped if `infra/cdk.out/LinionsStack.template.json` is missing. |
| `LINIONS_FORCE_CDK_SYNTH=1 pytest tests/cdk/test_linions_stack.py` | when you want pytest to run a fresh CDK synth | Slower than normal `pytest`. |
| `ruff check pipeline/` | after changing Python code | Python lint. |
| `npm run lint` | after changing TypeScript code | Lints `infra/`, `proxy/`, and `frontend/src/`. |
| `python scripts/run-director-agent.py "Linai meets a robot"` | when you want to inspect the Director agent directly | By default it uses the same Bedrock Knowledge Base retrieval flow as the deployed orchestrator, retries deterministic script-validation failures with the exact validator errors, and writes input/RAG/prompt/raw/validated output plus per-attempt artifacts to `tmp/director-agent/`. |
| `python scripts/run-animator-agent.py tmp/director-agent/debug-director.json` | when you want to inspect the Animator agent directly | Launches one Bedrock Animator call per act in parallel, then writes combined plus per-act prompt/raw/output artifacts to `tmp/animator-agent/`. |
| `python scripts/run-drawing-agent.py horse "Draw a ..."` | when you want to inspect the Drawing agent directly | Takes an obstacle slug and a drawing prompt. Writes the prompt, raw SVG, and sanitised SVG to `tmp/drawing-agent/`. Use `--drawing-type background` for backgrounds. |
| `python scripts/run-renderer-agent.py tmp/animator-agent/debug-director.json` | when you want to inspect the Renderer agent directly | Resolves obstacle SVG overrides, auto-draws any missing obstacle slugs, runs one real Renderer call per clip in parallel, retries truncated or invalid clip responses, validates/sanitises the returned clips, and writes prompt/raw/output artifacts to `tmp/renderer-agent/`. |
| `python scripts/publish-local.py tmp/renderer-agent/debug-director.json` | after verifying renderer output, to publish the episode locally | Reads the renderer output JSON directly, finds the director output at `tmp/director-agent/<prefix>.json`, assembles `episode.json` + `thumb.svg` identically to the orchestrator, validates the published artifact, writes them to `episodes/<github-username>/<uuid>/`, and rebuilds `episodes/index.json`. By default it uses the same username rule as the proxy: GitHub CLI login first, then `git user.email` local-part fallback. It refuses to overwrite existing published files. Accepts `--username`, `--episode-uuid`, and `--output-dir` overrides. |
| `npm run cdk -- synth --quiet` | after infra changes, or when you want to generate `infra/cdk.out` | Equivalent to `cdk synth` if you have the CDK CLI available. |
| `npm --prefix proxy run build` | after changing proxy code, or when you want to validate the proxy compiles cleanly | Recommended as a proxy TypeScript type-check. It does not need to run before `npm --prefix proxy start`. |
| `npm --prefix frontend run build` | before local proxy start, and after frontend changes | Required because the proxy serves `frontend/dist-studio` and CloudFront deploys `frontend/dist-public`. |

## Debug runners

### Inspect one Director-agent run

If you want to test the Director agent directly while developing, run:

```bash
python scripts/run-director-agent.py "Linai meets a robot"
```

If `BEDROCK_KNOWLEDGE_BASE_ID` is not exported, the script will try to discover
`KnowledgeBaseId` from the `LinionsStack` CloudFormation outputs automatically.

This writes:

- `tmp/director-agent/debug-director.input.json`
- `tmp/director-agent/debug-director.rag-context.txt`
- `tmp/director-agent/debug-director.prompt.txt`
- `tmp/director-agent/debug-director.raw.txt`
- `tmp/director-agent/debug-director.json`
- when retries happen, one per-attempt `.prompt.txt`, `.raw.txt`, and parsed `.json` file for each attempt

Useful options:

```bash
python scripts/run-director-agent.py "Linai meets a robot" --print-rag-context
python scripts/run-director-agent.py "Linai meets a robot" --rag-context "Linai is playful and persistent." --print-prompt
python scripts/run-director-agent.py "Linai meets a robot" --rag-context-file tmp/rag-context.txt --print-json
python scripts/run-director-agent.py "Linai meets a robot" --knowledge-base-id KB12345678 --validation-error 'act 1 must have exactly one winning choice'
python scripts/run-director-agent.py "Linai meets a robot" --stack-name LinionsStack --aws-profile default --aws-region eu-west-1
```

### Inspect one Animator-agent run

If you want to test the Animator agent directly while developing, run:

```bash
python scripts/run-animator-agent.py tmp/director-agent/debug-director.json
```

This writes:

- `tmp/animator-agent/debug-director.input.json`
- `tmp/animator-agent/debug-director.prompt.txt`
- `tmp/animator-agent/debug-director.raw.txt`
- `tmp/animator-agent/debug-director.json`
- `tmp/animator-agent/debug-director.act-0.prompt.txt` and `.raw.txt`
- `tmp/animator-agent/debug-director.act-1.prompt.txt` and `.raw.txt`
- one per-act `.json` file for each successful act

Useful options:

```bash
python scripts/run-animator-agent.py tmp/director-agent/debug-director.json --print-prompt
python scripts/run-animator-agent.py tmp/director-agent/debug-director.json --print-json
python scripts/run-animator-agent.py tmp/director-agent/debug-director.json --validation-error 'act 0 choice 1 must contain exactly one fail clip'
```

### Inspect one Drawing-agent run

If you want to test the Drawing agent directly while developing, run:

```bash
python scripts/run-drawing-agent.py horse "Draw a detailed, high-quality SVG illustration of a medieval horse. The horse should have a muscular build, flowing mane, a long tail, defined legs with hooves, and a bridle with reins. Use rich layering of shapes (back-to-front: tail, body, legs, neck, head, mane, bridle) to create depth. Technical requirements: Output one complete <svg>...</svg> document with a viewBox attribute. Valid XML, inline only. Assign these IDs: obstacle-root on the root <svg>, obstacle-main on the <g> containing the full horse body, obstacle-animated-part on the mane only, animated with <animateTransform type='rotate'> to gently sway."
```

The first argument is the obstacle slug. The second argument is the drawing prompt
(typically copied from Director output).

This writes:

- `tmp/drawing-agent/horse.prompt.txt`
- `tmp/drawing-agent/horse.raw.svg`
- `tmp/drawing-agent/horse.svg`

For background SVGs, use `--drawing-type background`:

```bash
python scripts/run-drawing-agent.py background-act-0 "Draw a full-canvas SVG background of a dark enchanted forest at twilight..." --drawing-type background
```

Useful options:

```bash
python scripts/run-drawing-agent.py horse "Draw a ..." --print-prompt
python scripts/run-drawing-agent.py horse "Draw a ..." --print-svg
python scripts/run-drawing-agent.py horse "Draw a ..." --validation-error 'svg must include required element id="obstacle-main"'
```

### Inspect one Renderer-agent run

If you want to test the Renderer agent directly while developing, run:

```bash
python scripts/run-renderer-agent.py tmp/animator-agent/debug-director.json
```

This resolves each obstacle slug before rendering:
- uses `obstacle_svg_override` when already present in the Animator JSON
- otherwise checks the bundled obstacle library at `frontend/public/obstacles/`
- otherwise checks `tmp/renderer-agent/generated-obstacles/*.svg`
- otherwise auto-runs DrawingAgent once for that slug and reuses the generated SVG

If `--director-output` is provided (or auto-detected), it also generates background SVGs per
act using each act's `background_drawing_prompt` and injects them as `background_svg` on
matching clips. The background resolution order is:
- cached `tmp/renderer-agent/generated-backgrounds/<slug>.svg` from a prior run
- matching slug from the bundled background library at `frontend/public/backgrounds/`
- auto-runs DrawingAgent and saves the result as `<slug>.svg` (slug derived from the prompt)

Missing obstacle/background draws are batched and run in parallel up to
`MAX_PARALLEL_DRAWING_TASKS`.

Then it fans out one Renderer call per clip in parallel, validates the SVGs, and
re-composes the exact obstacle/background layers into each returned scene before merging the
sanitised clips back into one episode-ordered JSON artifact.

This writes:

- `tmp/renderer-agent/debug-director.input.json`
- `tmp/renderer-agent/debug-director.prompt.txt`
- `tmp/renderer-agent/debug-director.raw.txt`
- `tmp/renderer-agent/debug-director.json`
- one per-clip sanitised `.svg` file
- `tmp/renderer-agent/generated-obstacles/*.prompt.txt`, `.raw.svg`, and `.svg` for any obstacle slugs the runner had to draw locally
- `tmp/renderer-agent/generated-backgrounds/<slug>.prompt.txt`, `<slug>.raw.svg`, and `<slug>.svg` for any backgrounds generated (slug derived from the prompt)

Useful options:

```bash
python scripts/run-renderer-agent.py tmp/animator-agent/debug-director.json --director-output tmp/director-agent/debug-director.json
python scripts/run-renderer-agent.py tmp/animator-agent/debug-director.json --print-prompt
python scripts/run-renderer-agent.py tmp/animator-agent/debug-director.json --print-json
python scripts/run-renderer-agent.py tmp/animator-agent/debug-director.json --validation-error 'renderer clip (act_index=0, branch=approach, choice_index=None) missing id="linai"'
```

### Publish locally

```bash
python scripts/publish-local.py tmp/renderer-agent/debug-director.json
```

After `publish-local.py` finishes, keep the proxy running and open:

```bash
http://localhost:3000/preview
```

This loads the same public viewer shell used by CloudFront, but it reads `episodes/index.json`,
`episode.json`, and `thumb.svg` directly from your local repo instead of the deployed bucket.
Story routes also work locally, for example:

```bash
http://localhost:3000/preview/story/<username>/<uuid>
```

## Quick answers

- `npm install` at the repo root does **not** install dependencies for `infra/`, `proxy/`, or `frontend/`.
- `npm --prefix frontend run build` is required before local proxy startup and after frontend changes. It is not tied only to deployment.
- `npm --prefix proxy run build` is recommended after proxy changes because it type-checks the proxy, but it is not required to run the proxy locally.
- `bash scripts/setup-env.sh` should be run after the first deployed stack exists, and again whenever deployed stack outputs change.
