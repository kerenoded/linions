import { fetchEpisodeForRoute } from "./episode-loader.js";
import { GalleryController } from "./gallery.js";
import { PlayerController } from "./player.js";
import { buildGalleryPath, parseStoryRoute, episodePathToStoryPath } from "./routes.js";
import { transitionPlayerState } from "./state-machine.js";
import type { PlayerState } from "./types.js";

function byId<T extends HTMLElement>(id: string): T {
  const node = document.getElementById(id);
  if (!node) {
    throw new Error(`Missing required element: #${id}`);
  }
  return node as T;
}

function maybeById<T extends HTMLElement>(id: string): T | null {
  const node = document.getElementById(id);
  return node as T | null;
}

let playerState: PlayerState = { status: "idle" };

function onStateChange(next: PlayerState): void {
  playerState = next;
}

function setMode(mode: "gallery" | "story"): void {
  byId<HTMLElement>("viewer-gallery-section").hidden = mode !== "gallery";
  byId<HTMLElement>("viewer-player-section").hidden = mode !== "story";
  byId<HTMLAnchorElement>("viewer-home-link").hidden = mode !== "story";
}

function syncHomeLink(): void {
  byId<HTMLAnchorElement>("viewer-home-link").href = buildGalleryPath(window.location.pathname);
}

function navigateToGallery(player: PlayerController, gallery: GalleryController): void {
  window.history.pushState({}, "", buildGalleryPath(window.location.pathname));
  window.scrollTo({ top: 0, behavior: "auto" });
  void renderRoute(player, gallery);
}

async function renderRoute(player: PlayerController, gallery: GalleryController): Promise<void> {
  syncHomeLink();
  const route = parseStoryRoute(window.location.pathname);
  if (!route) {
    setMode("gallery");
    await gallery.load();
    return;
  }

  setMode("story");
  player.clear();
  byId<HTMLElement>("player-status").textContent = "Loading episode...";

  try {
    const episode = await fetchEpisodeForRoute(route);
    player.loadEpisode(episode);
    onStateChange(transitionPlayerState(playerState, { type: "LOAD_EPISODE", episode }));
  } catch {
    byId<HTMLElement>("player-title").textContent = "Episode unavailable";
    byId<HTMLElement>("player-description").textContent =
      "This published episode could not be loaded from the public gallery.";
    byId<HTMLElement>("player-status").textContent = "Unable to load this story.";
    byId<HTMLElement>("player-choices").replaceChildren();
    maybeById<HTMLElement>("player-controls")?.replaceChildren();
    const storyCard = maybeById<HTMLElement>("player-story-card");
    if (storyCard) {
      storyCard.hidden = true;
    }
  }
}

function bootstrapViewer(): void {
  const player = new PlayerController({
    mode: "viewer",
    frame: byId<HTMLIFrameElement>("player-frame"),
    title: byId<HTMLElement>("player-title"),
    description: byId<HTMLElement>("player-description"),
    choicesContainer: byId<HTMLElement>("player-choices"),
    storyText: maybeById<HTMLElement>("player-story-text") ?? undefined,
    storyCard: maybeById<HTMLElement>("player-story-card") ?? undefined,
    controlsContainer: maybeById<HTMLElement>("player-controls") ?? undefined,
    statusLabel: byId<HTMLElement>("player-status"),
    onStateChange,
  });

  const gallery = new GalleryController({
    container: byId<HTMLElement>("gallery-grid"),
    statusLabel: byId<HTMLElement>("gallery-status"),
    onSelectEpisode: (episodePath: string) => {
      const storyPath = episodePathToStoryPath(episodePath);
      if (!storyPath) {
        return;
      }

      window.history.pushState({}, "", storyPath);
      syncHomeLink();
      window.scrollTo({ top: 0, behavior: "auto" });
      void renderRoute(player, gallery);
    },
  });

  byId<HTMLAnchorElement>("viewer-home-link").addEventListener("click", (event) => {
    event.preventDefault();
    navigateToGallery(player, gallery);
  });

  player.bind();

  window.addEventListener("popstate", () => {
    void renderRoute(player, gallery);
  });

  void renderRoute(player, gallery);
}

bootstrapViewer();
