import assert from "node:assert/strict";
import test from "node:test";

import {
  buildEpisodePath,
  buildGalleryPath,
  buildLegacyEpisodePath,
  buildStoryPath,
  episodePathToStoryPath,
  parseStoryRoute,
} from "../../frontend/src/routes.js";

test("buildEpisodePath uses the per-episode folder layout", () => {
  assert.equal(
    buildEpisodePath("tester", "episode-123"),
    "episodes/tester/episode-123/episode.json",
  );
});

test("buildLegacyEpisodePath preserves the legacy flat layout for fallback reads", () => {
  assert.equal(
    buildLegacyEpisodePath("tester", "episode-123"),
    "episodes/tester/episode-123.json",
  );
});

test("episodePathToStoryPath parses the new nested episode path", () => {
  assert.equal(
    episodePathToStoryPath("episodes/tester/episode-123/episode.json"),
    buildStoryPath("tester", "episode-123"),
  );
});

test("episodePathToStoryPath still parses legacy flat paths", () => {
  assert.equal(
    episodePathToStoryPath("episodes/tester/episode-123.json"),
    buildStoryPath("tester", "episode-123"),
  );
});

test("episodePathToStoryPath rejects unrelated asset paths", () => {
  assert.equal(episodePathToStoryPath("episodes/tester/episode-123/thumb.svg"), null);
});

test("buildStoryPath keeps the local preview prefix when running under /preview", () => {
  assert.equal(
    buildStoryPath("tester", "episode-123", "/preview/story/existing/example"),
    "/preview/story/tester/episode-123",
  );
});

test("buildGalleryPath keeps the local preview prefix when running under /preview", () => {
  assert.equal(buildGalleryPath("/preview/story/tester/episode-123"), "/preview");
});

test("parseStoryRoute accepts preview-prefixed public viewer URLs", () => {
  assert.deepEqual(parseStoryRoute("/preview/story/tester/episode-123"), {
    username: "tester",
    uuid: "episode-123",
  });
});
