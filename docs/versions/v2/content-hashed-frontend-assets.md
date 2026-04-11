# Content-Hashed Frontend Assets

Replace fixed-name JS and CSS files (`viewer.js`, `app.css`, etc.) with content-hashed
filenames (`viewer.abc123.js`) so browsers cache assets indefinitely and get fresh files
automatically after each deploy — without manual cache-busting.

## Why this is needed

Currently `index.html` references `/viewer.js` and `/app.css` by fixed name. CloudFront
and browsers cannot safely cache these long-term because there is no signal that the content
changed. Setting aggressive cache TTLs today would cause users to see stale code after a
deploy. Content hashing makes each build's output uniquely named, so:

- Hashed JS/CSS can be cached forever (`Cache-Control: max-age=31536000, immutable`).
- `index.html` is served with `Cache-Control: no-cache` so users always get the latest shell
  pointing to the correct hashed filenames.

## Why `tsc` alone cannot do this

The JS modules import each other by relative path (e.g. `import { PlayerController } from
"./player.js"`). If individual files are renamed to hashed versions, every import path inside
every file must be rewritten to match. `tsc` does not do this. A bundler is required.

## Required change: replace `tsc` with Vite

Vite handles everything in one step:

- Compiles TypeScript.
- Rewrites cross-module import paths.
- Hashes output filenames.
- Regenerates `index.html` (and `studio.html`) to reference the hashed names.
- Emits a `manifest.json` for inspection.

`copy-public.mjs` is largely superseded — Vite's output directory replaces `dist-public/`
and `dist-studio/`. The `generate-build-config.mjs` pre-step can stay as-is; it writes
`src/config.ts` before the build runs.

### Vite entry points

Two HTML entry points must be configured so each gets its own hashed bundle:

- `public/index.html` → viewer shell
- `public/studio.html` → studio shell

Shared modules (`player.ts`, `episode-loader.ts`, etc.) are automatically split into a
shared chunk by Vite's rollup code-splitting.

## CDK deploy changes

Two changes are needed in `linions-stack.ts`:

**1. Cache-Control headers**

`BucketDeployment` must set different headers per file type:

- Hashed JS and CSS: `Cache-Control: max-age=31536000, immutable`
- `index.html` and `studio.html`: `Cache-Control: no-cache, must-revalidate`
- `favicon.svg`, `player-frame.css`: `Cache-Control: max-age=86400`

CDK's `s3deploy.BucketDeployment` supports per-deployment `cacheControl` but not
per-file rules in a single deployment. The cleanest approach is two `BucketDeployment`
constructs: one for `*.js`/`*.css` hashed assets, one for `index.html`/`studio.html`.

**2. Keep `prune: false` for hashed assets**

Do not set `prune: true` on the hashed-asset deployment. Old hashed files must remain
in S3 for users who have a cached `index.html` pointing to previous hashes. Because
hashed filenames are unique, accumulation is bounded by the number of deploys, not by
user traffic.

`prune: true` is already used for `EpisodesDeployment` and `KnowledgeBaseDeployment`
— those are unaffected.

## What does not change

- The `generate-build-config.mjs` pre-step.
- All TypeScript source files.
- The S3 bucket and CloudFront distribution structure.
- The `episodes/` and `knowledge-base/` deploy logic.
- The studio pipeline and Lambda code.

## Implementation checklist

- [ ] Add Vite and `@vitejs/plugin-legacy` (if broad browser support needed) to
  `frontend/package.json`.
- [ ] Write `frontend/vite.config.ts` with both HTML entry points and `build.manifest: true`.
- [ ] Update `frontend/package.json` `build` script: run `generate-build-config.mjs` then
  `vite build` (drop the `tsc` and `copy-public.mjs` steps).
- [ ] Remove or repurpose `frontend/scripts/copy-public.mjs`.
- [ ] Update CDK `FrontendDeployment` to split into two `BucketDeployment` constructs with
  correct `cacheControl` per asset type.
- [ ] Verify `studio.html` receives its own entry-point bundle and is deployed correctly.
- [ ] Smoke-test viewer and studio after deploy: open DevTools → Network, confirm JS/CSS
  responses carry `Cache-Control: max-age=31536000, immutable` and `index.html` carries
  `Cache-Control: no-cache`.
