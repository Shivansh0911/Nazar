// Mirrors backend/nazar/core/schemas.py and the API route payloads.

export type Level = "confirmed" | "probable" | "candidate";

export interface SeriesPoint {
  t: string;
  n: number;
}

export interface CountResult {
  value: number;
  label: string;
  level: "confirmed";
  series: SeriesPoint[];
  bucket?: string;
}

export interface ClipItem {
  track_id: number;
  camera_id: string;
  cls: string;
  t_start: string;
  t_end: string;
  level: Level;
  why: string;
  caption: string | null;
  thumb_url: string | null;
  score: number;
  zones: string[];
}

export interface RuleSpec {
  camera_id: string;
  trigger: "zone_enter" | "zone_exit" | "dwell_over" | "count_over" | "object_removed";
  cls: string;
  zone: string;
  dwell_s?: number | null;
  count?: number | null;
  time_window?: { from: string; to: string } | null;
  confirm_with_vision?: string | null;
  notify?: "voice_note";
}

export interface RuleReplay {
  window_from: string;
  window_to: string;
  count: number;
  hits: { track_id: number; t: string; zone?: string; actor_track_id?: number; object_track_id?: number }[];
}

export interface HitThumb {
  track_id: number;
  t: string;
  thumb_url: string | null;
  object_track_id?: number | null;
  clip_track_id?: number;
}

export interface RuleDraft {
  ok: boolean;
  rule_id?: number | null;
  camera_id?: string | null;
  camera_name?: string | null;
  text?: string;
  human?: string;
  spec?: RuleSpec | null;
  replay?: RuleReplay | null;
  active?: boolean;
  question?: string | null;
  missing_zone_label?: string | null;
  hit_thumbs?: HitThumb[];
  language?: string;
  created_at?: string;
  activated_at?: string | null;
  last_alert?: string | null;
  alert_count?: number;
}

export interface Gap {
  camera_id?: string;
  from: string;
  to: string;
  minutes: number;
}

export interface AskResponse {
  query_id: number;
  transcript: string | null;
  language: string;
  reply_text: string;
  audio_url: string | null;
  count: CountResult | null;
  clips: ClipItem[];
  rule: RuleDraft | null;
  gaps: Gap[];
  followups: string[];
  cost_usd: number;
  cost_inr: number;
  latency_ms: number;
}

export interface AlertOut {
  id: number;
  rule_id: number;
  track_id: number;
  camera_id: string;
  camera_name?: string | null;
  t: string;
  message: string;
  human: string | null;
  audio_url: string | null;
  snapshot_url: string | null;
  vision_confirmed: boolean | null;
  suppressed: boolean;
  ack: boolean;
  meta?: Record<string, unknown>;
}

export interface Zone {
  name: string;
  label: string;
  polygon: [number, number][];
}

export interface CameraOut {
  id: string;
  name: string;
  kind: "file" | "rtsp" | "srt" | "rtmp" | "phone";
  source_url: string;
  zones: Zone[];
  settings: Record<string, unknown>;
  width: number | null;
  height: number | null;
  active: boolean;
  live: boolean;
  last_heartbeat_age_s: number | null;
  status_note: string | null;
  today_count: number;
  coverage_from: string | null;
  coverage_to: string | null;
  edge_running: boolean;
  fps_proc?: number | null;
}

export interface TrackOut {
  track_id: number;
  camera_id: string;
  cls: string;
  t_start: string;
  t_end: string;
  zones: string[];
  caption: string | null;
  attrs?: Record<string, unknown> | null;
  crops?: string[];
  thumb_url: string | null;
  level?: Level;
  score?: number;
  why?: string;
}

export interface ClipOut {
  url: string;
  t0_ms: number;
  t1_ms: number;
  path: number[][];
  camera_id: string;
  track_id?: number;
  cls?: string;
}

export interface Progress {
  state: "queued" | "processing" | "enriching" | "ready" | "error";
  processed_seconds: number;
  duration_seconds: number;
  tracks: number;
  enriched: number;
  error: string | null;
  note?: string | null;
}

export interface EdgeStatus {
  camera_id: string;
  running: boolean;
  queued: boolean;
  pid: number | null;
  uptime_s: number | null;
  restarts: number;
  last_log: string[];
}

export interface MetricsOut {
  total_usd: number;
  total_inr: number;
  by_kind: { kind: string; usd: number; inr: number; calls: number }[];
  by_model: { model: string; usd: number; inr: number; calls: number }[];
  cost_per_camera_day_inr: number | null;
  naive_per_camera_day_inr: number | null;
  ratio: number | null;
  footage_hours: number;
  tracks_processed: number;
  enrich_backlog: number;
  ask_latency_p50_ms: number | null;
  ask_latency_p90_ms: number | null;
  query_count: number;
  level_distribution: Record<Level, number>;
  unknown_price_calls: number;
  eval: Record<string, unknown> | null;
}

export interface Health {
  ok: boolean;
  db: boolean;
  openai_key: boolean;
  storage: string;
}

export type WsMessage =
  | { type: "hello" }
  | { type: "pong" }
  | { type: "alert"; update: boolean; alert: AlertOut }
  | { type: "camera_status"; cameras: Pick<CameraOut, "id" | "live" | "edge_running" | "today_count" | "last_heartbeat_age_s" | "status_note">[] };
