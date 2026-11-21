"use client";

import Link from "next/link";
import { useState } from "react";
import { Maximize2, Play, Radio, Square } from "lucide-react";
import { api, mjpegUrl, snapshotUrl } from "@/lib/api";
import { fmtDayTime } from "@/lib/format";
import { Btn, Empty, Page } from "@/components/ui";
import { useApp } from "@/components/Providers";

export default function LivePage() {
  const { cameras, refreshCameras, toast } = useApp();
  const [big, setBig] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const live = cameras.filter((c) => c.live || c.edge_running);
  const idle = cameras.filter((c) => !(c.live || c.edge_running));

  const toggle = async (id: string, running: boolean) => {
    setBusy(id);
    try {
      if (running) await api.stopEdge(id);
      else await api.startEdge(id);
      setTimeout(refreshCameras, 1500);
    } catch (e) {
      toast((e as Error).message, "err");
    } finally {
      setBusy(null);
    }
  };

  return (
    <Page title="Live" subtitle="Every live camera, face-blurred, with what the tracker sees right now.">
      {live.length === 0 ? (
        <Empty title="No camera is live right now" icon={<Radio size={22} />}>
          Connect a CCTV or phone, or play a recorded camera as live below.
        </Empty>
      ) : (
        <div className={`grid gap-3 ${big ? "" : "md:grid-cols-2 xl:grid-cols-3"}`}>
          {live.filter((c) => !big || c.id === big).map((c) => (
            <div key={c.id} className="overflow-hidden rounded-3xl border border-line bg-surface">
              <div className="relative aspect-video bg-black">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={c.live ? `${mjpegUrl(c.id)}&overlay=1` : snapshotUrl(c.id)} alt={c.name} className="h-full w-full object-contain" />
                <span className="absolute left-2 top-2 rounded-full bg-danger px-2 py-0.5 text-[10px] font-semibold text-white"><span className="live-dot">●</span> {c.live ? "LIVE" : "STARTING"}</span>
                <button onClick={() => setBig(big ? null : c.id)} className="absolute right-2 top-2 rounded-full bg-black/60 p-1.5 text-white" aria-label="Enlarge"><Maximize2 size={14} /></button>
              </div>
              <div className="flex items-center gap-3 p-3">
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium">{c.name}</div>
                  <div className="text-xs text-muted">{c.today_count} people today{c.fps_proc ? ` · ${c.fps_proc.toFixed(1)} fps` : ""}{c.status_note ? ` · ${c.status_note}` : ""}</div>
                </div>
                <div className="ml-auto flex gap-2">
                  <Link href={`/ask/?camera=${encodeURIComponent(c.id)}`} className="rounded-full bg-primary-soft px-3 py-1 text-xs text-primary">Ask</Link>
                  <Btn kind="ghost" onClick={() => toggle(c.id, true)} disabled={busy === c.id} className="!px-3 !py-1 text-xs"><Square size={12} /> Stop</Btn>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
      {idle.length > 0 && (
        <div className="mt-6">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">Not live</h2>
          <div className="grid gap-2 md:grid-cols-2">
            {idle.map((c) => (
              <div key={c.id} className="flex items-center gap-3 rounded-2xl border border-line bg-surface p-2">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={snapshotUrl(c.id)} alt="" className="h-12 w-20 rounded-lg object-cover" onError={(e) => ((e.target as HTMLImageElement).style.opacity = "0")} />
                <div className="min-w-0">
                  <div className="truncate text-sm">{c.name}</div>
                  <div className="truncate text-[11px] text-muted">{c.coverage_to ? `last footage ${fmtDayTime(c.coverage_to)}` : c.kind}</div>
                </div>
                <Btn kind="soft" onClick={() => toggle(c.id, false)} disabled={busy === c.id} className="ml-auto !px-3 !py-1 text-xs">
                  <Play size={12} /> {c.kind === "file" ? "Play as live" : "Start"}
                </Btn>
              </div>
            ))}
          </div>
        </div>
      )}
    </Page>
  );
}
