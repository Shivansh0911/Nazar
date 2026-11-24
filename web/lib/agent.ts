// Investigator API: start a run (SSE), runs, approvals, connected tools (MCP).
import { API_BASE, ApiError, getToken, setToken } from "./api";
import type { Level } from "./types";
import type { AskV2 } from "./types2";

export type StepStatus = "pending" | "doing" | "done" | "failed" | "skipped";
export interface PlanStep { id: number; title: string; how: string; status: StepStatus; finding: string | null; calls: number[]; added?: boolean }
export interface ToolEvent { index: number; name: string; label: string; state: "running" | "done" | "failed"; step: number | null; summary?: string; external?: boolean }
export interface AgentAction {
  id: number; tool: string; label: string; args: Record<string, unknown>; reason: string | null;
  status: "pending" | "running" | "done" | "failed" | "rejected"; result: { text?: string; error?: string; ok?: boolean } | null;
}
export type FindingLevel = Level | "external" | "unverified";
export interface Finding { title: string; detail: string; level: FindingLevel; calls: number[] }
export interface CaseFile extends AskV2 {
  run_id: number; goal: string; plan: PlanStep[]; findings: Finding[]; recommendations: string[]; actions: AgentAction[];
  trace: ToolEvent[]; external_servers: string[]; tool_calls: number; confidence: "high" | "low";
}
export interface RunRow {
  run_id: number; goal: string; camera_id: string | null; trigger: string; alert_id: number | null; status: "running" | "done" | "error";
  error: string | null; created_at: string; latency_ms: number | null; cost_inr: number; steps: number; pending_actions: number;
}
export interface McpServer {
  name: string; state: "idle" | "disabled" | "needs_config" | "connecting" | "connected" | "error" | "stopped"; transport: string;
  error: string | null; missing: string[]; description?: string | null;
  tools: { name: string; fn: string; description: string; needs_approval: boolean }[];
}
export interface ToolCatalog { native: { name: string; description: string }[]; servers: McpServer[]; config: string }

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const tok = getToken();
  if (tok) headers.set("X-Nazar-Token", tok);
  if (init.body) headers.set("Content-Type", "application/json");
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "Cannot reach the Nazar server. Is the API running?");
  }
  if (res.status === 401) {
    setToken(null);
    if (typeof window !== "undefined") window.location.href = "/login/";
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

export type InvestigateHandlers = {
  run?: (runId: number) => void;
  status?: (s: string) => void;
  plan?: (steps: PlanStep[]) => void;
  tool?: (t: ToolEvent) => void;
  action?: (a: AgentAction) => void;
  text?: (summary: string) => void;
};

/** POST /api/agent/investigate and follow the run live; resolves with the case file. */
export async function investigateStream(input: { goal?: string; camera_id?: string | null; alert_id?: number }, h: InvestigateHandlers,
  signal?: AbortSignal): Promise<CaseFile> {
  const headers = new Headers({ "Content-Type": "application/json" });
  const tok = getToken();
  if (tok) headers.set("X-Nazar-Token", tok);
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/agent/investigate`, { method: "POST", headers, body: JSON.stringify(input), signal });
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
  let result: CaseFile | null = null;
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
      if (ev === "run") h.run?.((d as { run_id: number }).run_id);
      else if (ev === "status") h.status?.(String(d));
      else if (ev === "plan") h.plan?.(d as PlanStep[]);
      else if (ev === "tool") h.tool?.(d as ToolEvent);
      else if (ev === "action") h.action?.(d as AgentAction);
      else if (ev === "text") h.text?.(String(d));
      else if (ev === "result") result = d as CaseFile;
      else if (ev === "error") error = String(d);
    }
  }
  if (error) throw new ApiError(500, error);
  if (!result) throw new ApiError(500, "The investigation stream ended early - open it again from Recent runs");
  return result;
}

export const agentApi = {
  tools: () => req<ToolCatalog>("/api/agent/tools"),
  runs: () => req<RunRow[]>("/api/agent/runs?limit=12"),
  run: (id: number) => req<RunRow & { plan: PlanStep[]; result: CaseFile | null }>(`/api/agent/runs/${id}`),
  decide: (runId: number, actionId: number, approve: boolean) =>
    req<AgentAction>(`/api/agent/runs/${runId}/actions/${actionId}`, { method: "POST", body: JSON.stringify({ approve }) }),
};
