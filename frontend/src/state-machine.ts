import type { Episode, PlayerState } from "./types.js";

export type PlayerEvent =
  | { type: "START_POLLING"; jobId: string }
  | { type: "LOAD_EPISODE"; episode: Episode }
  | { type: "SHOW_CHOICES"; episode: Episode; actIndex: number }
  | { type: "FINISH" }
  | { type: "FAIL"; message: string }
  | { type: "RESET" };

export function transitionPlayerState(current: PlayerState, event: PlayerEvent): PlayerState {
  switch (event.type) {
    case "START_POLLING":
      return { status: "polling", jobId: event.jobId };
    case "LOAD_EPISODE":
      return { status: "playing", episode: event.episode, actIndex: 0 };
    case "SHOW_CHOICES":
      return { status: "choosing", episode: event.episode, actIndex: event.actIndex };
    case "FINISH":
      return { status: "done" };
    case "FAIL":
      return { status: "error", message: event.message };
    case "RESET":
      return { status: "idle" };
    default:
      return current;
  }
}
