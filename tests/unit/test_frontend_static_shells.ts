import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";

const repoRoot = resolve(import.meta.dirname, "../..");

function readPublicFile(relativePath: string): string {
  return readFileSync(resolve(repoRoot, relativePath), "utf-8");
}

function assertPlayerIframeDoesNotAllowScripts(html: string, label: string): void {
  assert.match(
    html,
    /<iframe[\s\S]*?id="player-frame"[\s\S]*?sandbox=""/,
    `${label} must keep the player iframe sandboxed without extra permissions`,
  );
  assert.doesNotMatch(
    html,
    /<iframe[\s\S]*?id="player-frame"[\s\S]*?sandbox="[^"]*allow-scripts/,
    `${label} must not reintroduce allow-scripts on the player iframe`,
  );
}

test("public viewer shell keeps the player iframe fully sandboxed", () => {
  const html = readPublicFile("frontend/public/index.html");
  assertPlayerIframeDoesNotAllowScripts(html, "frontend/public/index.html");
});

test("studio shell keeps the player iframe fully sandboxed", () => {
  const html = readPublicFile("frontend/public/studio.html");
  assertPlayerIframeDoesNotAllowScripts(html, "frontend/public/studio.html");
});
