import { JOB_ID_STORAGE_KEY, POLL_INTERVAL_MS } from "./config.js";
import { transitionPlayerState } from "./state-machine.js";
import type {
  Episode,
  GenerateResponse,
  PlayerState,
  StatusResponse,
} from "./types.js";

export const PROGRESS_STAGES = [
  "[1/5] Querying character knowledge base...",
  "[2/5] Generating story script...",
  "[3/5] Validating script structure...",
  "[4/5] Designing animation keyframes...",
  "[5/5] Rendering SVG clips...",
] as const;

type GeneratorOptions = {
  form: HTMLFormElement;
  promptInput: HTMLTextAreaElement;
  submitButton: HTMLButtonElement;
  stageLabel: HTMLElement;
  onStateChange: (state: PlayerState) => void;
  onEpisodeReady: (episode: Episode) => void;
  onDraftKeyReady: (draftKey: string | null) => void;
};

async function fetchDraftEpisode(draftKey: string): Promise<Episode> {
  const response = await fetch(`/${draftKey.replace(/^\/+/, "")}`);
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Failed to fetch draft episode: ${draftKey}. ${errorText}`);
  }

  return (await response.json()) as Episode;
}

export class GeneratorController {
  private readonly options: GeneratorOptions;

  private pollHandle: number | null = null;

  public constructor(options: GeneratorOptions) {
    this.options = options;
  }

  public bind(): void {
    this.options.form.addEventListener("submit", (event) => {
      event.preventDefault();
      void this.generate();
    });

    const savedJobId = localStorage.getItem(JOB_ID_STORAGE_KEY);
    if (savedJobId) {
      this.setGenerateDisabled(true);
      this.options.onStateChange(transitionPlayerState({ status: "idle" }, { type: "START_POLLING", jobId: savedJobId }));
      this.startPolling(savedJobId);
    }
  }

  private async generate(): Promise<void> {
    const prompt = this.options.promptInput.value.trim();
    if (!prompt) {
      this.options.stageLabel.textContent = "Prompt is required.";
      return;
    }

    this.options.onDraftKeyReady(null);
    this.options.stageLabel.textContent = "Submitting prompt...";
    this.setGenerateDisabled(true);

    try {
      const response = await fetch("/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt }),
      });

      if (!response.ok) {
        this.setGenerateDisabled(false);
        this.options.onStateChange(transitionPlayerState({ status: "idle" }, { type: "FAIL", message: "Failed to start generation." }));
        return;
      }

      const payload = (await response.json()) as GenerateResponse;
      localStorage.setItem(JOB_ID_STORAGE_KEY, payload.jobId);
      this.options.onStateChange(transitionPlayerState({ status: "idle" }, { type: "START_POLLING", jobId: payload.jobId }));
      this.startPolling(payload.jobId);
    } catch {
      this.setGenerateDisabled(false);
      this.options.onStateChange(
        transitionPlayerState({ status: "idle" }, { type: "FAIL", message: "Failed to start generation." }),
      );
    }
  }

  private startPolling(jobId: string): void {
    this.stopPolling();
    void this.pollStatus(jobId);
    this.pollHandle = window.setInterval(() => {
      void this.pollStatus(jobId);
    }, POLL_INTERVAL_MS);
  }

  private stopPolling(): void {
    if (this.pollHandle !== null) {
      window.clearInterval(this.pollHandle);
      this.pollHandle = null;
    }
  }

  private async pollStatus(jobId: string): Promise<void> {
    let response: Response;
    try {
      response = await fetch(`/status/${encodeURIComponent(jobId)}`);
    } catch {
      this.stopPolling();
      localStorage.removeItem(JOB_ID_STORAGE_KEY);
      this.setGenerateDisabled(false);
      this.options.onStateChange(transitionPlayerState({ status: "polling", jobId }, { type: "FAIL", message: "Status polling failed." }));
      return;
    }
    if (!response.ok) {
      this.stopPolling();
      localStorage.removeItem(JOB_ID_STORAGE_KEY);
      this.setGenerateDisabled(false);
      this.options.onStateChange(transitionPlayerState({ status: "polling", jobId }, { type: "FAIL", message: "Status polling failed." }));
      return;
    }

    const payload = (await response.json()) as StatusResponse;
    this.options.stageLabel.textContent = payload.stage;

    if (payload.status === "DONE") {
      this.stopPolling();
      localStorage.removeItem(JOB_ID_STORAGE_KEY);
      this.setGenerateDisabled(false);
      this.options.onDraftKeyReady(payload.draftS3Key ?? null);

      if (!payload.draftS3Key) {
        const message = "Generation finished but no draft artifact was returned.";
        this.options.stageLabel.textContent = message;
        this.options.onStateChange(
          transitionPlayerState({ status: "polling", jobId }, { type: "FAIL", message }),
        );
        return;
      }

      try {
        this.options.stageLabel.textContent = "Loading generated draft...";
        const episode = await fetchDraftEpisode(payload.draftS3Key);
        this.options.onEpisodeReady(episode);
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "Generated draft could not be loaded.";
        this.options.stageLabel.textContent = message;
        this.options.onStateChange(
          transitionPlayerState({ status: "polling", jobId }, { type: "FAIL", message }),
        );
      }
    }

    if (payload.status === "FAILED") {
      this.stopPolling();
      localStorage.removeItem(JOB_ID_STORAGE_KEY);
      this.setGenerateDisabled(false);
      this.options.onStateChange(
        transitionPlayerState(
          { status: "polling", jobId },
          { type: "FAIL", message: payload.errorMessage ?? "Generation failed." },
        ),
      );
    }
  }

  private setGenerateDisabled(disabled: boolean): void {
    this.options.promptInput.disabled = disabled;
    this.options.submitButton.disabled = disabled;
  }
}
