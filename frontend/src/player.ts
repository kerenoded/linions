import { buildGitHubProfileUrl } from "./github.js";
import { transitionPlayerState } from "./state-machine.js";
import type { Episode, EpisodeChoice, PlayerState } from "./types.js";

type PlayerMode = "studio" | "viewer";

type PlayerOptions = {
  mode: PlayerMode;
  frame: HTMLIFrameElement;
  title: HTMLElement;
  description: HTMLElement;
  choicesContainer: HTMLElement;
  storyText?: HTMLElement;
  storyCard?: HTMLElement;
  controlsContainer?: HTMLElement;
  statusLabel: HTMLElement;
  onStateChange: (state: PlayerState) => void;
};

export class PlayerController {
  private readonly options: PlayerOptions;

  private episode: Episode | null = null;

  private actIndex = 0;

  public constructor(options: PlayerOptions) {
    this.options = options;
  }

  public bind(): void {}

  public clear(): void {
    this.options.frame.style.visibility = "hidden";
  }

  public loadEpisode(episode: Episode): void {
    this.episode = episode;
    this.actIndex = 0;

    this.options.title.textContent = episode.title;
    this.renderEpisodeDescription(episode);
    this.renderAct();
  }

  private renderEpisodeDescription(episode: Episode): void {
    const authorLink = document.createElement("a");
    authorLink.className = "github-link";
    authorLink.href = buildGitHubProfileUrl(episode.username);
    authorLink.target = "_blank";
    authorLink.rel = "noreferrer";
    authorLink.textContent = `@${episode.username}`;

    this.options.description.replaceChildren(
      document.createTextNode(`${episode.description} — by `),
      authorLink,
    );
  }

  private renderAct(): void {
    if (!this.episode) {
      return;
    }

    const act = this.episode.acts[this.actIndex];
    if (!act) {
      this.options.onStateChange(
        transitionPlayerState(
          { status: "playing", episode: this.episode, actIndex: this.actIndex },
          { type: "FINISH" },
        ),
      );
      this.renderStatus("Episode complete.");
      this.options.choicesContainer.replaceChildren();
      this.renderControls([]);
      return;
    }

    const state = transitionPlayerState(
      { status: "playing", episode: this.episode, actIndex: this.actIndex },
      { type: "SHOW_CHOICES", episode: this.episode, actIndex: this.actIndex },
    );
    this.options.onStateChange(state);
    this.renderStatus(`Linai reaches the ${humanizeObstacleType(act.obstacleType)}.`);
    this.renderStoryText(
      act.approachText || `Linai approaches the ${humanizeObstacleType(act.obstacleType).toLowerCase()}.`,
    );
    this.renderSvg(act.clips.approach);
    this.renderChoices(act.clips.choices);
    this.renderControls(this.buildApproachControls());
  }

  private renderSvg(svg: string): void {
    const frame = this.options.frame;
    frame.addEventListener(
      "load",
      () => {
        frame.style.visibility = "";
      },
      { once: true },
    );
    frame.srcdoc = `<!doctype html><html><head><link rel="stylesheet" href="/player-frame.css"></head><body>${svg}</body></html>`;
  }

  private renderChoices(choices: EpisodeChoice[]): void {
    this.options.choicesContainer.replaceChildren();

    for (const choice of choices) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "choice-button";
      button.textContent = choice.label;
      button.addEventListener("click", () => {
        this.renderChoiceResult(choice);
      });
      this.options.choicesContainer.appendChild(button);
    }
  }

  private renderChoiceResult(choice: EpisodeChoice): void {
    this.options.choicesContainer.replaceChildren();

    const svg = choice.isWinning ? choice.winClip : choice.failClip;
    if (svg) {
      this.renderSvg(svg);
    }

    const reachedEnding =
      choice.isWinning && this.episode !== null && this.actIndex === this.episode.acts.length - 1;
    this.renderStoryText(choice.outcomeText);
    this.renderStatus(
      reachedEnding
        ? "Journey complete. Linai finished the episode successfully."
        : choice.isWinning
          ? "Linai's choice worked."
          : "That path failed.",
    );
    this.renderControls(this.buildResolutionControls(choice));
  }

  private renderStoryText(text: string): void {
    if (!this.options.storyText || !this.options.storyCard) {
      return;
    }

    this.options.storyText.textContent = text;
    this.options.storyCard.hidden = text.trim().length === 0;
  }

  private renderStatus(text: string): void {
    this.options.statusLabel.textContent = text;
    this.options.statusLabel.hidden = text.trim().length === 0;
  }

  private renderControls(
    controls: Array<{
      label: string;
      onClick: () => void;
      disabled?: boolean;
      primary?: boolean;
    }>,
  ): void {
    if (!this.options.controlsContainer) {
      return;
    }

    this.options.controlsContainer.replaceChildren();
    for (const control of controls) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = control.label;
      button.disabled = control.disabled ?? false;
      if (control.primary) {
        button.className = "primary-button";
      }
      button.addEventListener("click", control.onClick);
      this.options.controlsContainer.appendChild(button);
    }
  }

  private buildApproachControls(): Array<{
    label: string;
    onClick: () => void;
    disabled?: boolean;
  }> {
    if (this.actIndex === 0) {
      return [];
    }

    return [this.buildPreviousActControl()];
  }

  private buildResolutionControls(
    choice: EpisodeChoice,
  ): Array<{
    label: string;
    onClick: () => void;
    disabled?: boolean;
    primary?: boolean;
  }> {
    const controls: Array<{
      label: string;
      onClick: () => void;
      disabled?: boolean;
      primary?: boolean;
    }> = [];

    if (this.actIndex > 0) {
      controls.push(this.buildPreviousActControl());
    }

    if (choice.isWinning) {
      if (this.episode && this.actIndex < this.episode.acts.length - 1) {
        controls.push({
          label: "Continue to next act",
          primary: true,
          onClick: () => {
            this.actIndex += 1;
            this.renderAct();
          },
        });
      }
      return controls;
    }

    controls.push({
      label: "Try this act again",
      primary: true,
      onClick: () => {
        this.renderAct();
      },
    });
    return controls;
  }

  private buildPreviousActControl(): {
    label: string;
    onClick: () => void;
    disabled?: boolean;
    primary?: boolean;
  } {
    return {
      label: "Previous act",
      onClick: () => {
        if (this.actIndex === 0) {
          return;
        }
        this.actIndex -= 1;
        this.renderAct();
      },
    };
  }
}

function humanizeObstacleType(value: string): string {
  return value
    .replace(/[-_]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (char) => char.toUpperCase());
}
