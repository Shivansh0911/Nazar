"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { MessageCircle, Play, Square } from "lucide-react";
import { api, mjpegUrl, snapshotUrl } from "@/lib/api";
import { fmtDayTime, fmtTime } from "@/lib/format";
import type { CameraOut, CountResult, Gap, TrackOut } from "@/lib/types";
import { ClipPlayer, type ClipTarget } from "@/components/ClipPlayer";
import { ZoneEditor } from "@/components/ZoneEditor";
import { Card, Empty, ErrorBox, MiniBars, Page, Spinner } from "@/components/ui";

export default function CameraPage() {
  const [id, setId] = useState<string | null>(null);
  const [cam, setCam] = useState<CameraOut | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [timeline, setTimeline] = useState<CountResult | null>(null);
  const [gaps, setGaps] = useState<Gap[]>([]);
  const [tracks, setTracks] = useState<TrackOut[] | null>(null);
  const [open, setOpen] = useState<ClipTarget | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setId(new URLSearchParams(window.location.search).get("id"));
  }, []);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const c = await api.camera(id);
      setCam(c);
      setErr(null);
      // the last 24 h of this camera's footage (demo footage is "last night")
      const to = c.coverage_to || new Date().toISOString();
      const from = new Date(new Date(to).getTime() - 24 * 3600 * 1000).toISOString();
      api.timeline(id, from, to).then(setTimeline).catch(() => setTimeline(null));
      api.gaps(id, from, to).then((g) => setGaps(g.gaps)).catch(() => setGaps([]));
      api.recentTracks(id, from, to).then(setTracks).catch(() => setTracks([]));
    } catch (e) {
      setErr((e as Error).message);
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  if (!id) return <Page><Empty title="No camera selected"><Link href="/cameras/" className="text-primary underline">Back to cameras</Link></Empty></Page>;
  if (err) return <Page><ErrorBox message={err} onRetry={load} /></Page>;
  if (!cam) return <Page><Spinner label="Loading camera…" /></Page>;

  const aspect = cam.width && cam.height ? cam.width / cam.height : 16 / 9;
  const toggle = async () => {
    setBusy(true);
    try {
      if (cam.edge_running) await api.stopEdge(cam.id);
      else await api.startEdge(cam.id);
      setTimeout(load, 1500);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Page wide>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h1 className="text-xl font-semibold">{cam.name}</h1>
        <span className={`rounded-full px-2 py-0.5 text-xs ${cam.live ? "bg-danger text-white" : "bg-line text-muted"}`}>{cam.live ? "● LIVE" : "offline"}</span>
        <div className="ml-auto flex gap-2">
          <button onClick={toggle} disabled={busy} className={`inline-flex items-center gap-1 rounded-full px-3 py-1.5 text-sm ${cam.edge_running ? "border border-line" : "bg-primary text-white"}`}>
            {cam.edge_running ? <><Square size={14} /> Stop</> : <><Play size={14} /> {cam.kind === "file" ? "Play as live" : "Start"}</>}
          </button>
          <Link href={`/?camera=${encodeURIComponent(cam.id)}`} className="inline-flex items-center gap-1 rounded-full bg-primary-soft px-3 py-1.5 text-sm text-primary"><MessageCircle size={14} /> Ask</Link>
        </div>
      </div>
      <div className="grid gap-4 lg:grid-cols-[3fr,2fr]">
        <Card>
          <div className="mb-2 text-sm font-medium">Zones <span className="font-normal text-muted">— where Nazar counts entries and watches rules</span></div>
          <ZoneEditor
            key={cam.id}
            imageUrl={cam.live ? mjpegUrl(cam.id) : snapshotUrl(cam.id)}
            aspect={aspect}
            initial={cam.zones}
            onSave={async (z) => { const c = await api.patchCamera(cam.id, { zones: z }); setCam(c); }}
            onSuggest={async () => (await api.suggestZones(cam.id)).zones}
          />
        </Card>
        <div className="space-y-4">
          <Card>
            <div className="flex items-baseline justify-between">
              <div className="text-sm font-medium">People per hour</div>
              <div className="text-xs text-muted">{timeline ? `${timeline.value} in 24 h` : ""}</div>
            </div>
            {timeline ? <div className="mt-2"><MiniBars series={timeline.series} /></div> : <Spinner />}
            <div className="mt-2 text-xs text-muted">
              Footage: {cam.coverage_from ? `${fmtDayTime(cam.coverage_from)} → ${fmtDayTime(cam.coverage_to)}` : "none yet"}
            </div>
            {gaps.length > 0 && (
              <div className="mt-2 text-xs text-muted">
                Offline: {gaps.slice(0, 4).map((g, i) => <span key={i}>{i ? ", " : ""}{fmtTime(g.from)}–{fmtTime(g.to)}</span>)}
                {gaps.length > 4 ? ` +${gaps.length - 4}` : ""}
              </div>
            )}
          </Card>
          <Card>
            <div className="mb-2 text-sm font-medium">Recent tracks</div>
            {!tracks ? <Spinner /> : tracks.length === 0 ? <div className="text-sm text-muted">No tracks yet.</div> : (
              <div className="grid grid-cols-4 gap-2">
                {tracks.slice(0, 16).map((t) => (
                  <button key={t.track_id} onClick={() => setOpen({ track_id: t.track_id, camera_id: cam.id, cls: t.cls, t_start: t.t_start, level: "confirmed", caption: t.caption })}
                    className="overflow-hidden rounded-lg border border-line text-left">
                    {t.thumb_url ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={t.thumb_url} alt="" className="aspect-[3/4] w-full object-cover" />
                    ) : <div className="aspect-[3/4] w-full bg-line" />}
                    <div className="truncate px-1 py-0.5 text-[10px]">{fmtTime(t.t_start)} · {t.cls}</div>
                  </button>
                ))}
              </div>
            )}
          </Card>
        </div>
      </div>
      {open && <ClipPlayer target={open} onClose={() => setOpen(null)} />}
    </Page>
  );
}
