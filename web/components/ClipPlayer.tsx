"use client";

import { useEffect, useRef, useState } from "react";
import { Search, X } from "lucide-react";
import { api } from "@/lib/api";
import { clsLabel, fmtDayTime } from "@/lib/format";
import type { ClipOut, Level, TrackOut } from "@/lib/types";
import { ErrorBox, LevelBadge, Spinner } from "./ui";

export interface ClipTarget {
  track_id: number;
  camera_id: string;
  cls?: string;
  t_start?: string;
  level?: Level;
  why?: string;
  caption?: string | null;
}

function nearest(path: number[][], t: number): number[] | null {
  let best: number[] | null = null;
  let bd = Infinity;
  for (const p of path) {
    const d = Math.abs(p[0] - t);
    if (d < bd) {
      bd = d;
      best = p;
    }
  }
  return best && bd <= 600 ? best : null;
}

export function ClipPlayer({ target, onClose }: { target: ClipTarget; onClose: () => void }) {
  const [clip, setClip] = useState<ClipOut | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [similar, setSimilar] = useState<TrackOut[] | null>(null);
  const [simLoading, setSimLoading] = useState(false);
  const [simNote, setSimNote] = useState<string | null>(null);
  const [current, setCurrent] = useState<ClipTarget>(target);
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    let alive = true;
    setClip(null);
    setErr(null);
    api
      .clipForTrack(current.track_id)
      .then((c) => alive && setClip(c))
      .catch((e) => alive && setErr(e.message));
    return () => {
      alive = false;
    };
  }, [current.track_id]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // draw the tracked box over the video, synced to currentTime (no re-encode)
  useEffect(() => {
    if (!clip) return;
    let raf = 0;
    const draw = () => {
      const v = videoRef.current;
      const c = canvasRef.current;
      if (v && c) {
        const rect = v.getBoundingClientRect();
        const dpr = window.devicePixelRatio || 1;
        if (c.width !== Math.round(rect.width * dpr) || c.height !== Math.round(rect.height * dpr)) {
          c.width = Math.round(rect.width * dpr);
          c.height = Math.round(rect.height * dpr);
        }
        const ctx = c.getContext("2d");
        if (ctx) {
          ctx.clearRect(0, 0, c.width, c.height);
          const vw = v.videoWidth || 16;
          const vh = v.videoHeight || 9;
          const scale = Math.min(c.width / vw, c.height / vh);
          const dw = vw * scale;
          const dh = vh * scale;
          const ox = (c.width - dw) / 2;
          const oy = (c.height - dh) / 2;
          const p = nearest(clip.path, clip.t0_ms + v.currentTime * 1000);
          if (p) {
            ctx.strokeStyle = "#D4F53C";
            ctx.lineWidth = 3 * dpr;
            ctx.strokeRect(ox + p[1] * dw, oy + p[2] * dh, (p[3] - p[1]) * dw, (p[4] - p[2]) * dh);
            ctx.fillStyle = "#D4F53C";
            ctx.font = `${12 * dpr}px sans-serif`;
            ctx.fillText(clsLabel[clip.cls || "person"] || "", ox + p[1] * dw, Math.max(12 * dpr, oy + p[2] * dh - 4 * dpr));
          }
        }
      }
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [clip]);

  const findAgain = async () => {
    setSimLoading(true);
    setSimNote(null);
    try {
      const r = await api.similar(current.track_id);
      setSimilar(r.results);
      if (r.note) setSimNote(r.note);
    } catch (e) {
      setSimNote((e as Error).message);
      setSimilar([]);
    } finally {
      setSimLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/70 sm:items-center" onClick={onClose}>
      <div className="max-h-dvh w-full max-w-3xl overflow-y-auto rounded-t-3xl bg-surface p-3 sm:rounded-3xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-2 flex items-center gap-2">
          <div className="min-w-0 flex-1">
            <div className="truncate font-medium">
              {clsLabel[current.cls || "person"] || current.cls} · {current.camera_id}
            </div>
            <div className="text-xs text-muted">{current.t_start ? fmtDayTime(current.t_start) : ""}</div>
          </div>
          {current.level && <LevelBadge level={current.level} />}
          <button onClick={onClose} className="rounded-full p-2 hover:bg-primary-soft" aria-label="Close">
            <X size={18} />
          </button>
        </div>
        <div className="relative w-full overflow-hidden rounded-2xl bg-black" style={{ aspectRatio: "16 / 9" }}>
          {clip ? (
            <>
              <video ref={videoRef} src={clip.url} controls autoPlay muted playsInline className="absolute inset-0 h-full w-full object-contain" />
              <canvas ref={canvasRef} className="pointer-events-none absolute inset-0 h-full w-full" />
            </>
          ) : err ? (
            <div className="absolute inset-0 flex items-center justify-center p-4 text-sm text-white/80">{err}</div>
          ) : (
            <div className="absolute inset-0 flex items-center justify-center text-white/70">
              <Spinner label="Cutting clip…" />
            </div>
          )}
        </div>
        {(current.caption || current.why) && (
          <div className="mt-2 text-sm">
            {current.caption && <div>{current.caption}</div>}
            {current.why && <div className="text-xs text-muted">Why: {current.why}</div>}
          </div>
        )}
        <div className="mt-3 flex items-center gap-2">
          <button
            onClick={findAgain}
            disabled={simLoading}
            className="inline-flex items-center gap-1.5 rounded-full bg-primary px-3 py-1.5 text-sm font-medium text-white disabled:opacity-60"
          >
            <Search size={15} /> Find again
          </button>
          <span className="text-xs text-muted">Same look, ±24 h (appearance fingerprint, no face recognition)</span>
        </div>
        {simLoading && <div className="mt-2"><Spinner label="Searching…" /></div>}
        {simNote && <div className="mt-2"><ErrorBox message={simNote} /></div>}
        {similar && !simLoading && (
          <div className="mt-3">
            {similar.length === 0 ? (
              <div className="text-sm text-muted">No similar-looking tracks found.</div>
            ) : (
              <div className="grid grid-cols-3 gap-2 sm:grid-cols-5">
                {similar.map((s) => (
                  <button
                    key={s.track_id}
                    onClick={() => {
                      setSimilar(null);
                      setCurrent({ track_id: s.track_id, camera_id: s.camera_id, cls: s.cls, t_start: s.t_start, level: s.level, why: s.why, caption: s.caption });
                    }}
                    className={`overflow-hidden rounded-xl text-left ${s.level === "candidate" ? "border border-dashed border-slate-400 opacity-80" : "border border-line"}`}
                  >
                    {s.thumb_url ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={s.thumb_url} alt="" className="aspect-[3/4] w-full object-cover" />
                    ) : (
                      <div className="aspect-[3/4] w-full bg-line" />
                    )}
                    <div className="p-1 text-[10px] leading-tight">
                      <div>{fmtDayTime(s.t_start)}</div>
                      <div className="text-muted">{s.level}</div>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
