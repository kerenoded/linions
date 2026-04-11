import { GeneratorController } from "./generator.js";
import { PlayerController } from "./player.js";
import { transitionPlayerState } from "./state-machine.js";
import type { Episode, PlayerState, PublishResponse } from "./types.js";

function byId<T extends HTMLElement>(id: string): T {
  const node = document.getElementById(id);
  if (!node) {
    throw new Error(`Missing required element: #${id}`);
  }
  return node as T;
}

let playerState: PlayerState = { status: "idle" };

function onStateChange(next: PlayerState): void {
  playerState = next;
}

function bootstrapStudio(): void {
  const createSection = byId<HTMLElement>("studio-create-section");
  const previewSection = byId<HTMLElement>("studio-preview-section");
  const promptInput = byId<HTMLTextAreaElement>("prompt-input");
  const generateButton = byId<HTMLButtonElement>("generate-button");
  const generatorStage = byId<HTMLElement>("generator-stage");
  const publishButton = byId<HTMLButtonElement>("publish-button");
  const generateNewButton = byId<HTMLButtonElement>("generate-new-button");
  let currentDraftKey: string | null = null;
  let published = false;

  const setStudioMode = (mode: "create" | "preview"): void => {
    createSection.hidden = mode !== "create";
    previewSection.hidden = mode !== "preview";
    createSection.style.display = mode === "create" ? "" : "none";
    previewSection.style.display = mode === "preview" ? "" : "none";
  };

  const syncPublishButton = (disabled: boolean): void => {
    publishButton.disabled = disabled || published;
  };

  const resetPublishButton = (): void => {
    published = false;
    publishButton.textContent = "Publish to repo";
  };

  const markPublished = (): void => {
    published = true;
    publishButton.textContent = "Published";
    publishButton.disabled = true;
  };

  const player = new PlayerController({
    mode: "studio",
    frame: byId<HTMLIFrameElement>("player-frame"),
    title: byId<HTMLElement>("player-title"),
    description: byId<HTMLElement>("player-description"),
    choicesContainer: byId<HTMLElement>("player-choices"),
    storyText: byId<HTMLElement>("player-story-text"),
    storyCard: byId<HTMLElement>("player-story-card"),
    controlsContainer: byId<HTMLElement>("player-controls"),
    statusLabel: byId<HTMLElement>("player-status"),
    onStateChange,
  });

  const generator = new GeneratorController({
    form: byId<HTMLFormElement>("prompt-form"),
    promptInput,
    submitButton: generateButton,
    stageLabel: generatorStage,
    onStateChange,
    onEpisodeReady: (episode: Episode) => {
      setStudioMode("preview");
      resetPublishButton();
      syncPublishButton(currentDraftKey === null);
      player.loadEpisode(episode);
      onStateChange(transitionPlayerState(playerState, { type: "LOAD_EPISODE", episode }));
    },
    onDraftKeyReady: (draftKey: string | null) => {
      currentDraftKey = draftKey;
      syncPublishButton(draftKey === null);
    },
  });

  generateNewButton.addEventListener("click", () => {
    currentDraftKey = null;
    resetPublishButton();
    syncPublishButton(true);
    setStudioMode("create");
    generatorStage.textContent = "Waiting for prompt...";
    promptInput.value = "";
    promptInput.focus();
    onStateChange(transitionPlayerState(playerState, { type: "RESET" }));
  });

  publishButton.addEventListener("click", async () => {
    if (!currentDraftKey) {
      return;
    }

    syncPublishButton(true);
    publishButton.textContent = "Publishing...";

    try {
      const response = await fetch("/publish", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ draftKey: currentDraftKey }),
      });

      const payload = (await response.json()) as PublishResponse | { error: string };
      if (!response.ok || "error" in payload) {
        throw new Error("error" in payload ? payload.error : "Publishing failed.");
      }

      markPublished();
    } catch {
      publishButton.textContent = "Publish failed";
      syncPublishButton(false);
    }
  });

  player.bind();
  generator.bind();
  resetPublishButton();
  syncPublishButton(true);
  setStudioMode("create");
}

bootstrapStudio();
