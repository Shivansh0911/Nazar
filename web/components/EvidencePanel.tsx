"use client";

import { useState } from "react";
import { FileText, Sparkles } from "lucide-react";
import type { AskV2, Hit } from "@/lib/types2";
import { api2 } from "@/lib/api2";
import type { ClipTarget } from "./ClipPlayer";
import { RuleCard, GapNote } from "./cards";
import { ChartCard, DataTable } from "./charts";
import { CountCardV2, HitCard, JourneyView, NoteCard, VideoModal } from "./evidence";
import { LevelBadge } from "./ui";

/** Everything behind an answer: count + receipts, clips/hits, tables, charts, images, journey, rule, report. */
export function EvidencePanel({ resp, onOpen }: { resp: AskV2; onOpen: (t: ClipTarget) => void }) {
  const [kf, setKf] = useState<{ url: string | null; poster?: string | null; t: string; camera_id: string } | null>(null);
  const openKeyframe = async (h: { camera_id: string; t: string }) => {
    const t = new Date(h.t).getTime();
    setKf({ url: null, t: h.t, camera_id: h.camera_id });
    try {
      const r = await api2.clipRange(h.camera_id, new Date(t - 4000).toISOString(), new Date(t + 6000).toISOString());
      setKf({ url: r.url, poster: r.poster_url, t: h.t, camera_id: h.camera_id });
    } catch {
      setKf(null);
    }
  };
  const empty = !resp.count && !resp.clips.length && !resp.tables?.length && !resp.charts?.length && !resp.images?.length &&
    !resp.journey && !resp.rule && !resp.notes?.length && !resp.report && !resp.sec_events?.length;
  return (
    <div className="space-y-3">
      {resp.count && <CountCardV2 count={resp.count} queryId={resp.query_id} onOpen={onOpen} />}
      {resp.charts?.map((c, i) => <ChartCard key={i} chart={c} />)}
      {resp.tables?.map((t, i) => <DataTable key={i} table={t} />)}
      {resp.images?.map((im, i) => (
        <figure key={i} className="overflow-hidden rounded-2xl border border-line bg-surface-2">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={im.url} alt={im.kind} className="w-full" />
          <figcaption className="px-3 py-2 text-xs text-muted">{im.kind === "heatmap" ? "Where time was spent (warmer = longer)" : "Latest frame (faces blurred)"}{im.caption ? ` · ${im.caption}` : ""}</figcaption>
        </figure>
      ))}
      {resp.notes?.map((n, i) => <NoteCard key={i} text={n.text} ai={n.ai_generated} />)}
      {resp.journey && <JourneyView journey={resp.journey} onOpen={onOpen} />}
      {resp.clips.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-sm font-medium"><Sparkles size={14} className="text-primary" /> Matching moments</div>
          {resp.clips.map((c, i) => <HitCard key={`${c.kind}-${c.track_id}-${c.keyframe_id}-${i}`} hit={c} onOpen={onOpen} onKeyframe={openKeyframe} />)}
        </div>
      )}
      {resp.sec_events && resp.sec_events.length > 0 && (
        <div className="space-y-2">
          {resp.sec_events.map((e) => (
            <div key={e.id} className="flex items-center gap-2 rounded-2xl border border-line bg-surface-2 p-3 text-sm">
              <LevelBadge level={e.level} /> <span className="font-medium">{e.type.replace(/_/g, " ")}</span>
              <span className="text-xs text-muted">{e.camera_id} · {new Date(e.t).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit", timeZone: "Asia/Kolkata" })}</span>
              {e.track_ids[0] && <button className="ml-auto text-xs text-primary" onClick={() => onOpen({ track_id: e.track_ids[0], camera_id: e.camera_id, t_start: e.t, level: e.level, why: e.reason || e.type })}>Play</button>}
            </div>
          ))}
        </div>
      )}
      {resp.rule && <RuleCard rule={resp.rule} onOpen={onOpen} />}
      {resp.report && (
        <a href={resp.report.pdf_url} target="_blank" rel="noreferrer" className="flex items-center gap-2 rounded-2xl border border-line bg-surface-2 p-3 text-sm hover:border-primary">
          <FileText size={18} className="text-primary" /> <span className="font-medium">{resp.report.title}</span><span className="ml-auto text-xs text-primary">Open PDF</span>
        </a>
      )}
      {resp.taught?.ok && <div className="rounded-2xl border border-primary/40 bg-primary-soft p-3 text-sm">{resp.taught.message || `Now watching for ${resp.taught.name}.`}</div>}
      <GapNote gaps={resp.gaps} />
      {empty && <div className="text-sm text-muted">No clips or numbers for this answer.</div>}
      {kf && <VideoModal title={`Scene · ${kf.camera_id}`} sub={new Date(kf.t).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })} url={kf.url} poster={kf.poster} onClose={() => setKf(null)} />}
    </div>
  );
}

export function hasEvidence(resp: AskV2): number {
  return (resp.count ? 1 : 0) + resp.clips.length + (resp.tables?.length || 0) + (resp.charts?.length || 0) + (resp.images?.length || 0) +
    (resp.journey ? 1 : 0) + (resp.rule ? 1 : 0) + (resp.report ? 1 : 0) + (resp.notes?.length || 0) + (resp.sec_events?.length || 0);
}

export type { Hit };
