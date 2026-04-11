<!-- AI ASSISTANT: Read in this order before writing any code:
  1. REQUIREMENTS.md
  2. STANDARDS.md  
  3. DESIGN.md
  4. PHASES.md
  Then confirm which phase you are implementing before starting. -->
  
# Standards — Linions

> Version 2.4 | Status: approved
>
> Read this document at the start of every implementation session.
> A phase is not done until every item in §9 (Definition of done) is checked.

---

## 1. Core principles

**Explicit over implicit.** If something is not obvious from reading the code, make it obvious
through naming, structure, or a short comment. No magic.

**Fail loudly and early.** Every error surfaces immediately with a message that says exactly
what went wrong and where. Silent failures and generic error messages are bugs.

**One source of truth.** A value, rule, or contract lives in exactly one place.

**AI output is untrusted input.** Every model response passes through a deterministic validator
before it is used, stored, or rendered. Nothing from an LLM goes anywhere raw.

**No hidden fallbacks.** No silent fallback to a default model, prompt, config value, or
behavior. Any fallback must be explicit, logged at WARN level, and ideally test-covered.

**Design both happy paths and fail paths.** Every workflow must make the success path,
expected domain failures, and unexpected infrastructure failures explicit in code and tests.
Shipping only the happy path is incomplete.

---

## 2. Code style

### 2.1 Python (pipeline, validators, proxy)

- Python 3.11+. Type hints mandatory on every function signature.
- `ruff` for linting and formatting. Config in `pyproject.toml`.
- Dependencies pinned in `requirements.lock`. Upgrades in dedicated PRs.
- Split functions when they have multiple responsibilities, deep nesting, or poor testability.
  Use judgment — 40 lines is a useful smell, not a hard rule.
- File length is a smell, not a violation. Split when a file owns multiple concerns.
- Prefer focused modules over "god files". If one file mixes handler translation,
  orchestration flow, and external service adapters, split it.
- Write code with separation of concerns, simplicity, and maintainability as
  first principles. If structure is getting hard to explain, it is probably time
  to split responsibilities.
- No `import *`. All imports explicit.
- All imports go at the top of the file — never inside a function or test body.
- All public functions have a docstring.
- Exceptions must always include a message.
- Leading underscore on a name signals "private to this module". Never prefix a function
  with `_` if it is imported by another module. Shared utilities must have public names.

**Documentation requirements:**
- Every public function must have a docstring: one-sentence description,
  input types, output type, exceptions raised.
- Every validator rule must have an inline comment explaining what it checks
  and why (not just what the code does — why the rule exists).
- Every config value must have an inline comment.
- No function may be merged without its docstring. This applies to AI-generated
  code — if the AI omits docstrings, reject the output and ask again.
  
### 2.2 TypeScript (frontend, CDK, proxy)

- Strict mode: `"strict": true` in `tsconfig.json`. Not negotiable.
- `eslint` with the TypeScript plugin. Config in `.eslintrc.json`.
- No `any`. Use `unknown` and narrow explicitly.
- No non-null assertions (`!`) without a comment explaining why it is safe.
- All async functions handle errors — no unhandled promise rejections.
- Node dependencies locked in `package-lock.json`.

### 2.3 Naming conventions

| Thing | Convention |
|-------|-----------|
| Python files, functions, variables | `snake_case` |
| Python classes, Pydantic models | `PascalCase` |
| Python constants | `UPPER_SNAKE_CASE` |
| TypeScript files | `kebab-case` |
| TypeScript functions, variables | `camelCase` |
| TypeScript types, interfaces | `PascalCase` |
| CDK constructs | `PascalCase` |
| Environment variables | `UPPER_SNAKE_CASE` |
| S3 keys, DynamoDB attributes | `kebab-case` |

### 2.4 Configuration

Tunable, shared, business-significant, or security-sensitive values live in `config.py`
(Python pipeline) and `config.ts` (CDK + frontend). These are the only places where
default values are defined.

Model IDs, prompt template paths, retry counts, timeouts, file size limits, and all
cost-boundary values must always be in config — never inline.

If a config value reads from an environment variable with a fallback default, that fallback
must be logged at WARN level (per §1 "No hidden fallbacks"). Pattern to follow:

```python
_DEFAULT = "some-default-value"
_from_env = os.getenv("MY_VAR")
if _from_env is None:
    print(f"WARN [config] MY_VAR not set; using default: {_DEFAULT}", file=sys.stderr)
MY_VAR: str = _from_env or _DEFAULT
```

```python
# config.py — document every value
WALK_DURATION_SECONDS: int = 8          # Default approach-float time between obstacles
MAX_EPISODE_DURATION_SECONDS: int = 90
MIN_OBSTACLE_ACTS: int = 2
MAX_OBSTACLE_ACTS: int = 2
MIN_CHOICES_PER_ACT: int = 2
MAX_CHOICES_PER_ACT: int = 2
MAX_AGENT_RETRY_COUNT: int = 2
POLLING_INTERVAL_SECONDS: int = 3
JOB_TTL_SECONDS: int = 86400           # 24 hours
MAX_SVG_FILE_SIZE_BYTES: int = 512_000
MAX_EPISODE_JSON_SIZE_BYTES: int = 5_242_880
MAX_INPUT_TOKENS_PER_STAGE: int = 8_000
MAX_OUTPUT_TOKENS_DIRECTOR_STAGE: int = 4_000
MAX_OUTPUT_TOKENS_ANIMATOR_STAGE: int = 12_000
MAX_OUTPUT_TOKENS_DRAWING_STAGE: int = 12_000
MAX_OUTPUT_TOKENS_RENDERER_STAGE: int = 12_000
MAX_PROMPT_LENGTH_CHARS: int = 500
# Director/Animator/Renderer use Sonnet; Drawing uses Opus for highest SVG quality.
# Each agent reads its own env var; warn on fallback per §1.
BEDROCK_MODEL_ID_DIRECTOR: str = "eu.anthropic.claude-sonnet-4-6"
BEDROCK_MODEL_ID_ANIMATOR: str = "eu.anthropic.claude-sonnet-4-6"
BEDROCK_MODEL_ID_DRAWING: str = "eu.anthropic.claude-opus-4-6-v1"
BEDROCK_MODEL_ID_RENDERER: str = "eu.anthropic.claude-sonnet-4-6"
BEDROCK_CONNECT_TIMEOUT_SECONDS: int = 10
AGENT_CALL_TIMEOUT_SECONDS: int = 120
JOB_DEADLINE_SECONDS: int = 120
CANVAS_WIDTH: int = 800
CANVAS_HEIGHT: int = 200
GROUND_LINE_Y: int = 160               # Invisible floor coordinate
SUPPORT_Y_TOLERANCE_PX: int = 5        # Max pixels grounded poses may drift vertically from support_y
HANDOFF_SUPPORT_Y_TOLERANCE_PX: int = 2 # Max pixels a handoff pose may drift vertically from support_y
HANDOFF_CHARACTER_X: int = 320
HANDOFF_X_TOLERANCE_PX: int = 5
```

---

## 3. Architecture standards

### 3.1 Agent rules

- Each agent (Director, Animator, Renderer) lives in its own folder under `pipeline/agents/`
  with its own `agent.py`, `prompt.txt`, and `tests/` subfolder.
- Each agent has one primary entrypoint: `run(input: AgentInput) -> AgentOutput`.
- Agents may call their assigned model dependency (Bedrock Converse API, AgentCore session).
- Agents must not do persistence, orchestration, cross-agent calls, or infrastructure side
  effects. The orchestrator owns all I/O.
- AgentCore session is created by the orchestrator and passed into each agent.
- Agent I/O must be fully typed Pydantic models. No raw dicts between stages.
- Pydantic models live under `pipeline/models/` and are grouped by bounded context
  (`director`, `animator`, `renderer`, `episode`, `shared`). Avoid a catch-all
  `models.py` file once model count grows.
- Prompt templates live in each agent's own folder. Prompt construction is deterministic
  from typed input. Prompt changes affecting output contract require model, validator,
  fixture, and doc updates.
- Every `pipeline/agents/` subdirectory must have an `__init__.py` to be a proper package,
  consistent with all other `pipeline/` packages.
- Prompt file paths must use `Path(__file__).parent / "prompt.txt"` — never a string
  relative to CWD. The CWD is not reliable across Lambda, tests, and local runs.

```python
class DirectorAgent:
    def run(self, input: DirectorInput) -> DirectorOutput:
        context = self._query_rag(input.rag_context, input.session)  # allowed
        raw = self._call_llm(input.prompt, context, input.session)   # allowed
        return DirectorOutput.model_validate(raw)
        # NOT allowed: s3.put(), dynamo.update(), AnimatorAgent().run()
```

### 3.2 Validator rules

- Validators are pure, stateless functions. No class instances, no global state.
- Return `ValidationResult(is_valid, errors)` for domain failures.
  Raise exceptions for programmer bugs or corrupted internal state.

```python
@dataclass
class ValidationResult:
    is_valid: bool
    errors: list[str]

def validate_script(script: dict) -> ValidationResult:
    errors: list[str] = []
    # domain checks → append to errors
    # programmer bug → raise immediately
    return ValidationResult(is_valid=len(errors) == 0, errors=errors)
```

### 3.3 Orchestrator rules

- The orchestrator is the only component that touches agents, validators, DynamoDB, S3,
  and the thumbnail extractor. It is the sole integration layer.
- Orchestrator Lambda flow code lives under `pipeline/lambdas/orchestrator/`. The handler,
  runtime wiring, orchestration flow, and external adapters may be separate modules there,
  but they should stay scoped to that lambda package instead of leaking back into the
  pipeline root.
- External integration adapters (for example Bedrock Knowledge Base retrieval) live in a
  dedicated file or module with that single responsibility.
- Before starting each agent, update DynamoDB with the current stage label.
- Do not proceed past a failed validation. Re-prompt with exact errors (max
  `MAX_AGENT_RETRY_COUNT`). On exhaustion mark FAILED and exit cleanly.
- No episode JSON or thumbnail shall be written to S3 until the full pipeline succeeds.
- S3 writes follow this explicit sequence: write episode JSON first, then write thumbnail.
  If the thumbnail write fails after the episode JSON has been written, the orchestrator
  must delete the episode JSON from S3 before marking the job FAILED. No dangling episode
  files without thumbnails shall exist in S3.
- Large `run()` methods are a smell. Once a workflow has multiple failure paths or stages,
  split it into named helper methods so each step is testable in isolation.

### 3.4 Job state machine

Legal transitions only — anything else fails loudly and logs ERROR:

```
create (PENDING)     — condition: item must not exist
PENDING → GENERATING — condition: status = PENDING
GENERATING → DONE    — condition: status = GENERATING
GENERATING → FAILED  — condition: status = GENERATING
```

All transitions use DynamoDB `ConditionExpression`. `DONE` and `FAILED` are terminal.
Orchestrator checks `status = GENERATING` before starting work — protects against
AWS Lambda async retry double-processing.

### 3.5 Retry, backoff, and timeout

| Rule | Value |
|------|-------|
| Max retries per agent call | `MAX_AGENT_RETRY_COUNT` (config) |
| Backoff | Exponential with jitter: `base * 2^attempt + random(0, 1)s` |
| Retryable | Model timeout, throttling, validation failure |
| Non-retryable | Schema version mismatch, budget ceiling exceeded, terminal job state |
| Per-stage timeout | `AGENT_CALL_TIMEOUT_SECONDS` (config) |
| Overall job deadline | `JOB_DEADLINE_SECONDS` (config) |

### 3.6 CDK stack rules

- One stack only: `LinionsStack`. No PublicStack/GenerationStack split.
- S3 buckets: `blockPublicAccess: BLOCK_ALL`, `encryption: S3_MANAGED`, `enforceSSL: true`.
- Lambda: explicit `timeout`, `memorySize`, `description`, scoped IAM role.
  No `*` resources in any policy statement.
- DynamoDB: `billingMode: PAY_PER_REQUEST`, `timeToLiveAttribute: 'ttl'`.
- CloudFront: `minimumProtocolVersion: TLS_V1_2_2021`, OAC (not OAI).
- No hardcoded account IDs, region strings, or ARNs — use CDK tokens.
- Use CDK enum values directly (`logs.RetentionDays.ONE_MONTH`). Do not write wrapper
  functions that map plain numbers to enums — that indirection only introduces fragility.

### 3.7 Lambda handler rules

- Handlers live under `pipeline/lambdas/<lambda-name>/handler.py`. Shared Lambda code lives
  under `pipeline/lambdas/shared/`.
- Each Lambda bundle installs only the dependencies it needs and copies only the pipeline
  code paths it imports at runtime.
- API-facing handlers (Function URL): catch unexpected errors, log structured context,
  return safe error response. Do not swallow silently.
- Async/internal handlers (orchestrator): propagate unhandled exceptions — AWS Lambda async
  retry and DLQ semantics depend on this. Do not wrap in blanket try/except.
- Every handler logs structured context before any error path.
- Every externally triggered handler documents its idempotency strategy inline.
- Reuse AWS SDK clients across warm invocations with module-level or cached factories.
  Do not create fresh `boto3.client(...)` instances inside every handler invocation unless
  there is a documented reason.

### 3.8 Proxy rules

- The proxy's only AWS interactions are: sign and forward requests to Lambda Function URLs.
- The proxy must not call S3, DynamoDB, or any other AWS SDK method directly.
- The proxy reads the GitHub username once at startup. If it cannot be determined, it
  refuses to start with a clear, actionable error message.
- The proxy logs every proxied request: method, path, status, duration ms.

### 3.9 Frontend rules

- No `innerHTML` with untrusted content. `textContent` for text, `createElement` +
  `setAttribute` for elements.
- Episode SVG renders inside `<iframe sandbox>` — never injected into main DOM.
- Episode player uses an explicit TypeScript union type for all states — not boolean flags.

```typescript
type PlayerState =
  | { status: 'idle' }
  | { status: 'polling'; jobId: string }
  | { status: 'playing'; episode: Episode; actIndex: number }
  | { status: 'choosing'; episode: Episode; actIndex: number }
  | { status: 'done' }
  | { status: 'error'; message: string };
```

- Handle all loading, error, and empty states explicitly.

---

## 4. Security standards

| ID | Rule |
|----|------|
| SEC-01 | No secret, API key, credential, or account ID in any committed file. Use `.env` (gitignored) locally and Lambda environment variables in AWS. |
| SEC-02 | `.gitignore` must include: `.env`, `*.env`, `cdk.context.json`, `cdk.out/`, `logs/`, `__pycache__/`, `node_modules/`. |
| SEC-03 | SVG linter strips: `<script>`, `<iframe>`, `<object>`, `<embed>`, `<foreignObject>`; attributes with `javascript:` or `data:`; `href`/`src`/`xlink:href` pointing to external URLs. `data:` URIs disallowed entirely. |
| SEC-04 | Gallery page uses `textContent` for all episode metadata. Episode SVG inside `<iframe sandbox>` only. |
| SEC-05 | Lambda Function URLs: `authType: AWS_IAM`. Enforced in CDK — cannot be deployed open. |
| SEC-06 | GitHub Actions OIDC role: `sub` condition scoped to this specific repo and branch. |
| SEC-07 | PR validation workflow: `permissions: contents: read` only. Zero AWS credentials. |
| SEC-08 | Deploy workflow: `id-token: write` and `contents: read` only. |
| SEC-09 | No `*` resource in any IAM policy statement. Every statement names a specific ARN. |
| SEC-10 | S3 bucket policy explicitly denies all `s3:GetObject` not from the CloudFront OAC principal. |
| SEC-11 | CloudFront sets: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self' data:; img-src 'self' data:; object-src 'none'; base-uri 'self'`. |

---

## 5. Schema and data standards

### 5.1 Schema versioning

Every episode JSON includes `schemaVersion` at root. Current version: `"1.0"`.
Breaking changes require a version bump. Old versions rejected with a clear error.
Fixtures and DESIGN.md must be updated with every schema change.

### 5.2 Artifact integrity

`contentHash` is SHA-256 of the JSON body with only the `contentHash` field set to `null`
before hashing. `username` is always present from generation time and is included in the hash.
The orchestrator computes and embeds the hash before the S3 write.
The PR validation workflow re-verifies the hash before allowing merge.

### 5.3 Cost guardrails

Orchestrator enforces hard ceilings — exceed any → mark FAILED immediately, no retry:

- Input tokens per stage: `MAX_INPUT_TOKENS_PER_STAGE`
- Output tokens per stage: the stage-specific `MAX_OUTPUT_TOKENS_*_STAGE` ceiling
- SVG file size: `MAX_SVG_FILE_SIZE_BYTES`
- Episode JSON size: `MAX_EPISODE_JSON_SIZE_BYTES`
- Overall job deadline: `JOB_DEADLINE_SECONDS`

---

## 6. Testing standards

### 6.1 What must be tested

| Component | Coverage requirement |
|-----------|---------------------|
| All validators + SVG linter | 100% — every rule has passing and failing test |
| `thumbnail.py` | All SVG shapes: with animations (strips cleanly), without animations, malformed XML (raises) |
| Agent Pydantic schemas | All required fields, optional fields, type constraints |
| Orchestrator retry logic | Happy path, 1 retry, exhausted retries, budget ceiling hit |
| Job state transitions | All legal transitions; all illegal transitions fail loudly |
| Frontend state machine | All transitions and error paths |
| CDK stack | Security-critical properties asserted explicitly (not just snapshot) |

### 6.2 Test rules

- No real HTTP, AWS, or Bedrock calls in tests. All external dependencies mocked.
- Test names: `test_validate_script_fails_when_act_count_exceeds_maximum`.
- Fixtures in `tests/fixtures/` — `valid_episode.json` plus one file per failure mode.
- Tests are the executable specification of DESIGN.md contracts. Contract changes → tests first.

### 6.3 Running tests

```bash
pytest tests/unit/ -v
LINIONS_FORCE_CDK_SYNTH=1 pytest tests/cdk/ -v
pytest --cov=pipeline --cov-report=term-missing tests/unit/
```

**CDK security tests must not be silently skipped.** `tests/cdk/` contains assertion tests
that only run when a synthesized template is present. Always set `LINIONS_FORCE_CDK_SYNTH=1`
when running CDK tests — this triggers `cdk synth` inside the test fixture when `cdk.out/`
is absent. Running `pytest tests/cdk/` without this flag produces zero failures *and zero
assertions*, which is a false pass.

Phase gate not passed until `pytest` exits 0, coverage requirements are met, and CDK tests
were run with `LINIONS_FORCE_CDK_SYNTH=1` (no skipped tests).

---

## 7. Observability standards

### 7.1 Log format

Human-readable single-line structured logs using `key=value` pairs, implemented in
`pipeline/shared/logging.py`. Example:

```
2026-03-27T10:00:00.123Z INFO [job-abc123] [DirectorAgent.agent_call_complete] durationMs=4823 inputTokens=1204 outputTokens=876 retryCount=0 validationResult=pass
```

### 7.2 Log levels and rules

Log levels: `INFO` normal progress, `WARN` retries/fallbacks, `ERROR` terminal failures,
`DEBUG` full prompt/response (`VERBOSE=true` only).

Never log credentials, tokens, or full SVG content (log byte size + hash instead).

---

## 8. Repository and CI standards

### 8.1 Branch and commit rules

- No direct push to `main`. All changes via PR.
- Conventional commits: `feat(director-agent): add RAG query`.
- Types: `feat`, `fix`, `test`, `docs`, `chore`, `refactor`.

### 8.2 Required CI checks

- `ruff check` + `ruff format --check` — zero violations.
- `eslint` — zero violations.
- `pytest` — all tests pass, coverage met.
- CDK synth — stack synthesizes without error.
- Episode PR validation — schema, SVG lint, `contentHash` valid, path == `github.actor`,
  size within limit, one episode per PR. Zero AWS credentials.

### 8.3 Deploy rules

- Deploy only on merge to `main`. OIDC — no stored credentials.
- CI re-extracts thumbnail using `thumbnail.py` and uploads it alongside the episode JSON.

### 8.4 What must never be committed

`.env`, `cdk.context.json`, `cdk.out/`, `logs/`, `__pycache__/`, `node_modules/`,
any file larger than 5 MB.

**`.env` files in subdirectories:** The root `.gitignore` matches `.env` in all subdirectories,
but add an explicit `proxy/.env` entry as defense-in-depth. After any `.gitignore`
restructuring, verify coverage with: `git check-ignore -v proxy/.env` — it must return a match.

**Committed templates:** Every directory that requires a `.env` file must have a committed
`.env.example` template with placeholder values and a comment directing developers to
`scripts/setup-env.sh`. Never commit real URLs, account IDs, or credentials in the example.

---

## 9. Definition of done

- [ ] Code compiles with zero errors and warnings.
- [ ] `ruff` and `eslint` pass clean.
- [ ] All tests pass. Coverage in §6.1 met.
- [ ] No magic numbers or strings outside config (per §2.4 guidance).
- [ ] All functions have type hints / explicit TypeScript types.
- [ ] All security rules in §4 satisfied.
- [ ] Structured logs emitted correctly on all code paths including error paths.
- [ ] Idempotency strategy documented inline for every externally triggered handler.
- [ ] DESIGN.md updated if any agent contract, JSON schema, or state machine changed.
- [ ] Phase gate in PHASES.md passes manually.
