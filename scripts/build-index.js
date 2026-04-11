#!/usr/bin/env node
//
// Rebuilds the repo-managed public episode index from the checked-in `episodes/` tree.
//
// Responsibilities:
// - walk every published `episodes/<username>/<uuid>/episode.json`
// - validate the published episode artifact before it is accepted into the gallery
// - regenerate `thumb.svg` from the first approach clip for each episode
// - write `episodes/index.json` sorted newest-first for the public viewer
//
// This script is intentionally the single publication gate for repo-managed content.
// Running it locally or in CI catches malformed paths, invalid JSON/schema, and unsafe
// embedded SVG before those artifacts are shipped to CloudFront.

import { spawnSync } from "node:child_process";
import { mkdir, readdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const REPO_ROOT = path.resolve(__dirname, "..");
const EPISODES_DIR = path.join(REPO_ROOT, "episodes");
const INDEX_PATH = path.join(EPISODES_DIR, "index.json");
const PYTHON_BIN = process.env.PYTHON_BIN || "python3";
const THUMBNAIL_SCRIPT = [
  "import sys",
  "from pipeline.media.thumbnail import extract_thumbnail",
  "svg = sys.stdin.read()",
  "sys.stdout.write(extract_thumbnail(svg))",
].join("\n");
const PUBLISHED_EPISODE_VALIDATION_SCRIPT = [
  "import sys",
  "from pipeline.shared.published_episode import validate_published_episode_json",
  "absolute_path = sys.argv[1]",
  "raw_json = sys.stdin.read()",
  "try:",
  "    validate_published_episode_json(raw_json)",
  "except Exception as error:",
  "    print(f'{absolute_path}: {error}', file=sys.stderr)",
  "    raise SystemExit(1)",
].join("\n");

/**
 * @typedef {{
 *   schemaVersion: string;
 *   uuid: string;
 *   username: string;
 *   title: string;
 *   description: string;
 *   generatedAt: string;
 *   contentHash: string;
 *   actCount: number;
 *   acts: Array<{
 *     actIndex: number;
 *     obstacleType: string;
 *     clips: {
 *       approach: string;
 *       choices: Array<{
 *         choiceIndex: number;
 *         label: string;
 *         isWinning: boolean;
 *         winClip: string | null;
 *         failClip: string | null;
 *       }>;
 *     };
 *   }>;
 * }} Episode
 */

/**
 * @typedef {{
 *   path: string;
 *   thumbPath: string;
 *   username: string;
 *   title: string;
 *   description: string;
 *   createdAt: string;
 * }} GalleryEntry
 */

async function walkEpisodeJsonFiles(rootDir) {
  /** @type {string[]} */
  const collected = [];

  async function visit(currentDir) {
    const entries = await readdir(currentDir, { withFileTypes: true });
    for (const entry of entries) {
      const absolutePath = path.join(currentDir, entry.name);
      if (entry.isDirectory()) {
        await visit(absolutePath);
        continue;
      }

      if (!entry.isFile() || !entry.name.endsWith(".json") || entry.name === "index.json") {
        continue;
      }

      collected.push(absolutePath);
    }
  }

  await visit(rootDir);
  collected.sort((left, right) => left.localeCompare(right));
  return collected;
}

/**
 * @param {Episode} episode
 * @param {string} absolutePath
 */
function parseEpisodeJson(rawEpisodeJson, absolutePath) {
  try {
    return JSON.parse(rawEpisodeJson);
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw new Error(`Episode JSON is malformed: ${absolutePath}. ${detail}`);
  }
}

function validatePublishedEpisode(rawEpisodeJson, absolutePath) {
  const result = spawnSync(PYTHON_BIN, ["-c", PUBLISHED_EPISODE_VALIDATION_SCRIPT, absolutePath], {
    cwd: REPO_ROOT,
    input: rawEpisodeJson,
    encoding: "utf-8",
  });

  if (result.status !== 0) {
    const stderr = result.stderr?.trim();
    throw new Error(stderr || `published episode validation failed: ${absolutePath}`);
  }
}

function extractThumbnailSvg(approachSvg) {
  const result = spawnSync(PYTHON_BIN, ["-c", THUMBNAIL_SCRIPT], {
    cwd: REPO_ROOT,
    input: approachSvg,
    encoding: "utf-8",
  });

  if (result.status !== 0) {
    const stderr = result.stderr?.trim();
    throw new Error(stderr || "thumbnail extraction failed");
  }

  return result.stdout;
}

/**
 * @param {string} absoluteJsonPath
 * @param {Episode} episode
 * @returns {Promise<GalleryEntry>}
 */
async function buildGalleryEntry(absoluteJsonPath, episode) {
  const relativeJsonPath = path.relative(REPO_ROOT, absoluteJsonPath).split(path.sep).join("/");
  const expectedJsonPath = `episodes/${episode.username}/${episode.uuid}/episode.json`;
  if (relativeJsonPath !== expectedJsonPath) {
    throw new Error(
      `Episode path must match username/uuid convention. Expected ${expectedJsonPath}, got ${relativeJsonPath}`,
    );
  }

  const thumbPath = `episodes/${episode.username}/${episode.uuid}/thumb.svg`;
  const absoluteThumbPath = path.join(REPO_ROOT, thumbPath);
  const thumbnailSvg = extractThumbnailSvg(episode.acts[0].clips.approach);

  await mkdir(path.dirname(absoluteThumbPath), { recursive: true });
  const existingThumb = await readFile(absoluteThumbPath, "utf-8").catch(() => null);
  if (existingThumb !== thumbnailSvg) {
    await writeFile(absoluteThumbPath, thumbnailSvg, "utf-8");
  }

  return {
    path: expectedJsonPath,
    thumbPath,
    username: episode.username,
    title: episode.title,
    description: episode.description,
    createdAt: episode.generatedAt,
  };
}

function sortEntriesNewestFirst(left, right) {
  const leftTs = Date.parse(left.createdAt);
  const rightTs = Date.parse(right.createdAt);
  const safeLeft = Number.isNaN(leftTs) ? 0 : leftTs;
  const safeRight = Number.isNaN(rightTs) ? 0 : rightTs;

  if (safeLeft !== safeRight) {
    return safeRight - safeLeft;
  }

  return left.path.localeCompare(right.path);
}

async function main() {
  const episodeJsonPaths = await walkEpisodeJsonFiles(EPISODES_DIR);
  /** @type {GalleryEntry[]} */
  const entries = [];

  for (const absoluteJsonPath of episodeJsonPaths) {
    const raw = await readFile(absoluteJsonPath, "utf-8");
    validatePublishedEpisode(raw, absoluteJsonPath);
    /** @type {Episode} */
    const episode = parseEpisodeJson(raw, absoluteJsonPath);
    const entry = await buildGalleryEntry(absoluteJsonPath, episode);
    entries.push(entry);
  }

  entries.sort(sortEntriesNewestFirst);
  await writeFile(INDEX_PATH, `${JSON.stringify(entries, null, 2)}\n`, "utf-8");
  console.log(`Rebuilt episodes/index.json with ${entries.length} episodes.`);
}

main().catch((error) => {
  const message = error instanceof Error ? error.message : String(error);
  console.error(`Failed to rebuild episodes/index.json: ${message}`);
  process.exit(1);
});
