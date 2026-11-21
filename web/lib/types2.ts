// v2 payloads (mirrors backend/nazar/api/*: visual, agent v2, metrics v2, onboarding, reports).
import type { AskResponse, CameraOut, ClipItem, CountResult, Level } from "./types";

export interface Receipt {
  track_id: number;
  camera_id: string;
  t: string;
  zone?: string | null;
  zones?: string[];
  thumb_url: string | null;
  level: Level;
  marked_wrong?: boolean;
}

export interface CountV2 extends CountResult {
  receipts?: Receipt[];
  receipts_total?: number;
  receipt_ids?: number[];
}

export interface TableOut {
  title: string;
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
  sql: string | null;
  level: "confirmed";
  change_pct?: number | null;
}

export interface ChartOut {
  type: "bar" | "line" | "pie" | "table";
  title: string;
  x: string;
  y: string;
  unit: string;
  data: { x: string | number; y: number }[];
}

export interface Hit {
  kind: "track" | "keyframe";
  id: number;
  track_id: number | null;
  camera_id: string;
  camera_name?: string;
  cls: string;
  t: string;
  t_start: string;
  t_end: string;
  sim: number;
  level: Level;
  why: string;
  caption: string | null;
  thumb_url: string | null;
  verified?: "yes" | "no" | "unclear";
  zones?: string[];
}

export interface JourneyStep {
  track_id: number;
  camera_id: string;
  camera_name?: string;
  cls: string;
  t_start: string;
  t_end: string;
  sim: number;
  level: Level;
  why: string;
  thumb_url: string | null;
  anchor?: boolean;
}

export interface Journey {
  track_id: number;
  steps: JourneyStep[];
  cameras?: string[];
  summary?: string;
  note?: string | null;
}

export interface SecEvent {
  id: number;
  camera_id: string;
  camera_name?: string;
  type: string;
  t: string;
  t_end?: string;
  track_ids: number[];
  level: Level;
  reason: string | null;
  thumb_url?: string | null;
}

export type ClipV2 = ClipItem & { kind?: string; keyframe_id?: number | null; verified?: string };

export interface AskV2 extends Omit<AskResponse, "count" | "clips"> {
  count: CountV2 | null;
  clips: ClipV2[];
  first_text_ms?: number;
  model?: string;
  clarify?: { question: string; options: string[] } | null;
  tables?: TableOut[];
  charts?: ChartOut[];
  images?: { url: string; kind: string; camera_id?: string; caption?: string | null }[];
  notes?: { kind: string; text: string; ai_generated: boolean; camera_id?: string }[];
  journey?: Journey | null;
  sec_events?: SecEvent[];
  report?: { report_id: number; pdf_url: string; title: string } | null;
  taught?: { ok: boolean; name: string; camera_id: string; message?: string } | null;
  cached?: boolean;
}

export interface UnitCosts {
  index_per_hour_inr: number;
  question_p50_inr: number | null;
  question_p90_inr: number | null;
  questions: number;
  verify_per_call_inr: number | null;
  verify_per_image_inr: number | null;
  verifications: number;
  report_inr: number | null;
  reports: number;
  caption_inr: number | null;
  captions_24h_inr: number;
}

export interface MetricsV2 {
  usd_inr: number;
  total_inr: number;
  today_inr: number;
  enrich_mode: string;
  unit_costs: UnitCosts;
  latency: {
    p50_ms: number | null; p90_ms: number | null; first_text_p50_ms: number | null; first_text_p90_ms: number | null;
    n: number; models: { model: string; n: number }[];
  };
  index: { footage_hours: number; tracks: number; tracks_indexed: number; keyframes_indexed: number };
  pipeline: { at: string; file_s: number; rows: [string, number, number, number, number | null][]; drift_s: number } | null;
  accuracy: Record<string, unknown>;
  level_distribution: Record<Level, number>;
  by_kind: { kind: string; inr: number; calls: number }[];
  by_model: { model: string; inr: number; calls: number }[];
  by_tier: { tier: string; inr: number; calls: number }[];
}

export interface ProbeResult {
  ok: boolean;
  error?: string;
  codec?: string;
  width?: number;
  height?: number;
  fps?: number | null;
  thumbnail?: string | null;
  url_preview?: string;
  row?: number;
  name?: string;
  ms?: number;
}

export interface ReportOut {
  id: number;
  at: string;
  title: string;
  language: string;
  pdf_url: string | null;
  manifest_sha256: string | null;
  preview_url?: string | null;
}

export interface Digest {
  text: string;
  audio_url: string | null;
  items: SecEvent[];
  anomalies: { camera_id: string; hour: string; count: number; normal: number; z: number; note?: string }[];
  totals: { camera_id: string; name: string; people: number; normal: number | null }[];
  generated_at: string;
}

export type { CameraOut };
