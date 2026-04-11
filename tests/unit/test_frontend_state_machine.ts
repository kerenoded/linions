import assert from "node:assert/strict";
import test from "node:test";

import { transitionPlayerState } from "../../frontend/src/state-machine.js";
import type { Episode } from "../../frontend/src/types.js";

const episode: Episode = {
  schemaVersion: "1.0",
  uuid: "test-uuid",
  username: "tester",
  title: "Test Episode",
  description: "Test description",
  generatedAt: new Date().toISOString(),
  contentHash: "sha256:test",
  actCount: 1,
  acts: [
    {
      actIndex: 0,
      obstacleType: "wall",
      clips: {
        approach:
          '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 200"><g id="linai"/></svg>',
        choices: [
          {
            choiceIndex: 0,
            label: "Go",
            isWinning: true,
            winClip:
              '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 200"><g id="linai"/></svg>',
            failClip: null,
          },
        ],
      },
    },
  ],
};

test("transitions idle to polling", () => {
  const next = transitionPlayerState({ status: "idle" }, { type: "START_POLLING", jobId: "job-1" });
  assert.deepEqual(next, { status: "polling", jobId: "job-1" });
});

test("loads episode to playing", () => {
  const next = transitionPlayerState({ status: "idle" }, { type: "LOAD_EPISODE", episode });
  assert.equal(next.status, "playing");
  if (next.status === "playing") {
    assert.equal(next.actIndex, 0);
    assert.equal(next.episode.uuid, "test-uuid");
  }
});

test("moves to choosing state", () => {
  const next = transitionPlayerState(
    { status: "playing", episode, actIndex: 0 },
    { type: "SHOW_CHOICES", episode, actIndex: 0 },
  );
  assert.equal(next.status, "choosing");
});

test("moves to done state", () => {
  const next = transitionPlayerState(
    { status: "playing", episode, actIndex: 0 },
    { type: "FINISH" },
  );
  assert.deepEqual(next, { status: "done" });
});

test("moves to error state", () => {
  const next = transitionPlayerState(
    { status: "polling", jobId: "job-1" },
    { type: "FAIL", message: "boom" },
  );
  assert.deepEqual(next, { status: "error", message: "boom" });
});

test("resets to idle state", () => {
  const next = transitionPlayerState(
    { status: "error", message: "boom" },
    { type: "RESET" },
  );
  assert.deepEqual(next, { status: "idle" });
});
