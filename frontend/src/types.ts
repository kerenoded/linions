export type ObstacleType = string;

export interface EpisodeChoice {
  choiceIndex: number;
  label: string;
  isWinning: boolean;
  outcomeText: string;
  winClip: string | null;
  failClip: string | null;
}

export interface EpisodeAct {
  actIndex: number;
  obstacleType: ObstacleType;
  approachText: string;
  clips: {
    approach: string;
    choices: EpisodeChoice[];
  };
}

export interface Episode {
  schemaVersion: string;
  uuid: string;
  username: string;
  title: string;
  description: string;
  generatedAt: string;
  contentHash: string;
  actCount: number;
  acts: EpisodeAct[];
}

export interface GalleryEntry {
  path: string;
  thumbPath: string;
  username: string;
  title: string;
  description: string;
  createdAt: string;
}

export interface GenerateResponse {
  jobId: string;
}

export interface PublishResponse {
  publishedPath: string;
  indexPath: string;
  message: string;
  buildOutput: string;
}

/** Director script JSON returned by the status endpoint on DONE (Phase 4 inspection). */
export interface DirectorChoice {
  label: string;
  is_winning: boolean;
  outcome_description: string;
}

export interface DirectorAct {
  act_index: number;
  obstacle_type: string;
  approach_description: string;
  choices: DirectorChoice[];
}

export interface DirectorScript {
  title: string;
  description: string;
  acts: DirectorAct[];
}

export interface StatusResponse {
  jobId: string;
  username?: string;
  status: "PENDING" | "GENERATING" | "DONE" | "FAILED";
  stage: string;
  draftS3Key?: string;
  /** JSON-encoded DirectorOutput — present when status is DONE and no S3 episode yet. */
  directorScriptJson?: string;
  errorMessage?: string;
}

export type PlayerState =
  | { status: "idle" }
  | { status: "polling"; jobId: string }
  | { status: "playing"; episode: Episode; actIndex: number }
  | { status: "choosing"; episode: Episode; actIndex: number }
  | { status: "done" }
  | { status: "error"; message: string };

export interface PlayerViewModel {
  state: PlayerState;
  published: boolean;
  draftS3Key: string | null;
  selectedChoiceIndex: number | null;
}
