"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fmtInr } from "@/lib/format";
import type { MetricsOut } from "@/lib/types";
import { Card, ErrorBox, Page, Spinner } from "@/components/ui";

export default function MetricsPage() {
  const [m, setM] = useState<MetricsOut | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setM(await api.metrics());
      setErr(null);
    } catch (e) {
      setErr((e as Error).message);
    }
  }, []);
  useEffect(() => {
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [load]);

  return (
    <Page wide>
      <h1 className="text-xl font-semibold">Cost &amp; quality</h1>
      <p className="mt-1 text-sm text-muted">Every OpenAI call is logged with its cost. Numbers below come straight from those rows.</p>
      {err && <div className="mt-3"><ErrorBox message={err} onRetry={load} /></div>}
      {!m && !err && <div className="mt-4"><Spinner label="Loading…" /></div>}
      {m && (
        <div className="mt-4 grid gap-4 md:grid-cols-3">
          <Card className="md:col-span-2">
            <div className="text-sm text-muted">Cost per camera-day</div>
            <div className="mt-1 flex flex-wrap items-end gap-x-4 gap-y-1">
              <div className="text-5xl font-bold tracking-tight">{fmtInr(m.cost_per_camera_day_inr)}</div>
              {m.ratio && m.ratio >= 2 ? <div className="rounded-full bg-lime px-3 py-1 text-sm font-semibold text-slate-900">{m.ratio.toLocaleString("en-IN")}× cheaper</div> : null}
            </div>
            <div className="mt-2 text-sm text-muted">
              vs. <b>{fmtInr(m.naive_per_camera_day_inr, 0)}</b> if one image per second went to AI (measured price of one caption image × 86,400; real full frames would cost more).
            </div>
            {m.cost_per_camera_day_inr === null && (
              <div className="mt-2 text-xs text-muted">Shows once tracks are enriched (needs OPENAI_API_KEY). Footage watched so far: {m.footage_hours.toFixed(2)} h.</div>
            )}
            {m.per_track_inr != null && (
              <div className="mt-3 rounded-xl bg-background p-3 text-sm">
                <div><b>{fmtInr(m.per_track_inr, 3)}</b> per person/vehicle described · {m.tracks_described} described</div>
                <div className="mt-1 text-xs text-muted">
                  Cost follows activity, not time: this demo footage is rush-hour dense (~{m.tracks_per_hour?.toLocaleString("en-IN")} described per hour),
                  so its camera-day projection is close to the naive one. Example: a shop with 500 visitors a day ≈ {fmtInr(m.per_track_inr * 500)} per day.
                </div>
              </div>
            )}
            <div className="mt-3 text-xs text-muted">
              How: CV watches every frame for free (YOLO + tracker on the edge); OpenAI only sees 1–3 face-blurred crops per tracked person/vehicle
              and your questions. Based on {m.footage_hours.toFixed(2)} h of footage.
            </div>
          </Card>
          <Card>
            <div className="text-sm text-muted">Total spend</div>
            <div className="mt-1 text-3xl font-bold">{fmtInr(m.total_inr)}</div>
            <div className="text-xs text-muted">${m.total_usd.toFixed(4)}{m.unknown_price_calls ? ` · ${m.unknown_price_calls} calls with unknown price` : ""}</div>
            <div className="mt-3 space-y-1">
              {m.by_kind.map((k) => (
                <div key={k.kind} className="flex justify-between text-sm"><span>{k.kind} <span className="text-muted">×{k.calls}</span></span><span>{fmtInr(k.inr)}</span></div>
              ))}
              {!m.by_kind.length && <div className="text-sm text-muted">No AI calls yet.</div>}
            </div>
          </Card>
          <Card>
            <div className="text-sm text-muted">Tracks processed</div>
            <div className="mt-1 text-3xl font-bold">{m.tracks_processed.toLocaleString("en-IN")}</div>
            <div className="text-xs text-muted">Enrichment backlog: {m.enrich_backlog}</div>
          </Card>
          <Card>
            <div className="text-sm text-muted">Ask latency</div>
            <div className="mt-1 text-3xl font-bold">{m.ask_latency_p50_ms ? `${(m.ask_latency_p50_ms / 1000).toFixed(1)} s` : "—"}</div>
            <div className="text-xs text-muted">p50 · p90 {m.ask_latency_p90_ms ? `${(m.ask_latency_p90_ms / 1000).toFixed(1)} s` : "—"} · {m.query_count} questions</div>
          </Card>
          <Card>
            <div className="text-sm text-muted">Evidence in answers</div>
            <div className="mt-2 space-y-1 text-sm">
              <div className="flex justify-between"><span>Confirmed</span><span>{m.level_distribution.confirmed}</span></div>
              <div className="flex justify-between"><span>Probable</span><span>{m.level_distribution.probable}</span></div>
              <div className="flex justify-between"><span>Candidate</span><span>{m.level_distribution.candidate}</span></div>
            </div>
          </Card>
          {m.eval && (
            <Card className="md:col-span-3">
              <div className="text-sm font-medium">Evaluation (scripts/eval_*)</div>
              <pre className="mt-2 overflow-x-auto rounded-xl bg-background p-3 text-xs">{JSON.stringify(m.eval, null, 2)}</pre>
            </Card>
          )}
          <Card className="md:col-span-3">
            <div className="text-sm font-medium">By model</div>
            <div className="mt-2 grid gap-1 text-sm sm:grid-cols-2">
              {m.by_model.map((x) => (
                <div key={x.model} className="flex justify-between"><code className="text-xs">{x.model}</code><span>{fmtInr(x.inr)} · {x.calls} calls</span></div>
              ))}
              {!m.by_model.length && <div className="text-muted">—</div>}
            </div>
          </Card>
        </div>
      )}
    </Page>
  );
}
