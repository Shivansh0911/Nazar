"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Bell, FileText, ShieldAlert, ShieldCheck, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import { api2 } from "@/lib/api2";
import { fmtDayTime } from "@/lib/format";
import type { SecEvent } from "@/lib/types2";
import type { RuleDraft } from "@/lib/types";
import { AlertBubble, RuleCard } from "@/components/cards";
import { ClipPlayer, type ClipTarget } from "@/components/ClipPlayer";
import { Btn, Empty, ErrorBox, LevelBadge, Page, Skeleton, inputCls } from "@/components/ui";
import { useApp } from "@/components/Providers";

const PRESETS = [
  { k: "loitering", t: "Agar koi 2 minute se zyada ek jagah ruke toh batana", d: "Loitering" },
  { k: "after_hours", t: "Raat 11 baje se subah 6 baje tak koi bhi dikhe toh batao", d: "After-hours" },
  { k: "crowding", t: "5 se zyada log ek saath ho jaayein toh batana", d: "Crowding" },
  { k: "removed", t: "Koi bag uthaye toh mujhe batana", d: "Object taken" },
];
const TYPE_LABEL: Record<string, string> = {
  loitering: "Loitering", abandoned_object: "Abandoned object", object_removed: "Object taken", running: "Running",
  fall: "Possible fall", crowding: "Crowding", after_hours: "After-hours presence", possible_snatch: "Possible snatch", wrong_way: "Wrong way",
};

export default function AlertsPage() {
  const { alerts, cameras, toast, refreshAlerts } = useApp();
  const [tab, setTab] = useState<"alerts" | "security">("alerts");
  const [events, setEvents] = useState<SecEvent[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState<ClipTarget | null>(null);
  const [cam, setCam] = useState("");
  const [draft, setDraft] = useState<RuleDraft | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  const load = useCallback(() => {
    api2.secEvents().then((e) => { setEvents(e); setErr(null); }).catch((e) => setErr(e.message));
  }, []);
  useEffect(() => { load(); refreshAlerts(); }, [load, refreshAlerts]);
  useEffect(() => { if (!cam && cameras.length) setCam(cameras[0].id); }, [cameras, cam]);

  const preset = async (text: string, k: string) => {
    if (!cam) return;
    setBusy(k);
    setDraft(null);
    try {
      setDraft(await api.compileRule(text, cam));
    } catch (e) {
      toast((e as Error).message, "err");
    } finally {
      setBusy(null);
    }
  };
  const report = async (b: { alert_id?: number; sec_event_id?: number; title: string }) => {
    setBusy(`r${b.alert_id ?? b.sec_event_id}`);
    // open the tab inside the click (popup blockers allow it), point it at the PDF when it is ready
    const tab = window.open("", "_blank");
    try {
      const r = await api2.createReport({ ...b, language: "en" });
      toast("Incident report ready");
      if (tab && !tab.closed) tab.location.href = r.pdf_url;
      else window.location.href = r.pdf_url;
    } catch (e) {
      tab?.close();
      toast((e as Error).message, "err");
    } finally {
      setBusy(null);
    }
  };
  const shown = (events || []).filter((e) => !filter || e.type === filter);

  return (
    <Page title="Alerts & rules" subtitle="Live alerts from your rules, security events found in the footage, and the security pack."
      actions={<Link href="/rules/" className="rounded-full border border-line px-4 py-2 text-sm hover:bg-surface-2">Manage rules</Link>}>
      <div className="mb-4 flex gap-1 rounded-full border border-line bg-surface p-1 md:w-fit">
        {([["alerts", "Alert inbox", Bell], ["security", "Security events", ShieldAlert]] as const).map(([id, label, Icon]) => (
          <button key={id} onClick={() => setTab(id)} className={`flex flex-1 items-center justify-center gap-1.5 rounded-full px-4 py-2 text-sm ${tab === id ? "bg-primary text-on-primary" : "text-muted"}`}>
            <Icon size={15} /> {label}
          </button>
        ))}
      </div>
      {tab === "alerts" ? (
        <div className="grid gap-5 lg:grid-cols-[1fr_24rem]">
          <div className="space-y-3">
            {alerts.length === 0 ? <Empty title="No alerts yet" icon={<Bell size={22} />}>Activate a rule — Nazar replays it on yesterday first, then watches live.</Empty> :
              alerts.slice(0, 30).map((a) => (
                <div key={a.id}>
                  <AlertBubble alert={a} onOpen={setOpen} autoPlay={false} />
                  <button onClick={() => report({ alert_id: a.id, title: `Alert #${a.id} · ${a.camera_name || a.camera_id}` })} disabled={busy === `r${a.id}`}
                    className="mt-1 inline-flex items-center gap-1 text-xs text-primary disabled:opacity-50"><FileText size={13} /> {busy === `r${a.id}` ? "Preparing PDF…" : "Incident report (PDF)"}</button>
                  <a href={`/agent/?alert=${a.id}`} className="ml-3 mt-1 inline-flex items-center gap-1 text-xs text-primary"><Sparkles size={13} /> Investigate</a>
                </div>
              ))}
          </div>
          <div className="space-y-3">
            <div className="rounded-3xl border border-line bg-surface p-4">
              <div className="mb-2 flex items-center gap-2 text-sm font-semibold"><Sparkles size={16} className="text-lime" /> Security pack</div>
              <select value={cam} onChange={(e) => setCam(e.target.value)} className={inputCls} aria-label="Camera for preset">
                {cameras.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
              <div className="mt-2 grid grid-cols-2 gap-2">
                {PRESETS.map((p) => (
                  <Btn key={p.k} kind="ghost" onClick={() => preset(p.t, p.k)} disabled={!!busy} className="!rounded-2xl !py-2.5 text-xs">{busy === p.k ? "Building…" : p.d}</Btn>
                ))}
              </div>
              <div className="mt-2 text-[11px] text-muted">Each rule is replayed on the last day of footage before you activate it.</div>
            </div>
            {draft && <RuleCard rule={draft} onOpen={setOpen} />}
          </div>
        </div>
      ) : (
        <div>
          <div className="mb-3 flex flex-wrap gap-1.5">
            <button onClick={() => setFilter("")} className={`rounded-full px-3 py-1 text-xs ${!filter ? "bg-primary text-on-primary" : "border border-line"}`}>All</button>
            {Object.entries(TYPE_LABEL).map(([k, v]) => (
              <button key={k} onClick={() => setFilter(k)} className={`rounded-full px-3 py-1 text-xs ${filter === k ? "bg-primary text-on-primary" : "border border-line"}`}>{v}</button>
            ))}
          </div>
          {err && <ErrorBox message={err} onRetry={load} />}
          {!events && !err && <div className="space-y-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-20" />)}</div>}
          {events && shown.length === 0 && <Empty title="No security events" icon={<ShieldCheck size={22} />}>Nothing unusual was found in the footage for this filter.</Empty>}
          <div className="grid gap-2 md:grid-cols-2">
            {shown.map((e) => (
              <div key={e.id} className={`flex gap-3 rounded-2xl p-3 ${e.level === "candidate" ? "border border-dashed border-muted/50" : "border border-line bg-surface"}`}>
                {e.thumb_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={e.thumb_url} alt="" className="h-20 w-16 shrink-0 rounded-xl object-cover" />
                ) : <div className="h-20 w-16 shrink-0 rounded-xl bg-line" />}
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-1.5"><span className="text-sm font-medium">{TYPE_LABEL[e.type] || e.type}</span><LevelBadge level={e.level} verified={!!(e as SecEvent & { verified_by?: string }).verified_by?.startsWith("ai:yes")} /></div>
                  <div className="text-xs text-muted">{e.camera_name || e.camera_id} · {fmtDayTime(e.t)}</div>
                  <div className="mt-0.5 line-clamp-2 text-xs">{e.reason}</div>
                  <div className="mt-1 flex gap-3">
                    {e.track_ids[0] && <button className="text-xs text-primary" onClick={() => setOpen({ track_id: e.track_ids[0], camera_id: e.camera_id, t_start: e.t, level: e.level, why: e.reason || e.type })}>Play</button>}
                    <button className="text-xs text-primary disabled:opacity-50" disabled={busy === `r${e.id}`} onClick={() => report({ sec_event_id: e.id, title: `${TYPE_LABEL[e.type] || e.type} · ${e.camera_name || e.camera_id}` })}>
                      {busy === `r${e.id}` ? "Preparing…" : "Report"}
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
          <div className="mt-4 text-xs text-muted">Heuristic events start as Candidates; an AI check of 6 blurred frames upgrades them to Probable. After-hours presence and crowding are tracker facts.</div>
        </div>
      )}
      {open && <ClipPlayer target={open} onClose={() => setOpen(null)} />}
    </Page>
  );
}
