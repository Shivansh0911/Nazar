"use client";

import { useCallback, useEffect, useState } from "react";
import { Cpu, Gauge, IndianRupee, Timer } from "lucide-react";
import { api2 } from "@/lib/api2";
import { fmtInr } from "@/lib/format";
import type { MetricsV2 } from "@/lib/types2";
import { Card, ErrorBox, Page, Skeleton, Stat } from "@/components/ui";

const ms = (v: number | null | undefined) => (v ? `${(v / 1000).toFixed(1)} s` : "—");

export default function MetricsPage() {
  const [m, setM] = useState<MetricsV2 | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [visitors, setVisitors] = useState(500);
  const [questions, setQuestions] = useState(20);
  const [alertsDay, setAlertsDay] = useState(3);
  const load = useCallback(async () => {
    try {
      setM(await api2.metrics());
      setErr(null);
    } catch (e) {
      setErr((e as Error).message);
    }
  }, []);
  useEffect(() => {
    load();
    const t = setInterval(load, 20000);
    return () => clearInterval(t);
  }, [load]);

  const u = m?.unit_costs;
  const perQ = u?.question_p50_inr ?? null;
  const perCap = u?.caption_inr ?? null;
  const perVerify = u?.verify_per_call_inr ?? null;
  // projection from measured unit costs: indexing is local (0); questions + AI checks on alerts + captions on alerts
  const projection = perQ !== null ? questions * perQ + alertsDay * ((perVerify ?? 0) + (perCap ?? 0)) : null;
  const acc = (m?.accuracy || {}) as Record<string, { rows?: { name: string; truth: number; counted: number; err_pct: number }[]; summary?: string } | null>;

  return (
    <Page title="Insights" subtitle="Every number here is measured: costs from logged OpenAI calls, speed and accuracy from the evaluation scripts.">
      {err && <ErrorBox message={err} onRetry={load} />}
      {!m && !err && <div className="grid gap-3 md:grid-cols-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-28" />)}</div>}
      {m && u && (
        <div className="space-y-5">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat accent label="AI cost to index" value="₹0" hint={`${m.index.footage_hours.toFixed(1)} h footage · ${m.index.tracks_indexed.toLocaleString("en-IN")} tracks + ${m.index.keyframes_indexed.toLocaleString("en-IN")} frames indexed locally`} />
            <Stat label="Per question" value={fmtInr(u.question_p50_inr)} hint={`p50 · p90 ${fmtInr(u.question_p90_inr)} · ${u.questions} asked`} />
            <Stat label="Per AI check" value={fmtInr(u.verify_per_call_inr)} hint={`${u.verifications} verifications${u.verify_per_image_inr ? ` · ${fmtInr(u.verify_per_image_inr, 3)}/image` : ""}`} />
            <Stat label="Per incident report" value={fmtInr(u.report_inr)} hint={`${u.reports} report${u.reports === 1 ? "" : "s"} · incl. AI description`} />
          </div>
          <div className="grid gap-4 lg:grid-cols-[1.3fr_1fr]">
            <Card>
              <div className="mb-3 flex items-center gap-2 font-medium"><IndianRupee size={18} className="text-lime" /> What would it cost you?</div>
              <div className="grid grid-cols-3 gap-3 text-sm">
                <label>Visitors / day<input type="number" min={0} value={visitors} onChange={(e) => setVisitors(+e.target.value)} className="mt-1 w-full rounded-xl border border-line bg-surface-2 px-3 py-2" /></label>
                <label>Questions / day<input type="number" min={0} value={questions} onChange={(e) => setQuestions(+e.target.value)} className="mt-1 w-full rounded-xl border border-line bg-surface-2 px-3 py-2" /></label>
                <label>Alerts / day<input type="number" min={0} value={alertsDay} onChange={(e) => setAlertsDay(+e.target.value)} className="mt-1 w-full rounded-xl border border-line bg-surface-2 px-3 py-2" /></label>
              </div>
              <div className="mt-4 flex items-end gap-3">
                <div className="font-display text-6xl leading-none">{projection !== null ? fmtInr(projection) : "—"}</div>
                <div className="pb-1 text-sm text-muted">per day per site</div>
              </div>
              <div className="mt-2 text-xs text-muted">
                = {questions} × {fmtInr(perQ)} per question + {alertsDay} × ({fmtInr(perVerify)} AI check + {fmtInr(perCap)} description). Watching {visitors.toLocaleString("en-IN")} visitors costs ₹0 in AI: detection, tracking, counting and the visual index run on this machine.
              </div>
            </Card>
            <Card>
              <div className="mb-3 flex items-center gap-2 font-medium"><Timer size={18} className="text-primary" /> Answer speed</div>
              <div className="grid grid-cols-2 gap-3">
                <div><div className="text-xs text-muted">First words (p50)</div><div className="font-display text-4xl">{ms(m.latency.first_text_p50_ms)}</div><div className="text-[11px] text-muted">p90 {ms(m.latency.first_text_p90_ms)}</div></div>
                <div><div className="text-xs text-muted">Full answer (p50)</div><div className="font-display text-4xl">{ms(m.latency.p50_ms)}</div><div className="text-[11px] text-muted">p90 {ms(m.latency.p90_ms)}</div></div>
              </div>
              <div className="mt-2 text-xs text-muted">{m.latency.n} questions · {m.latency.models.map((x) => `${x.model} ×${x.n}`).join(", ")}</div>
            </Card>
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <div className="mb-3 flex items-center gap-2 font-medium"><Cpu size={18} className="text-primary" /> Pipeline speed</div>
              {m.pipeline ? (
                <div>
                  {m.pipeline.rows.map((r) => (
                    <div key={r[0]} className="flex items-center gap-3 border-t border-line py-2 text-sm first:border-0">
                      <span className="flex-1">{r[0]}</span><span className="font-display text-2xl">{r[3]}×</span><span className="w-20 text-right text-xs text-muted">real time</span>
                    </div>
                  ))}
                  <div className="mt-1 text-xs text-muted">{(m.pipeline.file_s / 60).toFixed(0)} min test file · timestamp drift {m.pipeline.drift_s.toFixed(2)} s · measured {m.pipeline.at.slice(0, 16).replace("T", " ")}</div>
                </div>
              ) : <div className="text-sm text-muted">Run <code>python scripts/bench_pipeline.py</code>.</div>}
            </Card>
            <Card>
              <div className="mb-3 flex items-center gap-2 font-medium"><Gauge size={18} className="text-primary" /> Accuracy</div>
              {acc.counts?.rows?.length ? (
                <table className="w-full text-sm">
                  <thead><tr className="text-xs text-muted"><th className="text-left font-medium">Window</th><th className="text-right font-medium">Hand count</th><th className="text-right font-medium">Nazar</th><th className="text-right font-medium">Error</th></tr></thead>
                  <tbody>{acc.counts.rows.map((r) => (
                    <tr key={r.name} className="border-t border-line"><td className="py-1.5">{r.name}</td><td className="text-right">{r.truth}</td><td className="text-right">{r.counted}</td><td className="text-right">{r.err_pct}%</td></tr>
                  ))}</tbody>
                </table>
              ) : <div className="text-sm text-muted">Run <code>python scripts/eval_counts.py</code> to measure count accuracy against hand counts.</div>}
              {acc.tracking?.summary && <div className="mt-2 text-xs text-muted">Tracking (MOT17): {acc.tracking.summary}</div>}
              <div className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
                {(["confirmed", "probable", "candidate"] as const).map((k) => (
                  <div key={k} className="rounded-xl bg-surface-2 p-2"><div className="font-display text-2xl">{m.level_distribution[k]}</div>{k}</div>
                ))}
              </div>
              <div className="mt-1 text-[11px] text-muted">Evidence levels shown in recent answers</div>
            </Card>
          </div>
          <Card>
            <div className="mb-2 flex items-baseline gap-2"><span className="font-medium">Spend</span><span className="text-xs text-muted">today {fmtInr(m.today_inr)} · total {fmtInr(m.total_inr)}</span></div>
            <div className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2 lg:grid-cols-3">
              {m.by_kind.map((k) => <div key={k.kind} className="flex justify-between border-b border-line py-1"><span>{k.kind} <span className="text-muted">×{k.calls}</span></span><span>{fmtInr(k.inr)}</span></div>)}
            </div>
            <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted">
              {m.by_tier.map((t) => <span key={t.tier} className="rounded-full bg-surface-2 px-2 py-1">{t.tier}: {t.calls} calls · {fmtInr(t.inr)}</span>)}
              <span className="rounded-full bg-surface-2 px-2 py-1">descriptions: {m.enrich_mode}</span>
            </div>
          </Card>
        </div>
      )}
    </Page>
  );
}
