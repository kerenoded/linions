import { CLOUDFRONT_DOMAIN, LOCAL_PREVIEW_BASE_PATH } from "./config.js";
import { buildEpisodePath, buildLegacyEpisodePath, type StoryRoute } from "./routes.js";
import type { Episode } from "./types.js";

function stripLeadingSlash(path: string): string {
  return path.replace(/^\/+/, "");
}

function getProxyRelativeBaseUrl(): string {
  if (typeof window === "undefined") {
    return "";
  }

  const { pathname } = window.location;
  if (pathname === LOCAL_PREVIEW_BASE_PATH || pathname.startsWith(`${LOCAL_PREVIEW_BASE_PATH}/`)) {
    return LOCAL_PREVIEW_BASE_PATH;
  }

  return "";
}

export function getPublicBaseUrl(): string {
  return CLOUDFRONT_DOMAIN || getProxyRelativeBaseUrl();
}

export function resolvePublicUrl(path: string): string {
  const baseUrl = getPublicBaseUrl();
  const normalisedPath = stripLeadingSlash(path);
  return baseUrl ? `${baseUrl}/${normalisedPath}` : `/${normalisedPath}`;
}

export async function fetchEpisodeByPath(path: string): Promise<Episode> {
  const response = await fetch(resolvePublicUrl(path));
  if (!response.ok) {
    throw new Error(`Episode request failed with status ${response.status}`);
  }

  return (await response.json()) as Episode;
}

export async function fetchEpisodeForRoute(route: StoryRoute): Promise<Episode> {
  const primaryPath = buildEpisodePath(route.username, route.uuid);
  try {
    return await fetchEpisodeByPath(primaryPath);
  } catch (error) {
    const legacyPath = buildLegacyEpisodePath(route.username, route.uuid);
    if (legacyPath === primaryPath) {
      throw error;
    }
    return fetchEpisodeByPath(legacyPath);
  }
}
