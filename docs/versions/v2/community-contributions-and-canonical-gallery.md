# Plan: Community Contributions and Canonical Gallery

> Status: planned for v2
> Scope: contributor workflow, owner-managed canonical gallery, PR validation, deploy automation

---

## Problem

V1 intentionally separates the product into two surfaces:

- `localhost:3000` is a local creator studio
- CloudFront is a public viewer site only

That keeps v1 focused and avoids shipping creator controls publicly, but it also means there
is no built-in way yet for one developer to submit a published episode to an owner-managed
canonical gallery.

---

## Goal

- A developer can publish an episode to their own deployment in v1, then contribute it to an
  owner-managed canonical gallery in v2.
- The contribution path is secure, deterministic, and reviewable through GitHub PRs.
- The public CloudFront viewer remains viewer-only; contribution tooling stays in local/dev flows
  and repository automation.
- The owner stays the sole approver of what appears in the canonical gallery.

---

## V2 scope

### 1. Local creator handoff

After a successful publish in the localhost creator UI:

- show a `Contribute` button
- keep `Share` pointing to the contributor's own public story URL
- keep the public CloudFront viewer free of contribution controls

The `Contribute` button should launch a guided GitHub-based flow, not expose raw repo steps
without validation.

### 2. Contribution helper script

Add `scripts/prepare-contribution.sh` to:

- validate the published episode JSON with the same schema and validators used in CI
- verify `contentHash`
- verify the episode path matches the contributor identity
- copy the episode into `episodes/{username}/{uuid}.json`
- update `episodes/index.json`
- print the next git commands clearly

### 3. PR validation workflow

Add `.github/workflows/validate-pr.yml` for PRs that touch `episodes/`.

Checks:

- episode JSON schema valid
- SVG linter passes
- `contentHash` matches
- path prefix matches `github.actor`
- file size is within limits
- exactly one new episode per PR
- zero AWS credentials in the workflow

### 4. Canonical gallery deploy workflow

Add `.github/workflows/deploy.yml` for merges to `main`.

Responsibilities:

- assume an OIDC role scoped only to the owner's S3 destination
- upload the merged episode JSON to the owner's `episodes/` prefix
- re-extract and upload the thumbnail with `pipeline/media/thumbnail.py`
- upload the updated `episodes/index.json`
- invalidate `/episodes/index.json` in the owner's CloudFront distribution

### 5. Attribution and metadata

The canonical gallery should preserve contributor attribution:

- contributor username visible on gallery cards
- contributor username visible on the public story page
- no mutation of episode authorship during contribution

### 6. Security model

Defense in depth remains required:

- SVG sanitisation before any storage or serving
- DOM escaping in the public viewer
- GitHub workflow with no AWS access on validation
- deploy role restricted to the owner destination only
- owner approval required before anything reaches the canonical gallery

---

## Non-goals

- Public episode generation from CloudFront
- Public upload forms
- Automatic publishing from a contributor's AWS account into the owner's S3 without review
- Viewer accounts or contributor accounts

---

## Acceptance criteria

- A developer can publish locally, click `Contribute`, and open a valid PR with the correct episode payload.
- Invalid episodes fail in CI before merge.
- A merged PR updates the owner's canonical gallery and thumbnail in S3.
- The owner's CloudFront gallery shows the newly merged episode after invalidation.
- The public viewer remains viewer-only throughout the entire workflow.
