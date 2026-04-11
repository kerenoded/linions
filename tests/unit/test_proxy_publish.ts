import assert from "node:assert/strict";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import test from "node:test";

import { parsePublishedEpisodeMetadata, publishDraftToRepo } from "../../proxy/publish.ts";

function makeDraftBody(username = "tester", uuid = "episode-123"): string {
  return JSON.stringify({
    username,
    uuid,
    title: "Test Episode",
  });
}

test("parsePublishedEpisodeMetadata returns the repo-managed episode and thumb paths", () => {
  const repoRoot = "/tmp/repo";
  const episodesDir = "/tmp/repo/episodes";

  const metadata = parsePublishedEpisodeMetadata(makeDraftBody(), {
    repoRoot,
    episodesDir,
  });

  assert.equal(metadata.publishedPath, "episodes/tester/episode-123/episode.json");
  assert.equal(metadata.thumbPath, "episodes/tester/episode-123/thumb.svg");
  assert.equal(metadata.absolutePath, "/tmp/repo/episodes/tester/episode-123/episode.json");
  assert.equal(metadata.absoluteThumbPath, "/tmp/repo/episodes/tester/episode-123/thumb.svg");
});

test("publishDraftToRepo removes both episode.json and thumb.svg when build-index fails", async () => {
  const repoRoot = await mkdtemp(join(tmpdir(), "linions-proxy-publish-"));
  const episodesDir = join(repoRoot, "episodes");
  const buildIndexScript = join(repoRoot, "scripts", "build-index.js");
  const draftBody = makeDraftBody("tester", "episode-rollback");
  const expectedEpisodePath = join(episodesDir, "tester", "episode-rollback", "episode.json");
  const expectedThumbPath = join(episodesDir, "tester", "episode-rollback", "thumb.svg");

  await assert.rejects(
    publishDraftToRepo({
      draftBody,
      repoRoot,
      episodesDir,
      buildIndexScript,
      runBuildIndex: async () => {
        mkdirSync(dirname(expectedThumbPath), { recursive: true });
        await writeFile(expectedThumbPath, "<svg/>", "utf-8");
        throw new Error("simulated build-index failure");
      },
    }),
    /Failed to rebuild episodes\/index\.json/,
  );

  assert.equal(existsSync(expectedEpisodePath), false);
  assert.equal(existsSync(expectedThumbPath), false);
});

test("publishDraftToRepo rejects conflicts when a published artifact already exists", async () => {
  const repoRoot = await mkdtemp(join(tmpdir(), "linions-proxy-conflict-"));
  const episodesDir = join(repoRoot, "episodes");
  const buildIndexScript = join(repoRoot, "scripts", "build-index.js");
  const existingEpisodePath = join(episodesDir, "tester", "episode-123", "episode.json");

  mkdirSync(dirname(existingEpisodePath), { recursive: true });
  writeFileSync(existingEpisodePath, "{}", "utf-8");

  await assert.rejects(
    publishDraftToRepo({
      draftBody: makeDraftBody(),
      repoRoot,
      episodesDir,
      buildIndexScript,
    }),
    /Episode already exists/,
  );

  assert.equal((await readFile(existingEpisodePath, "utf-8")).trim(), "{}");
});
