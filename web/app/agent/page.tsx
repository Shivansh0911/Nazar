"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Check, CircleDashed, CircleSlash, Layers, Loader2, Plug, Plus, Send, ShieldCheck, Sparkles, Wrench, X,
} from "lucide-react";
import {
  agentApi, investigateStream, type AgentAction, type CaseFile, type Finding, type McpServer, type PlanStep, type RunRow,
  type ToolCatalog, type ToolEvent,
} from "@/lib/agent";
import { fmtDayTime } from "@/lib/format";
import { ClipPlayer, type ClipTarget } from "@/components/ClipPlayer";
import { AudioReply } from "@/components/cards";
import { EvidencePanel, hasEvidence } from "@/components/EvidencePanel";
import { Btn, Card, ErrorBox, LevelBadge, Shell, Spinner } from "@/components/ui";
import { useApp } from "@/components/Providers";

const GOALS = [
  "Kal raat kuch ajeeb hua? Poori jaanch karo aur batao",
  "Investigate the bag pickup at desk 14: who took it, where did they go, and prepare an incident report",
  "Compare today with yesterday across all cameras and tell me what changed",
  "आज सबसे ज़्यादा भीड़ कब थी और क्यों? पूरी जाँच करो",
];

function StepIcon({ s }: { s: PlanStep["status"] }) {
  if (s === "doing") return <Loader2 size={16} className="animate-spin text-primary" />;
  if (s === "done") return <span className="flex h-4 w-4 items-center justify-center rounded-full bg-success text-white"><Check size={11} strokeWidth={3} /></span>;
  if (s === "failed") return <span className="flex h-4 w-4 items-center justify-center rounded-full bg-danger text-white"><X size={11} strokeWidth={3} /></span>;
  if (s === "skipped") return <CircleSlash size={16} className="text-muted" />;
  return <CircleDashed size={16} className="text-muted" />;
}

function PlanView({ steps, tools }: { steps: PlanStep[]; tools: ToolEvent[] }) {
  return (
    <ol className="space-y-2.5">
      {steps.map((s) => {
        const mine = tools.filter((t) => t.step === s.id);
        return (
          <li key={s.id} className={`flex gap-3 ${s.status === "skipped" ? "opacity-60" : ""}`}>
            <div className="mt-0.5 shrink-0"><StepIcon s={s.status} /></div>
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium">
                {s.title}
                {s.added && <span className="ml-2 inline-flex items-center gap-0.5 rounded-full bg-primary-soft px-1.5 py-px align-middle text-[10px] font-normal text-primary"><Plus size={10} /> new lead</span>}
              </div>
              {s.finding ? <div className="mt-0.5 text-[13px] text-foreground/90">{s.finding}</div>
                : <div className="mt-0.5 text-xs text-muted">{s.how}</div>}
              {mine.length > 0 && (
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {mine.map((t) => (
                    <span key={t.index} title={t.name}
                      className={`inline-flex max-w-full items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] ${t.state === "failed" ? "border-danger/50 text-danger" : t.external ? "border-primary/50 text-primary" : "border-line text-muted"}`}>
                      {t.state === "running" ? <Loader2 size={10} className="animate-spin" /> : t.external ? <Plug size={10} /> : <Wrench size={10} />}
                      <span className="truncate">{t.label}{t.summary ? ` · ${t.summary}` : ""}</span>
                    </span>
                  ))}
                </div>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function FindingBadge({ level }: { level: Finding["level"] }) {
  if (level === "external")
    return <span className="inline-flex items-center gap-1 rounded-full border border-primary/50 px-2.5 py-0.5 text-xs text-primary"><Plug size={11} /> From a connected tool</span>;
  if (level === "unverified")
    return <span className="inline-flex items-center gap-1 rounded-full border border-dashed border-muted/70 px-2.5 py-0.5 text-xs text-muted">Agent’s reasoning · not evidence</span>;
  return <LevelBadge level={level} />;
}

function ActionCard({ a, runId, onDone }: { a: AgentAction; runId: number; onDone: (a: AgentAction) => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const decide = async (approve: boolean) => {
    setBusy(true);
    setErr(null);
    try {
      onDone(await agentApi.decide(runId, a.id, approve));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const pending = a.status === "pending";
  return (
    <div className={`rounded-2xl border p-3 ${pending ? "border-primary/60 bg-primary-soft" : "border-line bg-surface-2"}`}>
      <div className="flex items-center gap-2 text-sm font-medium">
        <ShieldCheck size={15} className="text-primary" /> {a.label}
        <span className="ml-auto text-xs font-normal text-muted">
          {pending ? "needs your approval" : a.status === "done" ? "done" : a.status === "rejected" ? "rejected" : a.status}
        </span>
      </div>
      {a.reason && <div className="mt-1 text-[13px]">{a.reason}</div>}
      <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-xl bg-background/60 p-2 font-mono text-[11px] text-muted">{JSON.stringify(a.args, null, 2)}</pre>
      {a.result?.error && <div className="mt-1 text-xs text-danger">{a.result.error}</div>}
      {a.status === "done" && a.result?.text && <div className="mt-1 line-clamp-3 text-xs text-muted">{a.result.text}</div>}
      {err && <div className="mt-1 text-xs text-danger">{err}</div>}
      {pending && (
        <div className="mt-2 flex gap-2">
          <Btn onClick={() => decide(true)} disabled={busy} className="!px-3 !py-1.5 !text-xs">{busy ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />} Approve and run</Btn>
          <Btn kind="ghost" onClick={() => decide(false)} disabled={busy} className="!px-3 !py-1.5 !text-xs">Reject</Btn>
        </div>
      )}
    </div>
  );
}

const STATE_TEXT: Record<McpServer["state"], string> = {
  connected: "connected", connecting: "starting…", needs_config: "needs a key", disabled: "off", error: "error", idle: "idle", stopped: "stopped",
};

function ToolsPanel({ cat }: { cat: ToolCatalog | null }) {
  const [open, setOpen] = useState<string | null>(null);
  if (!cat) return <Spinner label="Looking for connected tools…" />;
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2 rounded-2xl border border-line bg-surface-2 px-3 py-2 text-sm">
        <span className="h-2 w-2 rounded-full bg-success" /> <span className="font-medium">Nazar</span>
        <span className="ml-auto text-xs text-muted">{cat.native.length} tools</span>
      </div>
      {cat.servers.map((s) => (
        <div key={s.name} className="rounded-2xl border border-line bg-surface-2 px-3 py-2 text-sm">
          <button className="flex w-full items-center gap-2 text-left" onClick={() => setOpen(open === s.name ? null : s.name)}>
            <span className={`h-2 w-2 shrink-0 rounded-full ${s.state === "connected" ? "bg-success" : s.state === "error" ? "bg-danger" : s.state === "connecting" ? "animate-pulse bg-primary" : "bg-muted/50"}`} />
            <span className="truncate font-medium">{s.name}</span>
            <span className="ml-auto shrink-0 text-xs text-muted">{s.state === "connected" ? `${s.tools.length} tools` : STATE_TEXT[s.state]}</span>
          </button>
          {open === s.name && (
            <div className="mt-2 space-y-1 border-t border-line pt-2 text-xs text-muted">
              {s.description && <div>{s.description}</div>}
              {s.state === "needs_config" && <div>Add <span className="font-mono text-foreground">{s.missing.join(", ")}</span> to .env and restart the API.</div>}
              {s.state === "disabled" && <div>Set <span className="font-mono text-foreground">&quot;enabled&quot;: true</span> for it in mcp.servers.json.</div>}
              {s.error && <div className="text-danger">{s.error}</div>}
              {s.tools.map((t) => (
                <div key={t.fn} className="flex items-start gap-1.5">
                  {t.needs_approval ? <ShieldCheck size={12} className="mt-0.5 shrink-0 text-primary" /> : <Wrench size={12} className="mt-0.5 shrink-0" />}
                  <span><span className="font-mono text-foreground">{t.name}</span>{t.needs_approval ? " · asks you first" : ""}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
      {cat.servers.length === 0 && <div className="text-xs text-muted">No external tools yet. Add MCP servers to <span className="font-mono">mcp.servers.json</span>.</div>}
    </div>
  );
}

export default function AgentPage() {
  const { cameras } = useApp();
  const [camera, setCamera] = useState("");
  const [goal, setGoal] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [asked, setAsked] = useState<string | null>(null);
  const [steps, setSteps] = useState<PlanStep[]>([]);
  const [tools, setTools] = useState<ToolEvent[]>([]);
  const [actions, setActions] = useState<AgentAction[]>([]);
  const [runId, setRunId] = useState<number | null>(null);
  const [res, setRes] = useState<CaseFile | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [cat, setCat] = useState<ToolCatalog | null>(null);
  const [runs, setRuns] = useState<RunRow[]>([]);
  const [open, setOpen] = useState<ClipTarget | null>(null);
  const started = useRef(false);

  const refresh = useCallback(() => {
    agentApi.tools().then(setCat).catch(() => setCat({ native: [], servers: [], config: "" }));
    agentApi.runs().then(setRuns).catch(() => undefined);
  }, []);

  const reset = () => {
    setSteps([]); setTools([]); setActions([]); setRes(null); setErr(null); setRunId(null);
  };

  const start = useCallback(async (input: { goal?: string; alert_id?: number }) => {
    reset();
    setAsked(input.goal || `Alert #${input.alert_id}`);
    setBusy(true);
    setStatus("Reading the goal…");
    try {
      const r = await investigateStream({ ...input, camera_id: camera || null }, {
        run: setRunId,
        status: setStatus,
        plan: setSteps,
        tool: (t) => setTools((prev) => [...prev.filter((x) => x.index !== t.index), t]),
        action: (a) => setActions((prev) => [...prev, a]),
      });
      setRes(r);
      setSteps(r.plan);
      setActions(r.actions);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
      refresh();
    }
  }, [camera, refresh]);

  const openRun = async (id: number) => {
    reset();
    setErr(null);
    try {
      const r = await agentApi.run(id);
      setAsked(r.goal);
      setRunId(r.run_id);
      setSteps(r.plan || []);
      if (r.result) {
        setRes(r.result);
        setTools(r.result.trace || []);
        setActions(r.result.actions || []);
      } else if (r.status === "error") setErr(r.error || "This run failed.");
      else setStatus("This run is still working…");
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  useEffect(() => {
    refresh();
    if (started.current) return;
    started.current = true;
    const p = new URLSearchParams(window.location.search);
    if (p.get("alert")) start({ alert_id: Number(p.get("alert")) });
    else if (p.get("run")) openRun(Number(p.get("run")));
    else if (p.get("goal")) start({ goal: p.get("goal") || "" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // a server that is still starting (first npx download) shows up without a reload
  useEffect(() => {
    if (!cat?.servers.some((s) => s.state === "connecting")) return;
    const t = setTimeout(() => agentApi.tools().then(setCat).catch(() => undefined), 4000);
    return () => clearTimeout(t);
  }, [cat]);

  const submit = () => {
    const g = goal.trim();
    if (!g || busy) return;
    setGoal("");
    start({ goal: g });
  };
  const pending = actions.filter((a) => a.status === "pending").length;
  const idle = !asked && !busy;

  return (
    <Shell title="Investigate">
      <main className="mx-auto grid w-full max-w-6xl gap-6 px-4 py-5 md:px-8 md:py-8 lg:grid-cols-[minmax(0,1fr)_19rem]">
        <section className="min-w-0 space-y-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">Investigate</h1>
            <div className="mt-1 text-sm text-muted">Give Nazar a goal, not a question. It plans, checks the footage step by step, follows leads, and asks you before it changes or sends anything.</div>
          </div>
          <Card className="!p-3">
            <textarea value={goal} onChange={(e) => setGoal(e.target.value)} rows={2} maxLength={2000} disabled={busy}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } }}
              placeholder="What should Nazar find out? e.g. “Kal raat counter pe kya hua? Jaanch karke guard group ko batao.”"
              className="w-full resize-none bg-transparent px-2 py-1.5 text-[15px] outline-none placeholder:text-muted" />
            <div className="flex items-center gap-2 px-1">
              <select value={camera} onChange={(e) => setCamera(e.target.value)} aria-label="Camera" disabled={busy}
                className="max-w-[11rem] rounded-full border border-line bg-surface-2 px-3 py-1.5 text-xs">
                <option value="">All cameras</option>
                {cameras.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
              <Btn onClick={submit} disabled={busy || !goal.trim()} className="ml-auto">{busy ? <Loader2 size={15} className="animate-spin" /> : <Send size={15} />} Investigate</Btn>
            </div>
          </Card>
          {idle && (
            <div className="flex flex-wrap gap-2">
              {GOALS.map((g) => <button key={g} onClick={() => start({ goal: g })}
                className="rounded-full border border-line bg-surface px-3 py-2 text-left text-sm hover:border-primary hover:text-primary">{g}</button>)}
            </div>
          )}
          {asked && (
            <div className="flex justify-end"><div className="max-w-[85%] rounded-3xl rounded-br-lg bg-primary px-4 py-2.5 text-[15px] text-on-primary">{asked}</div></div>
          )}
          {err && <ErrorBox message={err} />}
          {(steps.length > 0 || busy) && (
            <Card>
              <div className="mb-3 flex items-center gap-2 text-sm font-semibold"><Sparkles size={15} className="text-primary" /> Plan
                {busy && <span className="ml-auto"><Spinner label={status} /></span>}
                {!busy && res && <span className="ml-auto text-xs font-normal text-muted">{res.tool_calls} tool calls · {(res.latency_ms / 1000).toFixed(0)} s · ₹{(res.cost_inr ?? 0).toFixed(2)}</span>}
              </div>
              {steps.length ? <PlanView steps={steps} tools={tools} /> : <div className="text-sm text-muted">Writing the plan…</div>}
            </Card>
          )}
          {!res && actions.length > 0 && runId && (
            <div className="space-y-2">{actions.map((a) => <ActionCard key={a.id} a={a} runId={runId} onDone={(n) => setActions((p) => p.map((x) => (x.id === n.id ? n : x)))} />)}</div>
          )}
          {res && (
            <>
              <Card className="space-y-3">
                <div className="text-xs font-medium uppercase tracking-wide text-muted">Case file #{res.run_id}{res.confidence === "low" ? " · the agent is not sure" : ""}</div>
                <div className="text-[15px] leading-relaxed">{res.reply_text}</div>
                {res.audio_url && <AudioReply url={res.audio_url} autoPlay={false} />}
                {res.findings.length > 0 && (
                  <div className="space-y-2">
                    {res.findings.map((f, i) => (
                      <div key={i} className="rounded-2xl border border-line bg-surface-2 p-3">
                        <div className="flex flex-wrap items-center gap-2"><span className="text-sm font-medium">{f.title}</span><FindingBadge level={f.level} /></div>
                        <div className="mt-1 text-[13px] text-foreground/90">{f.detail}</div>
                      </div>
                    ))}
                  </div>
                )}
                {res.recommendations.length > 0 && (
                  <div>
                    <div className="mb-1 text-xs font-medium uppercase tracking-wide text-muted">Suggested next</div>
                    <ul className="list-disc space-y-0.5 pl-5 text-sm">{res.recommendations.map((r) => <li key={r}>{r}</li>)}</ul>
                  </div>
                )}
              </Card>
              {actions.length > 0 && (
                <div className="space-y-2">
                  <div className="flex items-center gap-2 text-sm font-semibold"><ShieldCheck size={15} className="text-primary" /> Actions{pending ? ` · ${pending} waiting for you` : ""}</div>
                  {actions.map((a) => <ActionCard key={a.id} a={a} runId={res.run_id} onDone={(n) => setActions((p) => p.map((x) => (x.id === n.id ? n : x)))} />)}
                </div>
              )}
              {hasEvidence(res) > 0 && (
                <div>
                  <div className="mb-2 flex items-center gap-2 text-sm font-semibold"><Layers size={15} className="text-primary" /> Evidence</div>
                  <EvidencePanel resp={res} onOpen={setOpen} />
                </div>
              )}
              {res.followups.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {res.followups.map((f) => <button key={f} disabled={busy} onClick={() => start({ goal: f })}
                    className="rounded-full bg-surface-2 px-3 py-1 text-xs hover:bg-primary hover:text-on-primary">{f}</button>)}
                </div>
              )}
            </>
          )}
        </section>
        <aside className="space-y-5">
          <div>
            <div className="mb-2 flex items-center gap-2 text-sm font-semibold"><Plug size={15} className="text-primary" /> Connected tools</div>
            <ToolsPanel cat={cat} />
            <div className="mt-2 text-xs text-muted">External tools speak MCP. Read-only ones run on their own; anything that sends, writes or switches something waits for your approval.</div>
          </div>
          {runs.length > 0 && (
            <div>
              <div className="mb-2 text-sm font-semibold">Recent runs</div>
              <div className="space-y-1.5">
                {runs.map((r) => (
                  <button key={r.run_id} onClick={() => openRun(r.run_id)} disabled={busy}
                    className={`block w-full rounded-2xl border bg-surface px-3 py-2 text-left hover:border-primary/60 ${runId === r.run_id ? "border-primary/60" : "border-line"}`}>
                    <div className="line-clamp-2 text-[13px]">{r.goal}</div>
                    <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-muted">
                      {fmtDayTime(r.created_at)} · {r.status === "done" ? `${r.steps} steps` : r.status}
                      {r.trigger !== "user" && <span>· {r.trigger}</span>}
                      {r.pending_actions > 0 && <span className="ml-auto rounded-full bg-primary-soft px-1.5 text-primary">{r.pending_actions} to approve</span>}
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}
        </aside>
      </main>
      {open && <ClipPlayer target={open} onClose={() => setOpen(null)} />}
    </Shell>
  );
}
