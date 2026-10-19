export type Style = "comic" | "realistic";
export type Gate = "script" | "assets" | "storyboard" | "sample";
export interface Project {
  id: string;
  name: string;
  budget: number;
  version: number;
}
export interface Output {
  path?: string;
  duration?: number;
  simulated?: boolean;
  mechanical_passed?: boolean;
  note?: string;
  bundle?: string;
  subtitles?: string;
  job_id?: string;
}
export interface Episode {
  id: string;
  title: string;
  style: Style;
  script: string;
  aspect: string;
  target_duration: number;
  version: number;
  planned_hash?: string;
  gates: Record<Gate, boolean>;
  delivery?: Output;
}
export interface Asset {
  id: string;
  name: string;
  kind: "character" | "scene" | "prop";
  description: string;
  costume: string;
  voice: string;
  style: Style;
  version: number;
  image?: string;
  simulated?: boolean;
}
export interface Shot {
  id: string;
  episode_id: string;
  version: number;
  order: number;
  visual: string;
  dialogue: string;
  speaker_id: string | null;
  asset_ids: string[];
  duration: number;
  framing: string;
  sample: boolean;
  outputs: Record<string, Output>;
  review_id?: string;
}
export interface Job {
  id: string;
  episode_id: string;
  entity_id: string;
  entity_version: number;
  op: string;
  status: string;
  error?: string;
  estimate: number;
  reserved: number;
  spent: number;
  actual_cost?: number;
  attempts: number;
  result?: Output;
  remote?: { request_id: string };
  created_at: number;
  finished_at?: number;
  provider_mode: string;
}
export interface Review {
  id: string;
  shot_id?: string;
  identity?: boolean;
  continuity?: boolean;
  voice?: boolean;
  dialogue?: boolean;
  lip_sync?: boolean;
  note?: string;
  qc_job_id?: string;
}
export interface Snapshot {
  project: Project;
  episodes: Episode[];
  assets: Asset[];
  shots: Shot[];
  jobs: Job[];
  reviews: Review[];
  budget: {
    limit: number;
    reserved: number;
    spent_ceiling: number;
    actual_known: number;
    remaining: number;
    unreconciled: number;
  };
}
export interface Health {
  mode: "mock" | "live";
  vimax_available: boolean;
  fal_configured: boolean;
  voice_configured: boolean;
  config: Record<string, unknown>;
}
