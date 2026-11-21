"use client";

import Link from "next/link";
import { useState } from "react";
import { Play, Plus, Square } from "lucide-react";
import { api, mjpegUrl, snapshotUrl } from "@/lib/api";
import { fmtDayTime } from "@/lib/format";
import type { CameraOut } from "@/lib/types";
import { Empty, ErrorBox, Page, Spinner } from "@/components/ui";
import { useApp } from "@/components/Providers";

export default function CamerasPage() {
  const { cameras, camerasLoading, camerasError, refreshCameras } = useApp();
  return (
    <Page wide>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold">Cameras</h1>
        <Link href="/cameras/new/" className="inline-flex items-center gap-1.5 rounded-full bg-primary px-4 py-2 text-sm font-semibold text-white">
          <Plus size={16} /> Add camera
        </Link>
      </div>
      {camerasError && <ErrorBox message={camerasError} onRetry={refreshCameras} />}
      {camerasLoading && !cameras.length && <Spinner label="Loading cameras…" />}
      {!camerasLoading && !cameras.length && !camerasError && (
        <Empty title="No cameras yet">Add a CCTV/RTSP URL, a phone camera, or upload a video.</Empty>
      )}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {cameras.map((c) => (
          <CameraCard key={c.id} cam={c} onChanged={refreshCameras} />
        ))}
      </div>
    </Page>
  );
}

function CameraCard({ cam, onChanged }: { cam: CameraOut; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const toggle = async () => {
    setBusy(true);
    setErr(null);
    try {
      if (cam.edge_running) await api.stopEdge(cam.id);
      else await api.startEdge(cam.id);
      onChanged();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const status = cam.live
    ? "Live"
    : cam.edge_running
      ? "Starting…"
      : cam.coverage_to
        ? `Offline · last footage ${fmtDayTime(cam.coverage_to)}`
        : "No footage yet";
  return (
    <div className="overflow-hidden rounded-2xl border border-line bg-surface shadow-sm">
      <Link href={`/camera/?id=${encodeURIComponent(cam.id)}`} className="block">
        <div className="relative aspect-video bg-black">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={cam.live ? mjpegUrl(cam.id) : snapshotUrl(cam.id)} alt={cam.name} className="h-full w-full object-cover"
            onError={(e) => ((e.target as HTMLImageElement).style.opacity = "0")} />
          <span className={`absolute left-2 top-2 rounded-full px-2 py-0.5 text-xs font-medium ${cam.live ? "bg-danger text-white" : "bg-black/60 text-white"}`}>
            {cam.live ? "● LIVE" : cam.kind.toUpperCase()}
          </span>
        </div>
      </Link>
      <div className="p-3">
        <div className="flex items-center gap-2">
          <Link href={`/camera/?id=${encodeURIComponent(cam.id)}`} className="truncate font-medium hover:text-primary">{cam.name}</Link>
          <span className="ml-auto shrink-0 text-xs text-muted">{cam.today_count} {cam.today_count === 1 ? "person" : "people"} today</span>
        </div>
        <div className="mt-0.5 truncate text-xs text-muted">{status}</div>
        {cam.coverage_from && (
          <div className="truncate text-xs text-muted">Footage {fmtDayTime(cam.coverage_from)} → {fmtDayTime(cam.coverage_to)}</div>
        )}
        {err && <div className="mt-1 text-xs text-danger">{err}</div>}
        <div className="mt-2 flex gap-2">
          <button onClick={toggle} disabled={busy}
            className={`inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium disabled:opacity-60 ${cam.edge_running ? "border border-line" : "bg-primary text-white"}`}>
            {cam.edge_running ? <><Square size={12} /> Stop</> : <><Play size={12} /> {cam.kind === "file" ? "Play as live" : "Start"}</>}
          </button>
          <Link href={`/?camera=${encodeURIComponent(cam.id)}`} className="rounded-full bg-primary-soft px-3 py-1 text-xs font-medium text-primary">Ask</Link>
        </div>
      </div>
    </div>
  );
}
