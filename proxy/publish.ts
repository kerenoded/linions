import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, rmdir, unlink, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";

export type PublishedEpisodeMetadata = {
  username: string;
  uuid: string;
  publishedPath: string;
  absolutePath: string;
  thumbPath: string;
  absoluteThumbPath: string;
};

type PublishDraftToRepoArgs = {
  draftBody: string;
  repoRoot: string;
  episodesDir: string;
  buildIndexScript: string;
  runBuildIndex?: (args: { repoRoot: string; buildIndexScript: string }) => Promise<string>;
};

function defaultRunBuildIndex(args: { repoRoot: string; buildIndexScript: string }): Promise<string> {
  return Promise.resolve(
    execFileSync(process.execPath, [args.buildIndexScript], {
      cwd: args.repoRoot,
      encoding: "utf-8",
      stdio: ["ignore", "pipe", "pipe"],
    }).trim(),
  );
}

function requireSafePathSegment(value: unknown, fieldName: string): string {
  if (typeof value !== "string" || !/^[A-Za-z0-9._-]+$/.test(value)) {
    throw new Error(`Draft episode has an invalid ${fieldName}.`);
  }
  return value;
}

export function parsePublishedEpisodeMetadata(
  rawDraft: string,
  args: { repoRoot: string; episodesDir: string },
): PublishedEpisodeMetadata {
  let parsed: unknown;
  try {
    parsed = JSON.parse(rawDraft);
  } catch {
    throw new Error("Draft episode JSON is malformed.");
  }

  if (!parsed || typeof parsed !== "object") {
    throw new Error("Draft episode JSON must be an object.");
  }

  const episode = parsed as { username?: unknown; uuid?: unknown };
  const username = requireSafePathSegment(episode.username, "username");
  const uuid = requireSafePathSegment(episode.uuid, "uuid");
  const publishedPath = `episodes/${username}/${uuid}/episode.json`;
  const thumbPath = `episodes/${username}/${uuid}/thumb.svg`;
  const absolutePath = resolve(args.repoRoot, publishedPath);
  const absoluteThumbPath = resolve(args.repoRoot, thumbPath);
  const episodesRoot = resolve(args.episodesDir);
  if (
    absolutePath !== resolve(args.episodesDir, username, uuid, "episode.json")
    && !absolutePath.startsWith(`${episodesRoot}/`)
  ) {
    throw new Error("Resolved publish path escaped the episodes directory.");
  }

  return {
    username,
    uuid,
    publishedPath,
    absolutePath,
    thumbPath,
    absoluteThumbPath,
  };
}

async function cleanupPublishedArtifactPaths(
  metadata: PublishedEpisodeMetadata,
): Promise<string[]> {
  const cleanupErrors: string[] = [];
  for (const absolutePath of [metadata.absoluteThumbPath, metadata.absolutePath]) {
    if (!existsSync(absolutePath)) {
      continue;
    }
    try {
      await unlink(absolutePath);
    } catch (cleanupError) {
      cleanupErrors.push(
        cleanupError instanceof Error ? cleanupError.message : String(cleanupError),
      );
    }
  }

  try {
    await rmdir(dirname(metadata.absolutePath));
  } catch {
    // Ignore: the directory may still contain files or may already be absent.
  }

  return cleanupErrors;
}

export async function publishDraftToRepo(
  args: PublishDraftToRepoArgs,
): Promise<{ publishedPath: string; indexPath: string; buildOutput: string }> {
  const metadata = parsePublishedEpisodeMetadata(args.draftBody, {
    repoRoot: args.repoRoot,
    episodesDir: args.episodesDir,
  });
  if (existsSync(metadata.absolutePath) || existsSync(metadata.absoluteThumbPath)) {
    const msg = `Episode already exists at ${metadata.publishedPath}`;
    const error = new Error(msg);
    error.name = "PublishConflict";
    throw error;
  }

  await mkdir(dirname(metadata.absolutePath), { recursive: true });
  await writeFile(metadata.absolutePath, args.draftBody, "utf-8");

  try {
    const buildOutput = await (args.runBuildIndex ?? defaultRunBuildIndex)({
      repoRoot: args.repoRoot,
      buildIndexScript: args.buildIndexScript,
    });
    return {
      publishedPath: metadata.publishedPath,
      indexPath: "episodes/index.json",
      buildOutput,
    };
  } catch (error) {
    const cleanupErrors = await cleanupPublishedArtifactPaths(metadata);
    const stderr =
      error instanceof Error && "stderr" in error && typeof error.stderr === "string"
        ? error.stderr.trim()
        : "";
    const cleanupSuffix =
      cleanupErrors.length > 0
        ? ` Cleanup also failed: ${cleanupErrors.join("; ")}`
        : "";
    throw new Error(
      `Failed to rebuild episodes/index.json after copying ${metadata.publishedPath}.${stderr ? ` ${stderr}` : ""}${cleanupSuffix}`,
    );
  }
}
