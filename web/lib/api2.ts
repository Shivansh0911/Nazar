// v2 API calls: streaming ask (SSE), visual search, receipts, uploads, onboarding, reports, settings.
import { API_BASE, ApiError, getToken, setToken } from "./api";
import type { CameraOut } from "./types";
import type { AskV2, Digest, Hit, Journey, MetricsV2, ProbeResult, Receipt, ReportOut, SecEvent } from "./types2";

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const tok = getToken();
  if (tok) headers.set("X-Nazar-Token", tok);
  if (init.body && !(init.body instanceof FormData) && !(init.body instanceof Blob) && !headers.has("Content-Type"))
    headers.set("Content-Type", "application/json");
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "Cannot reach the Nazar server. Is the API running?");
  }
  if (res.status === 401) {
    setToken(null);
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) window.location.href = "/login/";
    throw new ApiError(401, "Please log in again");
  }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = j.error || j.detail || msg;
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return (await res.json()) as T;
}

const qs = (p: Record<string, string | number | null | undefined>) => {
  const u = new URLSearchParams();
  Object.entries(p).forEach(([k, v]) => v !== null && v !== undefined && v !== "" && u.set(k, String(v)));
  const s = u.toString();
  return s ? `?${s}` : "";
};

export type StreamHandlers = {
  status?: (s: string) => void;
  text?: (delta: string) => void;
  reset?: () => void;
  transcript?: (t: string) => void;
};

/** POST /api/ask/stream and parse server-sent events; resolves with the final answer. */
export async function askStream(input: { text?: string; audio?: { blob: Blob; filename: string } }, camera_id: string | null,
  h: StreamHandlers): Promise<AskV2> {
  const headers = new Headers();
  const tok = getToken();
  if (tok) headers.set("X-Nazar-Token", tok);
  let body: BodyInit;
  if (input.audio) {
    const fd = new FormData();
    fd.append("audio", input.audio.blob, input.audio.filename);
    if (camera_id) fd.append("camera_id", camera_id);
    body = fd;
  } else {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify({ text: input.text, camera_id });
  }
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/ask/stream`, { method: "POST", headers, body });
  } catch {
    throw new ApiError(0, "Cannot reach the Nazar server. Is the API running?");
  }
  if (res.status === 401) {
    setToken(null);
    window.location.href = "/login/";
    throw new ApiError(401, "Please log in again");
  }
  if (!res.ok || !res.body) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = j.error || j.detail || msg;
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, String(msg));
  }
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  let result: AskV2 | null = null;
  let error: string | null = null;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i: number;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, i);
      buf = buf.slice(i + 2);
      let ev = "message";
      let data = "";
      for (const line of chunk.split("\n")) {
        if (line.startsWith("event: ")) ev = line.slice(7);
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      let d: unknown = null;
      try {
        d = JSON.parse(data);
      } catch {
        continue;
      }
      if (ev === "status") h.status?.(String(d));
      else if (ev === "text") h.text?.(String(d));
      else if (ev === "reset") h.reset?.();
      else if (ev === "transcript") h.transcript?.(String(d));
      else if (ev === "result") result = d as AskV2;
      else if (ev === "error") error = String(d);
    }
  }
  if (error) throw new ApiError(500, error);
  if (!result) throw new ApiError(500, "The answer stream ended early - please try again");
  return result;
}

export const api2 = {
  visualSearch: (fd: FormData) =>
    req<{ hits: Hit[]; verified: boolean; note?: string; query_image_url?: string }>("/api/search/visual", { method: "POST", body: fd }),
  verify: (question: string, hits: Hit[]) =>
    req<{ hits: Hit[] }>("/api/search/verify", { method: "POST", body: JSON.stringify({ question, hits }) }),
  journey: (trackId: number) => req<Journey>(`/api/journey/${trackId}`),
  receipts: (qid: number, page = 0, hour?: string) =>
    req<{ total: number; items: Receipt[]; value: number; marked_wrong: number; after_review: number }>(
      `/api/receipts/${qid}${qs({ page, hour })}`),
  feedback: (kind: string, ref: string, correct: boolean) =>
    req<{ ok: boolean }>("/api/feedback", { method: "POST", body: JSON.stringify({ kind, ref, correct }) }),
  reel: (track_ids: number[], total?: number) =>
    req<{ url: string; poster_url: string | null; moments: number; total: number }>("/api/clips/reel",
      { method: "POST", body: JSON.stringify({ track_ids, total }) }),
  clipRange: (camera_id: string, from: string, to: string) =>
    req<{ url: string; poster_url: string | null; t0_ms: number; t1_ms: number }>(`/api/clips/range${qs({ camera_id, from, to })}`),
  metrics: () => req<MetricsV2>("/api/metrics"),
  uploadInit: (b: { filename: string; size: number; name?: string; recorded_at?: string | null }) =>
    req<{ upload_id: string; chunk_size: number; parts: number; received: number[] }>("/api/uploads/init",
      { method: "POST", body: JSON.stringify(b) }),
  uploadStatus: (id: string) => req<{ received: number[]; parts: number; chunk_size: number }>(`/api/uploads/${id}`),
  uploadPart: async (id: string, index: number, blob: Blob) => {
    const headers = new Headers({ "Content-Type": "application/octet-stream" });
    const tok = getToken();
    if (tok) headers.set("X-Nazar-Token", tok);
    const r = await fetch(`${API_BASE}/api/uploads/${id}/part/${index}`, { method: "PUT", headers, body: blob });
    if (!r.ok) throw new ApiError(r.status, `part ${index} failed`);
  },
  uploadComplete: (id: string) =>
    req<{ camera: CameraOut; job_id: number; duration_s: number; portrait: boolean; width: number; height: number }>(
      `/api/uploads/${id}/complete`, { method: "POST" }),
  analysis: (camera_id: string) =>
    req<{ job: { state: string; processed_s: number; duration_s: number; error: string | null } | null;
      stats: { people_so_far?: number; in_view?: number; objects_in_view?: number; speed_x?: number; processed_s?: number;
        duration_s?: number; state?: string } }>(`/api/analysis/${encodeURIComponent(camera_id)}/live`),
  presets: () => req<{ id: string; label: string; port: number; path: string | null; note: string }[]>("/api/cameras/presets"),
  testCamera: (b: Record<string, unknown>) => req<ProbeResult>("/api/cameras/test", { method: "POST", body: JSON.stringify(b) }),
  createRtsp: (b: Record<string, unknown>) => req<CameraOut>("/api/cameras/rtsp", { method: "POST", body: JSON.stringify(b) }),
  importCameras: (f: File) => {
    const fd = new FormData();
    fd.append("file", f);
    return req<{ import_id: string; rows: ProbeResult[]; working: number }>("/api/cameras/import", { method: "POST", body: fd });
  },
  importCommit: (import_id: string, rows: number[]) =>
    req<{ added: CameraOut[]; errors: { row: number; error: string }[] }>("/api/cameras/import/commit",
      { method: "POST", body: JSON.stringify({ import_id, rows }) }),
  discover: () => req<{ cameras: { ip: string; maker: string | null }[]; error?: string }>("/api/cameras/discover"),
  secEvents: (from?: string, to?: string) => req<SecEvent[]>(`/api/sec-events${qs({ from, to })}`),
  digest: () => req<Digest>("/api/digest"),
  reports: () => req<ReportOut[]>("/api/reports"),
  createReport: (b: { title: string; alert_id?: number; sec_event_id?: number; track_ids?: number[]; language: "en" | "hi" }) =>
    req<{ report_id: number; pdf_url: string; manifest_sha256: string }>("/api/reports", { method: "POST", body: JSON.stringify(b) }),
  settings: () => req<Record<string, unknown>>("/api/settings"),
  pairCode: () => req<{ code: string; bot: string | null; link: string | null; expires_s: number; paired: { chat_id: number; name: string | null }[] }>(
    "/api/telegram/pair-code", { method: "POST" }),
  customObjects: (camera_id?: string) =>
    req<{ id: number; camera_id: string; name: string; prompt_type: string; active: boolean }[]>(`/api/custom-objects${qs({ camera_id })}`),
  teach: (camera_id: string, name: string) =>
    req<{ ok: boolean; message: string }>("/api/custom-objects", { method: "POST", body: JSON.stringify({ camera_id, name }) }),
  teachPhoto: (camera_id: string, name: string, image: File, alert: boolean) => {
    const fd = new FormData();
    fd.append("camera_id", camera_id);
    fd.append("name", name);
    fd.append("image", image);
    fd.append("alert", String(alert));
    return req<{ ok: boolean; message: string; rule_id: number | null; replay: { sightings: number; hits: Hit[] } }>(
      "/api/custom-objects/photo", { method: "POST", body: fd });
  },
  deleteCustomObject: (id: number) => req<{ ok: boolean }>(`/api/custom-objects/${id}`, { method: "DELETE" }),
};
