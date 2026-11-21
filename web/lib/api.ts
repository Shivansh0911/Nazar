// Tiny API client. Token lives in localStorage after the passcode screen.
import type {
  AlertOut, AskResponse, CameraOut, ClipOut, EdgeStatus, Gap, Health, MetricsOut, Progress, RuleDraft, TrackOut, Zone, CountResult,
} from "./types";

export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
const TOKEN_KEY = "nazar_token";

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(t: string | null) {
  try {
    if (t) localStorage.setItem(TOKEN_KEY, t);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* private mode */
  }
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const tok = getToken();
  if (tok) headers.set("X-Nazar-Token", tok);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "Cannot reach the Nazar server. Is the API running?");
  }
  if (res.status === 401 && path !== "/api/auth") {
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

const q = (params: Record<string, string | number | boolean | null | undefined>) => {
  const u = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== null && v !== undefined && v !== "") u.set(k, String(v));
  });
  const s = u.toString();
  return s ? `?${s}` : "";
};

export const api = {
  auth: (passcode: string) => request<{ token: string }>("/api/auth", { method: "POST", body: JSON.stringify({ passcode }) }),
  health: () => request<Health>("/api/health"),
  cameras: () => request<CameraOut[]>("/api/cameras"),
  camera: (id: string) => request<CameraOut>(`/api/cameras/${encodeURIComponent(id)}`),
  createCamera: (body: { name: string; source_url: string; kind?: string; start?: boolean; id?: string }) =>
    request<CameraOut>("/api/cameras", { method: "POST", body: JSON.stringify(body) }),
  patchCamera: (id: string, body: { name?: string; zones?: Zone[] }) =>
    request<CameraOut>(`/api/cameras/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteCamera: (id: string) => request<{ ok: boolean }>(`/api/cameras/${encodeURIComponent(id)}`, { method: "DELETE" }),
  suggestZones: (id: string) => request<{ zones: Zone[] }>(`/api/cameras/${encodeURIComponent(id)}/suggest-zones`, { method: "POST" }),
  timeline: (id: string, from?: string, to?: string, zone?: string) =>
    request<CountResult>(`/api/cameras/${encodeURIComponent(id)}/timeline${q({ from, to, zone })}`),
  gaps: (id: string, from?: string, to?: string) =>
    request<{ gaps: Gap[]; offline_minutes: number }>(`/api/cameras/${encodeURIComponent(id)}/gaps${q({ from, to })}`),
  recentTracks: (id: string, from?: string, to?: string) =>
    request<TrackOut[]>(`/api/cameras/${encodeURIComponent(id)}/tracks${q({ from, to, limit: 24 })}`),
  startEdge: (id: string) => request<EdgeStatus & { status: string }>(`/api/cameras/${encodeURIComponent(id)}/start`, { method: "POST" }),
  stopEdge: (id: string) => request<{ stopped: boolean }>(`/api/cameras/${encodeURIComponent(id)}/stop`, { method: "POST" }),
  edge: (id: string) => request<EdgeStatus>(`/api/cameras/${encodeURIComponent(id)}/edge`),
  progress: (id: string) => request<Progress>(`/api/cameras/${encodeURIComponent(id)}/progress`),
  phoneSetup: (id: string) => request<{ srt: string; rtmp: string; source_url: string; host: string }>(`/api/phone-setup/${encodeURIComponent(id)}`),
  askText: (text: string, camera_id?: string | null) =>
    request<AskResponse>("/api/ask", { method: "POST", body: JSON.stringify({ text, camera_id: camera_id || null }) }),
  askVoice: (blob: Blob, filename: string, camera_id?: string | null) => {
    const fd = new FormData();
    fd.append("audio", blob, filename);
    if (camera_id) fd.append("camera_id", camera_id);
    return request<AskResponse>("/api/ask", { method: "POST", body: fd });
  },
  track: (id: number) => request<TrackOut & { path: number[][] }>(`/api/tracks/${id}`),
  similar: (id: number) => request<{ results: TrackOut[]; note?: string }>(`/api/tracks/${id}/similar?hours=24`),
  clipForTrack: (id: number) => request<ClipOut>(`/api/clips/track/${id}`),
  compileRule: (text: string, camera_id: string) =>
    request<RuleDraft>("/api/rules/compile", { method: "POST", body: JSON.stringify({ text, camera_id }) }),
  rules: () => request<RuleDraft[]>("/api/rules"),
  activateRule: (id: number) => request<RuleDraft>(`/api/rules/${id}/activate`, { method: "POST" }),
  deactivateRule: (id: number) => request<RuleDraft>(`/api/rules/${id}/deactivate`, { method: "POST" }),
  deleteRule: (id: number) => request<{ ok: boolean }>(`/api/rules/${id}`, { method: "DELETE" }),
  alerts: () => request<AlertOut[]>("/api/alerts?limit=50"),
  ackAlert: (id: number) => request<{ ok: boolean }>(`/api/alerts/${id}/ack`, { method: "POST" }),
  metrics: () => request<MetricsOut>("/api/metrics"),
};

export function withToken(url: string): string {
  const t = getToken();
  if (!t) return url;
  return url + (url.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(t);
}

export const snapshotUrl = (id: string, bust = 0) => withToken(`${API_BASE}/api/cameras/${encodeURIComponent(id)}/snapshot.jpg?b=${bust}`);
export const mjpegUrl = (id: string) => withToken(`${API_BASE}/api/cameras/${encodeURIComponent(id)}/live.mjpg`);
export const wsUrl = () => withToken(API_BASE.replace(/^http/, "ws") + "/api/ws");

export function uploadVideo(file: File, name: string, start: string | null, onProgress: (frac: number) => void) {
  return new Promise<{ camera: CameraOut; job_id: number; duration_s: number }>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/api/cameras/upload`);
    const t = getToken();
    if (t) xhr.setRequestHeader("X-Nazar-Token", t);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      try {
        const j = JSON.parse(xhr.responseText);
        if (xhr.status >= 200 && xhr.status < 300) resolve(j);
        else reject(new ApiError(xhr.status, j.error || xhr.statusText));
      } catch {
        reject(new ApiError(xhr.status, xhr.statusText));
      }
    };
    xhr.onerror = () => reject(new ApiError(0, "Upload failed - is the API running?"));
    const fd = new FormData();
    fd.append("file", file);
    fd.append("name", name);
    if (start) fd.append("start", start);
    xhr.send(fd);
  });
}
