import { LOCAL_PREVIEW_BASE_PATH } from "./config.js";

export type StoryRoute = {
  username: string;
  uuid: string;
};

function trimSlashes(value: string): string {
  return value.replace(/^\/+/, "").replace(/\/+$/, "");
}

function isLocalPreviewPath(pathname: string): boolean {
  return pathname === LOCAL_PREVIEW_BASE_PATH || pathname.startsWith(`${LOCAL_PREVIEW_BASE_PATH}/`);
}

function getViewerBasePath(currentPathname?: string): string {
  const pathname =
    currentPathname ?? (typeof window !== "undefined" ? window.location.pathname : "");
  return isLocalPreviewPath(pathname) ? LOCAL_PREVIEW_BASE_PATH : "";
}

function stripViewerBasePath(pathname: string): string {
  if (!isLocalPreviewPath(pathname)) {
    return pathname;
  }

  const stripped = pathname.slice(LOCAL_PREVIEW_BASE_PATH.length);
  return stripped.startsWith("/") ? stripped : `/${stripped}`;
}

export function buildStoryPath(username: string, uuid: string, currentPathname?: string): string {
  const basePath = getViewerBasePath(currentPathname);
  return `${basePath}/story/${encodeURIComponent(username)}/${encodeURIComponent(uuid)}`;
}

export function buildGalleryPath(currentPathname?: string): string {
  const basePath = getViewerBasePath(currentPathname);
  return basePath || "/";
}

export function buildEpisodePath(username: string, uuid: string): string {
  return `episodes/${username}/${uuid}/episode.json`;
}

export function buildLegacyEpisodePath(username: string, uuid: string): string {
  return `episodes/${username}/${uuid}.json`;
}

export function parseStoryRoute(pathname: string): StoryRoute | null {
  const cleaned = trimSlashes(stripViewerBasePath(pathname));
  const segments = cleaned.split("/").filter(Boolean);
  if (segments.length !== 3 || segments[0] !== "story") {
    return null;
  }

  return {
    username: decodeURIComponent(segments[1]),
    uuid: decodeURIComponent(segments[2]),
  };
}

export function episodePathToStoryPath(episodePath: string): string | null {
  const cleaned = trimSlashes(episodePath).replace(/^episodes\//, "");
  const segments = cleaned.split("/").filter(Boolean);

  if (segments.length === 3 && segments[2] === "episode.json") {
    return buildStoryPath(segments[0], segments[1]);
  }

  if (segments.length === 2 && segments[1].endsWith(".json")) {
    return buildStoryPath(segments[0], segments[1].replace(/\.json$/, ""));
  }

  return null;
}
