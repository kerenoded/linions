#!/usr/bin/env node
//
// Runs the lightweight TypeScript regression suite used in local development and CI.
//
// This wrapper keeps the command stable while the actual test files stay split by concern:
// - route/state-machine unit tests for browser logic
// - static shell checks for public HTML guarantees such as iframe sandboxing
// - local-tooling regression tests for small TypeScript helpers around the proxy/publish flow
//
// It intentionally uses Node's built-in test runner plus `tsx` so the repo does not need
// a heavier browser-test framework just to cover these small but important invariants.

import { spawnSync } from "node:child_process";
import { resolve } from "node:path";

const majorVersion = Number.parseInt(process.versions.node.split(".")[0] ?? "", 10);

if (!Number.isFinite(majorVersion) || majorVersion < 18) {
  console.error(
    `Frontend tests require Node 18+ because they use the built-in test runner and tsx. Current runtime: ${process.version}.`,
  );
  process.exit(1);
}

const tsxBin = process.platform === "win32" ? "node_modules/.bin/tsx.cmd" : "node_modules/.bin/tsx";
const result = spawnSync(
  resolve(process.cwd(), tsxBin),
  [
    "--test",
    "tests/unit/test_frontend_state_machine.ts",
    "tests/unit/test_frontend_routes.ts",
    "tests/unit/test_frontend_static_shells.ts",
    "tests/unit/test_frontend_network_failures.ts",
    "tests/unit/test_proxy_publish.ts",
  ],
  { stdio: "inherit" },
);

if (result.error) {
  throw result.error;
}

process.exit(result.status ?? 1);
