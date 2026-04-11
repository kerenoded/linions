<!-- AI ASSISTANT: Read in this order before writing any code:
  1. REQUIREMENTS.md
  2. STANDARDS.md  
  3. DESIGN.md
  4. PHASES.md
  Then confirm which phase you are implementing before starting. -->
  
# Requirements — Linions

> Version 2.5 | Status: approved
> Author: project owner

---

## 1. Project overview

Linions is an AI-powered interactive animated story generator. The first character is
**Linai** — an original expressive animated character. Linai encounters obstacles, and reacts
to choices the viewer makes. Future characters include Linoi (male) and eventually their
kids — the Linions family — but phase 1 ships Linai only.

A developer types a natural language prompt in a local creator UI; a pipeline of AI
agents running on AWS generates a short branching animated episode saved as a
self-contained JSON file. In v1, a generated draft becomes public only after the developer
downloads it, adds it under the repo's `episodes/` folder, rebuilds `episodes/index.json`,
and redeploys. The public site is separate from the local creator UI and can be used by
anyone in a browser with no setup or account required.

This project demonstrates production-quality AI agent architecture on AWS: multi-agent
orchestration, deterministic validation of AI output, RAG-augmented character
generation using Bedrock Knowledge Bases, and a secure serverless infrastructure with
near-zero idle cost.

---

## 2. System modes

**Generate mode** — a developer who has deployed `LinionsStack` to their own AWS account
runs the local proxy, opens `localhost:3000`, types a prompt, and generates episodes.
Generated episodes land in a `drafts/` prefix in S3 and are not yet visible in the public
viewer site. The developer can preview them locally, then decide to download/export or
discard.

**Repo publication mode** — a developer takes a downloaded episode artifact from the local
creator UI, adds it under the repo's `episodes/` folder together with its thumbnail,
rebuilds `episodes/index.json`, and redeploys. Only repo-managed `episodes/` content is
shipped to S3/CloudFront in v1.

**View mode** — anyone with a CloudFront URL can browse that deployment's published episode
gallery and open a dedicated story page for any published episode. No setup, no credentials,
no account required. Only published episodes appear. The CloudFront site contains no prompt
input, generation controls, or other creator-only tools.

**Community contribution workflow** — deferred to v2. The GitHub PR flow, canonical
owner-managed gallery, and related CI/CD workflows are intentionally out of scope for v1.

---

## 3. Goals

### Primary goals
- Demonstrate multi-agent orchestration on AWS with clear, tested contracts.
- Demonstrate deterministic validation of AI-generated output (hybrid AI + rule-based pipeline).
- Demonstrate RAG-augmented generation using Bedrock Knowledge Bases for character consistency.
- Show a secure, serverless AWS architecture with near-zero idle cost.
- Produce a working product that any person can enjoy in a browser without any setup or account.
- Deliver a polished public viewer experience that feels professional and separate from the
  localhost creator tooling.

### Secondary goals
- Serve as a reference implementation of a phased, tested, and observable AI agent pipeline.
- Prepare the architecture so community contribution workflows can be added cleanly in v2.

### Non-goals (explicitly out of scope)
- A public generation endpoint — generation runs on each developer's own AWS account only.
- The CloudFront public site mirroring the full localhost creator UI.
- User accounts, authentication for viewers, or persistent user data of any kind.
- Community contribution workflow in v1.
- Audio or music generation.
- Mobile-native app (responsive browser is sufficient).
- Free-text user input during gameplay (choices are predefined buttons only).
- Video file export (mp4, gif).
- Analytics or usage tracking of any kind.
- Monetisation.

---

## 4. Users

**Viewer** — anyone with a CloudFront URL. No setup, no API key, no account. Browses the
published episode gallery and plays any episode interactively in the browser.

**Developer** — anyone who has cloned the repo, deployed `LinionsStack` to their own AWS
account, and is running the local proxy. Generates episodes, previews drafts locally,
downloads/export drafts, and can later add selected episodes to their own public viewer
site through the repo-driven deployment flow.

**Contributor (planned for v2)** — a developer who will be able to submit one of their
published episodes to an owner-managed canonical gallery via GitHub PR.

> **Character roadmap:** Phase 1 ships with Linai only (female character). Linoi (male) and
> further Linions family members are planned for future phases. The architecture is
> character-agnostic — adding a new character requires only a new SVG template and a new
> knowledge base instance.

---

## 5. Functional requirements

### 5.1 Episode generation (local creator UI, developer's own AWS)

| ID | Requirement |
|----|-------------|
| GEN-01 | The system shall provide a browser UI at `localhost:3000` for entering a natural language prompt and monitoring generation progress. |
| GEN-02 | The browser UI shall be served by a local proxy process. The proxy is responsible for SigV4 signing of all requests to the Lambda Function URL using the developer's local AWS credentials profile. No credentials shall ever be transmitted to or stored in the browser. |
| GEN-03 | At proxy startup, the proxy shall read the developer's GitHub username using the GitHub CLI (`gh api user --jq .login`) or local git config as fallback. This username is injected into every generate request — the user never types it. If the username cannot be determined, the proxy shall refuse to start with a clear error message. |
| GEN-04 | On clicking generate, the system shall immediately return a job ID to the browser and begin async generation on Lambda. The browser shall store the job ID in localStorage for automatic recovery if the tab is closed. |
| GEN-05 | The browser shall poll a status endpoint every 3 seconds. The progress indicator shall show: `[1/6] Querying character knowledge base...`, `[2/6] Generating story script...`, `[3/6] Validating script structure...`, `[4/6] Designing animation keyframes...`, `[5/6] Drawing SVG assets...`, `[6/6] Rendering SVG clips...`. |
| GEN-06 | Generation shall complete in under 60 seconds from prompt submission to episode available in S3. |
| GEN-07 | The system shall produce a complete episode JSON file — full story tree, all SVG clips, title, and description — and a separate thumbnail SVG file, before showing any animation to the user. |
| GEN-08 | Each episode shall have 2–3 obstacle acts. Each act shall offer 2–3 predefined choices. Each choice shall have a win path and a fail path. |
| GEN-09 | Each episode shall be assigned a UUID and saved to `drafts/{username}/{uuid}/episode.json` in the developer's own S3 bucket, alongside its thumbnail at `drafts/{username}/{uuid}/thumb.svg` and supporting SVG assets under `drafts/{username}/{uuid}/obstacles/` and `drafts/{username}/{uuid}/backgrounds/`. Draft episodes are not visible in the gallery and are not served by CloudFront. |
| GEN-10 | The system shall retry failed AI agent calls up to 2 times with the exact validation error in the retry prompt. After 2 failures the job shall be marked `FAILED` with a descriptive error. |
| GEN-11 | If generation fails, no partial episode file or thumbnail shall be written to S3. |
| GEN-12 | All generation parameters shall be defined in a single configuration file. No magic numbers. |
| GEN-13 | Upon successful generation the browser shall display the completed animation inline and offer a Download action for the generated episode artifact. |
| GEN-14 | Inline preview is the default state after generation completes. |
| GEN-15 | The Download action shall fetch the generated draft episode JSON and trigger a browser file download for the developer's own use. |
| GEN-16 | v1 publication is repo-driven: a developer may place a downloaded episode under `episodes/{username}/`, run `scripts/build-index.js`, and redeploy to make it public. |
| GEN-17 | Creator-only controls — prompt input, generation progress, download/export, and any draft-management controls — shall exist only in the localhost creator UI and shall not be included in the CloudFront public viewer build. |

### 5.2 Public viewer site (every deployment)

| ID | Requirement |
|----|-------------|
| GAL-01 | Every `LinionsStack` deployment shall serve a public viewer site at its CloudFront URL. The home page lists all episodes in that deployment's `episodes/index.json` using thumbnail-first cards with title and optional supporting metadata. |
| GAL-02 | Each published episode shall have a dedicated direct shareable URL in the format `https://{cloudfront-domain}/story/{username}/{uuid}`. |
| GAL-03 | The owner's deployment shall ship with at least 3 pre-generated episodes in the repo so viewers see content immediately. |
| GAL-04 | The public viewer site shall not expose prompt input, generation controls, download/export actions, or any other creator-only workflow. |
| GAL-05 | The gallery page and episode page shall treat all episode JSON values as untrusted and escape them before DOM insertion. |
| GAL-06 | CloudFront shall cache `episodes/*` and `episodes/index.json` with a TTL of 24 hours. |
| GAL-07 | The gallery and player shall be fully responsive — working correctly on desktop and smartphone. SVG clips shall scale with `width: 100%; height: auto`. Choice buttons shall stack vertically on narrow screens. |
| GAL-08 | The public viewer site shall present published episodes with a polished, professional visual design, with clear separation between the gallery page and the individual episode page. |

### 5.3 Repo publication workflow

| ID | Requirement |
|----|-------------|
| PUB-01 | v1 shall not include a runtime publish API or publish Lambda. CloudFront content is repo-managed. |
| PUB-02 | A generated draft becomes publicly visible only after its episode JSON and thumbnail are added under the repo's `episodes/{username}/` folder and the stack is redeployed. |
| PUB-03 | `scripts/build-index.js` shall rebuild `episodes/index.json` locally by scanning the repo `episodes/` folder, extracting metadata from each episode JSON, and generating the matching thumbnail SVG from the first approach clip. |
| PUB-04 | `episodes/index.json` shall contain only repo-managed published episodes. Drafts stored in S3 under `drafts/` shall never appear in the public viewer. |
| PUB-05 | Publication remains a one-way workflow in v1. There is no unpublish UI. |

| ID | Requirement |
|----|-------------|
| JOB-01 | Each generation job shall be tracked in DynamoDB with: jobId, status (PENDING / GENERATING / DONE / FAILED), current stage label, episodeS3Key, createdAt, and TTL. |
| JOB-02 | DynamoDB TTL shall be 24 hours. Expired records deleted automatically. |
| JOB-03 | Job status shall be readable by a dedicated status Lambda performing a single DynamoDB GetItem only — no Bedrock calls. |
| JOB-04 | If a user closes the browser and returns, the browser shall read the job ID from localStorage and resume polling automatically. |
| JOB-05 | An SQS Dead Letter Queue shall be attached to the orchestrator Lambda. Failed jobs after all AWS automatic retries are captured in the DLQ with their payload for developer inspection and replay. |

### 5.4 Agent pipeline

| ID | Requirement |
|----|-------------|
| AGT-01 | The pipeline shall consist of Director, Animator, and Renderer agents, plus a conditional Drawing agent for unknown obstacle slugs, all running inside a single orchestrator Lambda. |
| AGT-02 | All agents in a generation job shall share a single AgentCore session. No manual JSON threading between stages. |
| AGT-03 | The Director agent shall query the Bedrock Knowledge Base (RAG) twice before writing the script: once for obstacle-specific behaviors, once for tone and style rules. |
| AGT-04 | The Director agent shall generate the episode title (max 60 chars) and description (max 120 chars). |
| AGT-05 | A deterministic script validator (pure function) shall validate Director output before it reaches the Animator. |
| AGT-06 | A deterministic frame validator (pure function) shall validate Animator output before it reaches the Renderer. |
| AGT-07 | A deterministic SVG linter (pure function) shall validate and sanitise Renderer output before any S3 write. Rules: no `<script>`, `<iframe>`, `<object>`, `<embed>` tags; no external URLs; no `data:` URIs; size within config limit. |
| AGT-08 | On validator failure the system shall re-prompt the relevant agent with the exact errors (up to 2 retries) before marking the job FAILED. |

### 5.5 Thumbnail

| ID | Requirement |
|----|-------------|
| THU-01 | The orchestrator Lambda shall generate a thumbnail immediately after assembling the episode JSON, as part of the same pipeline run. |
| THU-02 | The thumbnail is a static SVG extracted from the first approach clip by stripping all animation elements (`<animate>`, `<animateTransform>`, `<animateMotion>`, `<set>`), leaving a static first-frame snapshot. |
| THU-03 | The thumbnail extraction logic shall live in a shared utility `pipeline/media/thumbnail.py` used by the orchestrator Lambda and designed for reuse by future owner-gallery deploy automation in v2. One function, no duplicated extraction logic. |
| THU-04 | During generation, the thumbnail shall be saved to S3 at `drafts/{username}/{uuid}/thumb.svg` in the same write batch as the draft episode JSON. If thumbnail extraction fails the whole job is marked FAILED — no draft episode without a thumbnail. |
| THU-05 | The gallery index (`episodes/index.json`) shall include a `thumbPath` field for each episode pointing to the thumbnail S3 key. |

### 5.6 RAG knowledge base

| ID | Requirement |
|----|-------------|
| RAG-01 | The Bedrock Knowledge Base shall contain approximately 40–50 hand-authored documents: ~20 character behavior docs, ~15 narrative pattern docs, ~10 style rule docs. These shall be authored in Phase 0 before any agent development begins. |
| RAG-02 | Knowledge base source documents shall be stored in a dedicated S3 bucket and indexed automatically by Bedrock Knowledge Bases. |
| RAG-03 | The Director agent shall use both RAG query results as grounding context ensuring Linai's personality is consistent across all generated episodes. |
| RAG-04 | The knowledge base is part of LinionsStack. Every developer who deploys gets their own knowledge base instance. |

### 5.7 Character and animation

| ID | Requirement |
|----|-------------|
| ANI-01 | Linai shall be rendered as a single reusable SVG template animated procedurally. The character shape shall not be regenerated per episode. Linai's visual design shall be completed in Phase 0 before any agent development. |
| ANI-02 | Linai shall support open-ended AI-generated expression language. At minimum she should be capable of reading as neutral, happy, sad, angry, scared, triumphant, and in-love, but the Animator is not limited to a closed expression list. |
| ANI-03 | Linai shall support open-ended AI-generated choreography language. At minimum she should be capable of actions such as walk, stop, jump, sit, react, fall, and celebrate, but the Animator is not limited to a closed action list. The Animator may also attach per-part notes targeting real Linai SVG ids so the face and body can express richer acting. |
| ANI-04 | The starter obstacle library in v1 includes wall, hole, tree, puddle (plank or boat as choice options), elevated platform, bird blocking the path, and encounter with a second character holding a flower. Obstacle visuals shall come from a pre-authored SVG library at `frontend/public/obstacles/{name}.svg` when a matching slug exists; otherwise the system shall draw a new obstacle SVG in the same style during generation. Each obstacle SVG shall use `viewBox="0 0 120 150"` and include required IDs: `obstacle-root`, `obstacle-main`, `obstacle-animated-part` (gentle 4-degree idle sway). `obstacle-animated-part-2` is optional for a second animated element. |
| ANI-05 | All animation shall be pure SVG/CSS. No external animation libraries, no canvas, no WebGL. Every episode clip is a complete self-contained SVG string with zero external URL dependencies. |
| ANI-06 | A single episode shall not exceed the maximum total duration defined in config (default: 90 seconds). |
| ANI-07 | Walk duration between obstacles shall be configurable (default: 8 seconds). |
| ANI-08 | Each scene clip shall include a full-canvas background SVG generated per act by the Drawing agent from a Director-provided prompt. Backgrounds may contain subtle glow and color-change animations but no translating or rotating elements. |

### 5.8 Episode metadata

| ID | Requirement |
|----|-------------|
| META-01 | Each episode JSON shall contain at root: `schemaVersion`, `uuid`, `username`, `title`, `description`, `generatedAt`, `contentHash`, `actCount`. |
| META-02 | `username` shall be populated at generation time from the developer's GitHub identity. It shall never be empty and shall never be modified after generation. |
| META-03 | `contentHash` is SHA-256 of the JSON body with only the `contentHash` field set to `null` before hashing. Since `username` is always present from generation time, it is included in the hash. |
| META-04 | The gallery index (`episodes/index.json`) is a flat array. Each entry: `path`, `thumbPath`, `username`, `title`, `description`, `createdAt`. In v1 it is rebuilt locally from repo content via `scripts/build-index.js` or maintained alongside seed episodes. |
| META-05 | Episode files follow a two-prefix, folder-per-UUID structure in every S3 bucket. Draft artifacts live under `drafts/{username}/{uuid}/` (containing `episode.json`, `thumb.svg`, `obstacles/{slug}.svg`, `backgrounds/{slug}.svg`). Published artifacts live under `episodes/{username}/{uuid}/` (containing `episode.json` and `thumb.svg`). The gallery index and CloudFront only reference the `episodes/` prefix. |

### 5.9 Deferred to v2

Community contributions, the Contribute button, GitHub PR validation, and owner-managed
canonical gallery sync are intentionally deferred to v2. Track that scope in
`docs/versions/v2/community-contributions-and-canonical-gallery.md`.

---

## 6. Non-functional requirements

### 6.1 Cost
- Owner idle cost (no generation, viewers only): < $1/month.
- Developer generation cost: < $0.50 per episode, billed to the developer's own account.
- No always-on compute. Lambda, DynamoDB, and Bedrock are all pay-per-invocation.

### 6.2 Performance
- Gallery page initial load: < 2 seconds on 10 Mbps.
- Episode load and first frame: < 1 second (pre-generated static files).
- Generation end to end: < 60 seconds.
- Status polling response: < 200ms (DynamoDB GetItem only).

### 6.3 Availability
- Gallery availability: CloudFront + S3 SLA (~99.9%).
- Generation infrastructure: no availability requirement — developer tool.

### 6.4 Security
- No user data collected, transmitted, or stored anywhere.
- No credentials in any committed file, deployment secret, or frontend asset.
- Lambda Function URL `authType: AWS_IAM` — unsigned requests rejected before Lambda runs.
- S3 not directly accessible — CloudFront OAC only.
- SVG sanitised before S3 write. Gallery escapes all episode content before DOM insertion.
- See STANDARDS.md §4 for full security checklist.

### 6.5 Scalability
- Gallery handles traffic spikes automatically — CloudFront + S3 scale without configuration.
- Generation stack: one job at a time per developer — no concurrency requirement.

### 6.6 Observability
- Every agent call produces a structured log: agent name, prompt summary, model, token count, validation result, retry count, duration ms.
- Validation failures log the exact field and rule.
- Lambda logs to CloudWatch. Proxy mirrors to `logs/generation-{timestamp}.json`.
- `VERBOSE=true` enables full prompt/response logging.
- DynamoDB stage label updated in real time for the polling UI.

### 6.7 Maintainability
- Each agent has a documented input/output contract in DESIGN.md.
- Each validator is a pure function with 100% unit test coverage.
- No phase is complete until all tests pass. See PHASES.md for gate criteria.
- All tuneable values in a single config file per language. No magic numbers.

---

## 7. Constraints

- **Stack**: One CDK stack (`LinionsStack`) — every deployer gets the complete system.
- **Episode lifecycle**: `drafts/` (generated in the developer's AWS account) → downloaded repo artifact → `episodes/` (published via repo update + deploy). Gallery only shows published episodes.
- **Agent framework**: Custom Python agents on AWS Lambda, Amazon Bedrock Converse API as model provider.
- **AI model**: Claude models via Amazon Bedrock (per-agent configuration).
- **Session management**: AWS AgentCore — shared context across the three-agent pipeline.
- **RAG**: Amazon Bedrock Knowledge Bases backed by S3.
- **Job state**: DynamoDB single-table with TTL.
- **Failure handling**: SQS DLQ on orchestrator Lambda for replay and debugging.
- **Compute**: AWS Lambda only. No ECS, no EC2, no always-on processes.
- **Endpoint**: Lambda Function URL `authType: AWS_IAM`. No API Gateway.
- **Frontend**: TypeScript, no framework, compiled to plain JS.
- **Proxy**: Node.js. Serves the localhost creator UI, reads GitHub username at startup, signs Lambda requests, and may perform signed local-only draft reads from S3 so localhost can preview and download generated episodes.
- **IaC**: AWS CDK (TypeScript). Single `LinionsStack`. Includes `BucketDeployment` to upload the compiled public viewer site to S3 on `cdk deploy`.
- **Animation**: Pure SVG/CSS. No canvas, no WebGL, no animation libraries.
- Anyone who clones this repo can deploy a fully working system with only their own AWS account and Bedrock access.

---

## 8. AWS services (LinionsStack)

| Service | Purpose |
|---------|---------|
| Amazon Bedrock | Claude model invocations for all agents (per-agent model configuration) |
| AWS AgentCore | Shared session memory across the three-agent pipeline |
| Bedrock Knowledge Bases | RAG — Linai character knowledge |
| Amazon S3 — episodes | Stores episode artifacts under `episodes/{username}/{uuid}/` and `drafts/{username}/{uuid}/` |
| Amazon S3 — knowledge base | RAG source documents |
| Amazon CloudFront | CDN + HTTPS — serves the public viewer site and episode files |
| AWS Lambda — generate | Accepts prompt, reads username, creates job, triggers orchestrator |
| AWS Lambda — orchestrator | Runs agent pipeline, generates thumbnail, writes to drafts/ |
| AWS Lambda — status | DynamoDB GetItem only — returns job state to polling browser |
| Lambda Function URL | IAM-secured HTTPS endpoint for generate and status Lambdas |
| Amazon SQS (DLQ) | Captures failed orchestrator jobs for replay and debugging |
| Amazon DynamoDB | Job state tracking with TTL |
| Amazon CloudWatch Logs | Lambda execution and agent call logs |
| AWS CDK | Infrastructure as code |
> Every developer deploys this same stack to their own AWS account.
> Each deployment serves its own public viewer site for its own published episodes.
> A future owner-managed canonical gallery and contribution workflow are planned for v2.
