import { Sha256 } from "@aws-crypto/sha256-js";
import { defaultProvider } from "@aws-sdk/credential-provider-node";
import { HttpRequest } from "@smithy/protocol-http";
import { SignatureV4 } from "@smithy/signature-v4";
import { execFileSync } from "node:child_process";
import { createReadStream, existsSync, readFileSync, statSync } from "node:fs";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { join, normalize, resolve } from "node:path";
import { URL } from "node:url";
import { PORT, PREVIEW_BASE_PATH } from "./config";
import { publishDraftToRepo } from "./publish";

type Config = {
  awsProfile: string;
  awsRegion: string;
  generateUrl: string;
  statusUrl: string;
  cloudFrontDomain: string;
  episodesBucket: string;
};
// Resolve paths relative to this file's location so they are correct regardless
// of which directory npm --prefix uses as cwd.
const REPO_ROOT = resolve(__dirname, "..");
const STUDIO_DIST_DIR = resolve(REPO_ROOT, "frontend", "dist-studio");
const PUBLIC_DIST_DIR = resolve(REPO_ROOT, "frontend", "dist-public");
const ENV_PATH = resolve(__dirname, ".env");
const EPISODES_DIR = resolve(REPO_ROOT, "episodes");
const BUILD_INDEX_SCRIPT = resolve(REPO_ROOT, "scripts", "build-index.js");

function parseDotEnv(path: string): Record<string, string> {
  const content = readFileSync(path, "utf-8");
  const values: Record<string, string> = {};

  for (const rawLine of content.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) {
      continue;
    }
    const separatorIndex = line.indexOf("=");
    if (separatorIndex <= 0) {
      continue;
    }
    const key = line.slice(0, separatorIndex).trim();
    const value = line.slice(separatorIndex + 1).trim();
    values[key] = value;
  }

  return values;
}

function getRequiredValue(map: Record<string, string>, key: string): string {
  const value = map[key];
  if (!value) {
    throw new Error(`Missing required env value '${key}' in proxy/.env`);
  }
  return value;
}

function loadConfig(): Config {
  if (!existsSync(ENV_PATH)) {
    throw new Error("proxy/.env not found. Run scripts/setup-env.sh first.");
  }

  const env = parseDotEnv(ENV_PATH);
  const awsProfile = env.AWS_PROFILE ?? "default";

  return {
    awsProfile,
    awsRegion: getRequiredValue(env, "AWS_REGION"),
    generateUrl: getRequiredValue(env, "LINIONS_GENERATE_URL"),
    statusUrl: getRequiredValue(env, "LINIONS_STATUS_URL"),
    cloudFrontDomain: getRequiredValue(env, "CLOUDFRONT_DOMAIN"),
    episodesBucket: getRequiredValue(env, "EPISODES_BUCKET"),
  };
}

function resolveGitHubUsername(): string {
  try {
    const ghUser = execFileSync("gh", ["api", "user", "--jq", ".login"], {
      encoding: "utf-8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
    if (ghUser) {
      return ghUser;
    }
  } catch {
    // fallback below
  }

  try {
    const gitEmail = execFileSync("git", ["config", "user.email"], {
      encoding: "utf-8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
    const atIndex = gitEmail.indexOf("@");
    if (atIndex > 0) {
      return gitEmail.slice(0, atIndex);
    }
  } catch {
    // no-op
  }

  throw new Error(
    "Could not determine GitHub username. Install GitHub CLI/authenticate, or configure git user.email.",
  );
}

async function validateAwsCredentials(profile: string): Promise<void> {
  const provider = defaultProvider({ profile });
  await provider();
}

function sendJson(res: ServerResponse, statusCode: number, body: unknown): void {
  const serialised = JSON.stringify(body);
  res.writeHead(statusCode, {
    "Content-Type": "application/json",
    "Content-Length": Buffer.byteLength(serialised),
  });
  res.end(serialised);
}

function getBody(req: IncomingMessage): Promise<string> {
  return new Promise((resolveBody, rejectBody) => {
    const chunks: Buffer[] = [];
    req.on("data", (chunk: Buffer) => chunks.push(chunk));
    req.on("end", () => resolveBody(Buffer.concat(chunks).toString("utf-8")));
    req.on("error", rejectBody);
  });
}

function getContentType(absolutePath: string): string {
  const extension = absolutePath.split(".").pop()?.toLowerCase();
  return extension === "html"
    ? "text/html; charset=utf-8"
    : extension === "js"
      ? "application/javascript; charset=utf-8"
      : extension === "css"
        ? "text/css; charset=utf-8"
        : extension === "svg"
          ? "image/svg+xml"
          : extension === "json"
            ? "application/json; charset=utf-8"
            : "application/octet-stream";
}

function serveStaticFileFromRoot(reqPath: string, rootDir: string, res: ServerResponse): boolean {
  const requestedPath = reqPath === "/" ? "index.html" : reqPath.slice(1);
  const safePath = normalize(requestedPath).replace(/^\.+\//, "");
  const absolutePath = join(rootDir, safePath);

  if (!absolutePath.startsWith(rootDir)) {
    sendJson(res, 400, { error: "Invalid path" });
    return true;
  }

  if (!existsSync(absolutePath)) {
    return false;
  }

  const stats = statSync(absolutePath);
  if (stats.isDirectory()) {
    return false;
  }

  res.writeHead(200, { "Content-Type": getContentType(absolutePath) });
  createReadStream(absolutePath).pipe(res);
  return true;
}

function serveStaticFile(reqPath: string, res: ServerResponse): boolean {
  return serveStaticFileFromRoot(reqPath, STUDIO_DIST_DIR, res);
}

function servePreviewAsset(reqPath: string, res: ServerResponse): boolean {
  return serveStaticFileFromRoot(reqPath, PUBLIC_DIST_DIR, res);
}

function buildPreviewHtml(): string {
  const indexPath = join(PUBLIC_DIST_DIR, "index.html");
  const html = readFileSync(indexPath, "utf-8");
  return html
    .replace('href="/favicon.svg"', `href="${PREVIEW_BASE_PATH}/favicon.svg"`)
    .replace('href="/app.css"', `href="${PREVIEW_BASE_PATH}/app.css"`)
    .replace('href="/"', `href="${PREVIEW_BASE_PATH}/"`)
    .replace('src="/viewer.js"', `src="${PREVIEW_BASE_PATH}/viewer.js"`);
}

function servePreviewIndex(res: ServerResponse): void {
  const html = buildPreviewHtml();
  res.writeHead(200, {
    "Content-Type": "text/html; charset=utf-8",
    "Content-Length": Buffer.byteLength(html),
  });
  res.end(html);
}

function isModuleAssetRequest(path: string): boolean {
  return path.endsWith(".js") || path.endsWith(".mjs") || path.endsWith(".css") || path.endsWith(".map");
}

function getPathname(req: IncomingMessage): string {
  const url = new URL(req.url ?? "/", "http://localhost");
  return url.pathname;
}

function getTargetUrl(base: string, pathWithQuery: string): URL {
  const targetBase = new URL(base);
  return new URL(pathWithQuery, targetBase);
}

function encodeS3Key(key: string): string {
  return key
    .split("/")
    .filter((segment) => segment.length > 0)
    .map((segment) => encodeURIComponent(segment))
    .join("/");
}

function buildS3ObjectUrl(bucket: string, region: string, key: string): URL {
  return new URL(`https://${bucket}.s3.${region}.amazonaws.com/${encodeS3Key(key)}`);
}

function validatePublishDraftKey(draftKey: unknown): string {
  if (typeof draftKey !== "string" || !draftKey.startsWith("drafts/") || !draftKey.endsWith(".json")) {
    throw new Error("draftKey must point to a draft episode JSON object.");
  }
  return draftKey.replace(/^\/+/, "");
}

async function fetchSignedS3Object(args: {
  draftKey: string;
  config: Config;
  route: string;
}): Promise<{ upstream: Response; buffer: Buffer; target: URL }> {
  const target = buildS3ObjectUrl(args.config.episodesBucket, args.config.awsRegion, args.draftKey);
  const upstream = await forwardSignedRequest({
    method: "GET",
    targetUrl: target,
    config: args.config,
    service: "s3",
  });
  const buffer = Buffer.from(await upstream.arrayBuffer());
  if (!upstream.ok) {
    logUpstreamFailure({
      route: args.route,
      targetUrl: target.toString(),
      status: upstream.status,
      requestId: upstream.headers.get("x-amz-request-id"),
      body: buffer.toString("utf-8"),
    });
  }
  return { upstream, buffer, target };
}

async function signAwsRequest(
  method: "GET" | "POST",
  url: URL,
  body: string | undefined,
  awsProfile: string,
  awsRegion: string,
  service: "lambda" | "s3",
): Promise<Request> {
  const provider = defaultProvider({ profile: awsProfile });
  const signer = new SignatureV4({
    credentials: provider,
    region: awsRegion,
    service,
    sha256: Sha256,
  });

  const signed = (await signer.sign(
    new HttpRequest({
      protocol: url.protocol,
      hostname: url.hostname,
      port: url.port ? Number(url.port) : undefined,
      method,
      path: url.pathname,
      query: Object.fromEntries(url.searchParams.entries()),
      headers: {
        host: url.host,
        ...(body ? { "content-type": "application/json" } : {}),
      },
      body,
    }),
  )) as unknown as { headers: Record<string, string> };

  const headers = new Headers();
  for (const [key, value] of Object.entries(signed.headers)) {
    if (typeof value === "string") {
      headers.set(key, value);
    }
  }

  return new Request(url, {
    method,
    headers,
    body,
  });
}

async function forwardSignedRequest(args: {
  method: "GET" | "POST";
  targetUrl: URL;
  body?: string;
  config: Config;
  service: "lambda" | "s3";
}): Promise<Response> {
  const signedRequest = await signAwsRequest(
    args.method,
    args.targetUrl,
    args.body,
    args.config.awsProfile,
    args.config.awsRegion,
    args.service,
  );
  return fetch(signedRequest);
}

function logRequest(method: string, path: string, status: number, startedAt: number): void {
  const durationMs = Date.now() - startedAt;
  console.log(`${method} ${path} -> ${status} (${durationMs}ms)`);
}

function logUpstreamFailure(args: {
  route: string;
  targetUrl: string;
  status: number;
  requestId: string | null;
  body: string;
}): void {
  const snippet = args.body.length > 500 ? `${args.body.slice(0, 500)}...` : args.body;
  console.error(
    `[proxy upstream error] route=${args.route} target=${args.targetUrl} status=${args.status} requestId=${args.requestId ?? "n/a"} body=${snippet}`,
  );
}

function getPreviewSubPath(path: string): string | null {
  if (path === PREVIEW_BASE_PATH) {
    return "/";
  }

  if (!path.startsWith(`${PREVIEW_BASE_PATH}/`)) {
    return null;
  }

  return path.slice(PREVIEW_BASE_PATH.length) || "/";
}

function hasFileExtension(path: string): boolean {
  return /\.[A-Za-z0-9]+$/.test(path);
}

async function main(): Promise<void> {
  if (!existsSync(STUDIO_DIST_DIR) || !existsSync(PUBLIC_DIST_DIR)) {
    throw new Error(
      "frontend/dist-studio or frontend/dist-public is missing. Run `npm --prefix frontend run build` first.",
    );
  }

  const config = loadConfig();
  const username = resolveGitHubUsername();
  await validateAwsCredentials(config.awsProfile);

  console.log(`Linions proxy starting on port ${PORT}`);
  console.log(`GitHub username: ${username}`);
  console.log(`AWS profile: ${config.awsProfile}`);
  console.log(`Local published viewer: http://localhost:${PORT}${PREVIEW_BASE_PATH}`);

  const server = createServer(async (req, res) => {
    const startedAt = Date.now();
    const method = req.method ?? "GET";
    const path = getPathname(req);

    try {
      if (method === "POST" && path === "/generate") {
        const requestBody = await getBody(req);
        if (!requestBody) {
          sendJson(res, 400, { error: "Prompt is required" });
          logRequest(method, path, 400, startedAt);
          return;
        }

        let parsed: { prompt?: string; username?: string };
        try {
          parsed = JSON.parse(requestBody) as { prompt?: string; username?: string };
        } catch {
          sendJson(res, 400, { error: "Request body must be valid JSON" });
          logRequest(method, path, 400, startedAt);
          return;
        }

        if (!parsed.prompt?.trim()) {
          sendJson(res, 400, { error: "Prompt is required" });
          logRequest(method, path, 400, startedAt);
          return;
        }

        const target = new URL(config.generateUrl);
        console.log(
          `[proxy] forwarding generate to ${target.toString()} promptLength=${parsed.prompt.trim().length} username=${username}`,
        );
        const upstream = await forwardSignedRequest({
          method: "POST",
          targetUrl: target,
          body: JSON.stringify({
            ...parsed,
            username,
          }),
          config,
          service: "lambda",
        });

        const body = await upstream.text();
        if (!upstream.ok) {
          logUpstreamFailure({
            route: path,
            targetUrl: target.toString(),
            status: upstream.status,
            requestId: upstream.headers.get("x-amzn-requestid"),
            body,
          });
        }
        res.writeHead(upstream.status, {
          "Content-Type": upstream.headers.get("content-type") ?? "application/json",
        });
        res.end(body);
        logRequest(method, path, upstream.status, startedAt);
        return;
      }

      if (method === "GET" && path.startsWith("/status/")) {
        const jobId = path.slice("/status/".length).trim();
        if (!jobId) {
          sendJson(res, 404, { error: "Job not found" });
          logRequest(method, path, 404, startedAt);
          return;
        }

        const incomingUrl = new URL(req.url ?? "/", "http://localhost");
        const statusPath = `/status/${encodeURIComponent(jobId)}`;
        const target = getTargetUrl(config.statusUrl, `${statusPath}${incomingUrl.search}`);
        console.log(`[proxy] forwarding status to ${target.toString()} jobId=${jobId}`);
        const upstream = await forwardSignedRequest({
          method: "GET",
          targetUrl: target,
          config,
          service: "lambda",
        });

        const body = await upstream.text();
        if (!upstream.ok) {
          logUpstreamFailure({
            route: path,
            targetUrl: target.toString(),
            status: upstream.status,
            requestId: upstream.headers.get("x-amzn-requestid"),
            body,
          });
        }
        res.writeHead(upstream.status, {
          "Content-Type": upstream.headers.get("content-type") ?? "application/json",
        });
        res.end(body);
        logRequest(method, path, upstream.status, startedAt);
        return;
      }

      if (method === "GET" && path.startsWith("/drafts/")) {
        const draftKey = path.replace(/^\/+/, "");
        const { upstream, buffer, target } = await fetchSignedS3Object({
          draftKey,
          config,
          route: path,
        });
        console.log(`[proxy] forwarding draft read to ${target.toString()} key=${draftKey}`);
        res.writeHead(upstream.status, {
          "Content-Type": upstream.headers.get("content-type") ?? "application/octet-stream",
          "Content-Length": buffer.byteLength,
        });
        res.end(buffer);
        logRequest(method, path, upstream.status, startedAt);
        return;
      }

      if (method === "POST" && path === "/publish") {
        const requestBody = await getBody(req);
        let parsed: { draftKey?: unknown };
        try {
          parsed = JSON.parse(requestBody) as { draftKey?: unknown };
        } catch {
          sendJson(res, 400, { error: "Request body must be valid JSON" });
          logRequest(method, path, 400, startedAt);
          return;
        }

        let draftKey: string;
        try {
          draftKey = validatePublishDraftKey(parsed.draftKey);
        } catch (error) {
          sendJson(res, 400, { error: error instanceof Error ? error.message : "Invalid draft key" });
          logRequest(method, path, 400, startedAt);
          return;
        }

        const { upstream, buffer, target } = await fetchSignedS3Object({
          draftKey,
          config,
          route: path,
        });
        console.log(`[proxy] publishing draft from ${target.toString()} key=${draftKey}`);
        if (!upstream.ok) {
          sendJson(res, upstream.status, {
            error: "Failed to load the draft episode from S3 for publishing.",
          });
          logRequest(method, path, upstream.status, startedAt);
          return;
        }

        try {
          const result = await publishDraftToRepo({
            draftBody: buffer.toString("utf-8"),
            repoRoot: REPO_ROOT,
            episodesDir: EPISODES_DIR,
            buildIndexScript: BUILD_INDEX_SCRIPT,
          });
          sendJson(res, 200, {
            publishedPath: result.publishedPath,
            indexPath: result.indexPath,
            message: `Published locally to ${result.publishedPath} and rebuilt ${result.indexPath}. Redeploy the stack when you want it live.`,
            buildOutput: result.buildOutput,
          });
          logRequest(method, path, 200, startedAt);
          return;
        } catch (error) {
          const message = error instanceof Error ? error.message : "Failed to publish draft locally.";
          const statusCode = error instanceof Error && error.name === "PublishConflict" ? 409 : 500;
          sendJson(res, statusCode, { error: message });
          logRequest(method, path, statusCode, startedAt);
          return;
        }
      }

      if (method === "GET" && path.startsWith("/episodes/")) {
        const incomingUrl = new URL(req.url ?? "/", "http://localhost");
        const target = getTargetUrl(config.cloudFrontDomain, `${incomingUrl.pathname}${incomingUrl.search}`);
        const upstream = await fetch(target, { method: "GET" });
        const buffer = Buffer.from(await upstream.arrayBuffer());
        res.writeHead(upstream.status, {
          "Content-Type": upstream.headers.get("content-type") ?? "application/octet-stream",
          "Content-Length": buffer.byteLength,
        });
        res.end(buffer);
        logRequest(method, path, upstream.status, startedAt);
        return;
      }

      if (method === "GET") {
        const previewPath = getPreviewSubPath(path);
        if (previewPath) {
          if (previewPath.startsWith("/episodes/")) {
            const episodeAssetPath = previewPath.slice("/episodes".length) || "/";
            const servedEpisodeAsset = serveStaticFileFromRoot(episodeAssetPath, EPISODES_DIR, res);
            if (servedEpisodeAsset) {
              logRequest(method, path, 200, startedAt);
              return;
            }

            sendJson(res, 404, { error: "Preview episode asset not found" });
            logRequest(method, path, 404, startedAt);
            return;
          }

          const servedPreviewAsset = servePreviewAsset(previewPath, res);
          if (servedPreviewAsset) {
            logRequest(method, path, 200, startedAt);
            return;
          }

          if (previewPath === "/" || previewPath.startsWith("/story/") || !hasFileExtension(previewPath)) {
            servePreviewIndex(res);
            logRequest(method, path, 200, startedAt);
            return;
          }

          sendJson(res, 404, { error: "Preview asset not found" });
          logRequest(method, path, 404, startedAt);
          return;
        }

        const served = serveStaticFile(path, res);
        if (served) {
          logRequest(method, path, 200, startedAt);
          return;
        }

        if (isModuleAssetRequest(path)) {
          sendJson(res, 404, { error: "Asset not found" });
          logRequest(method, path, 404, startedAt);
          return;
        }

        const indexPath = join(STUDIO_DIST_DIR, "index.html");
        if (existsSync(indexPath)) {
          res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
          createReadStream(indexPath).pipe(res);
          logRequest(method, path, 200, startedAt);
          return;
        }
      }

      sendJson(res, 404, { error: "Not found" });
      logRequest(method, path, 404, startedAt);
    } catch (error) {
      const detail = error instanceof Error ? `${error.name}: ${error.message}\n${error.stack ?? ""}` : String(error);
      console.error(`[proxy error] method=${method} path=${path} detail=${detail}`);
      sendJson(res, 500, { error: "Internal proxy error" });
      logRequest(method, path, 500, startedAt);
    }
  });

  server.listen(PORT, "0.0.0.0");
}

void main().catch((error) => {
  console.error(error instanceof Error ? error.message : "Unknown startup error");
  process.exit(1);
});
