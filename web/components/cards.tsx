"use client";

import { useEffect, useRef, useState } from "react";
import { BellRing, Check, Clock, Pause, Play, PlayCircle, ShieldAlert, Zap } from "lucide-react";
import { api } from "@/lib/api";
import { clsLabel, fmtDayTime, fmtTime } from "@/lib/format";
import type { AlertOut, ClipItem, CountResult, Gap, RuleDraft } from "@/lib/types";
import type { ClipTarget } from "./ClipPlayer";
import { LevelBadge, MiniBars, Spinner } from "./ui";
import { useApp } from "./Providers";

export function CountCard({ count }: { count: CountResult }) {
  return (
    <div className="rounded-2xl border border-line bg-surface p-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-4xl font-bold leading-none tracking-tight">{count.value}</div>
          <div className="mt-1 text-sm text-muted">{count.label}</div>
        </div>
        <LevelBadge level="confirmed" />
      </div>
      {count.series.length > 1 && (
        <div className="mt-3">
          <MiniBars series={count.series} />
        </div>
      )}
    </div>
  );
}

export function ClipCard({ clip, onOpen }: { clip: ClipItem; onOpen: (t: ClipTarget) => void }) {
  const quiet = clip.level === "candidate";
  return (
    <button
      onClick={() => onOpen({ track_id: clip.track_id, camera_id: clip.camera_id, cls: clip.cls, t_start: clip.t_start, level: clip.level, why: clip.why, caption: clip.caption })}
      className={`flex w-full gap-3 rounded-2xl p-2 text-left transition hover:shadow-md ${
        quiet ? "border border-dashed border-slate-300 bg-surface/60 opacity-85" : "border border-line bg-surface"
      }`}
    >
      <div className="relative h-20 w-16 shrink-0 overflow-hidden rounded-xl bg-line">
        {clip.thumb_url && (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={clip.thumb_url} alt="" className="h-full w-full object-cover" />
        )}
        <PlayCircle className="absolute bottom-1 right-1 text-white drop-shadow" size={18} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <LevelBadge level={clip.level} />
          <span className="text-xs text-muted">{fmtDayTime(clip.t_start)}</span>
        </div>
        <div className="mt-1 line-clamp-2 text-sm">
          {clip.caption || `${clsLabel[clip.cls] || clip.cls} on ${clip.camera_id}${clip.zones.length ? ` · ${clip.zones.join(", ")}` : ""}`}
        </div>
        {clip.why && <div className="mt-0.5 truncate text-[11px] text-muted">{clip.why}</div>}
      </div>
    </button>
  );
}

const TRIGGER_TEXT: Record<string, string> = {
  zone_enter: "enters",
  zone_exit: "leaves",
  dwell_over: "stays",
  count_over: "crowd",
  object_removed: "object taken",
};

export function RuleCard({ rule, onOpen, onChange }: { rule: RuleDraft; onOpen?: (t: ClipTarget) => void; onChange?: (r: RuleDraft) => void }) {
  const [state, setState] = useState<RuleDraft>(rule);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (!state.ok) {
    return (
      <div className="rounded-2xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950/30 dark:text-amber-100">
        <div className="flex items-center gap-1.5 font-medium"><ShieldAlert size={16} /> Rule needs one more thing</div>
        <div className="mt-1">{state.question}</div>
        {state.camera_id && (
          <a href={`/camera/?id=${encodeURIComponent(state.camera_id)}`} className="mt-2 inline-block font-medium text-primary underline">
            Draw the zone →
          </a>
        )}
      </div>
    );
  }
  const spec = state.spec;
  const toggle = async () => {
    if (!state.rule_id) return;
    setBusy(true);
    setErr(null);
    try {
      const r = state.active ? await api.deactivateRule(state.rule_id) : await api.activateRule(state.rule_id);
      setState({ ...state, ...r });
      onChange?.({ ...state, ...r });
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="rounded-2xl border border-line bg-surface p-3">
      <div className="flex items-start gap-2">
        <BellRing size={18} className="mt-0.5 shrink-0 text-primary" />
        <div className="flex-1 text-sm font-medium">{state.human}</div>
      </div>
      {spec && (
        <div className="mt-2 flex flex-wrap gap-1.5 text-xs">
          <span className="rounded-full bg-primary-soft px-2 py-0.5 text-primary">{TRIGGER_TEXT[spec.trigger] || spec.trigger}</span>
          <span className="rounded-full bg-primary-soft px-2 py-0.5 text-primary">{clsLabel[spec.cls] || spec.cls}</span>
          <span className="rounded-full bg-primary-soft px-2 py-0.5 text-primary">{spec.zone.replace(/_/g, " ")}</span>
          {spec.dwell_s ? <span className="rounded-full bg-primary-soft px-2 py-0.5 text-primary">{spec.dwell_s}s+</span> : null}
          {spec.count ? <span className="rounded-full bg-primary-soft px-2 py-0.5 text-primary">&gt;{spec.count}</span> : null}
          {spec.time_window && (
            <span className="inline-flex items-center gap-1 rounded-full bg-primary-soft px-2 py-0.5 text-primary">
              <Clock size={11} /> {spec.time_window.from}–{spec.time_window.to}
            </span>
          )}
          {spec.confirm_with_vision && <span className="rounded-full bg-primary-soft px-2 py-0.5 text-primary">AI check</span>}
        </div>
      )}
      {state.replay && typeof state.replay.count === "number" && (
        <div className="mt-3 rounded-xl bg-background p-2">
          <div className="text-sm">
            <span className="font-semibold">Would have fired {state.replay.count} time{state.replay.count === 1 ? "" : "s"}</span>{" "}
            <span className="text-muted">
              ({fmtDayTime(state.replay.window_from)} → {fmtTime(state.replay.window_to)})
            </span>
          </div>
          {!!state.hit_thumbs?.length && (
            <div className="mt-2 flex gap-2 overflow-x-auto scroll-thin">
              {state.hit_thumbs.map((h) => (
                <button
                  key={`${h.track_id}-${h.t}`}
                  onClick={() => onOpen?.({ track_id: h.track_id, camera_id: spec?.camera_id || "", t_start: h.t, level: "confirmed", why: "rule replay hit" })}
                  className="w-16 shrink-0 overflow-hidden rounded-lg border border-line text-left"
                >
                  {h.thumb_url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={h.thumb_url} alt="" className="h-20 w-16 object-cover" />
                  ) : (
                    <div className="h-20 w-16 bg-line" />
                  )}
                  <div className="px-1 py-0.5 text-[10px]">{fmtTime(h.t)}</div>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
      {err && <div className="mt-2 text-xs text-danger">{err}</div>}
      <div className="mt-3 flex items-center gap-2">
        <button
          onClick={toggle}
          disabled={busy || !state.rule_id}
          className={`inline-flex items-center gap-1.5 rounded-full px-4 py-1.5 text-sm font-semibold disabled:opacity-60 ${
            state.active ? "border border-line text-foreground" : "bg-primary text-on-primary"
          }`}
        >
          {state.active ? <><Pause size={14} /> Pause</> : <><Zap size={14} /> Activate</>}
        </button>
        {state.active && <span className="inline-flex items-center gap-1 text-xs text-emerald-600"><Check size={14} /> Watching live</span>}
      </div>
    </div>
  );
}

export function GapNote({ gaps }: { gaps: Gap[] }) {
  if (!gaps.length) return null;
  const shown = gaps.slice(0, 3);
  return (
    <div className="rounded-xl bg-background px-3 py-2 text-xs text-muted">
      Camera offline (no footage):{" "}
      {shown.map((g, i) => (
        <span key={i}>
          {i ? ", " : ""}
          {fmtTime(g.from)}–{fmtTime(g.to)}
        </span>
      ))}
      {gaps.length > 3 ? ` +${gaps.length - 3} more` : ""}
    </div>
  );
}

export function AudioReply({ url, autoPlay }: { url: string; autoPlay: boolean }) {
  const { play, soundOn } = useApp();
  const [blocked, setBlocked] = useState(false);
  const [playing, setPlaying] = useState(false);
  const ref = useRef<HTMLAudioElement>(null);
  const tried = useRef(false);
  useEffect(() => {
    if (!autoPlay || tried.current || !soundOn) return;
    tried.current = true;
    play(url).then((ok) => setBlocked(!ok));
  }, [autoPlay, url, play, soundOn]);
  return (
    <div className="flex items-center gap-2">
      <button
        onClick={() => {
          const a = ref.current;
          if (!a) return;
          if (a.paused) {
            a.play().then(() => setBlocked(false)).catch(() => setBlocked(true));
          } else a.pause();
        }}
        className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ${blocked ? "bg-lime text-slate-900" : "bg-primary-soft text-primary"}`}
      >
        {playing ? <Pause size={13} /> : <Play size={13} />} {blocked ? "Tap to play voice reply" : "Voice reply"}
      </button>
      <audio ref={ref} src={url} preload="none" onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)} />
    </div>
  );
}

export function AlertBubble({ alert, onOpen, autoPlay }: { alert: AlertOut; onOpen: (t: ClipTarget) => void; autoPlay: boolean }) {
  const [ack, setAck] = useState(alert.ack);
  const [busy, setBusy] = useState(false);
  return (
    <div className="rounded-2xl border-2 border-danger bg-surface p-3 shadow-sm">
      <div className="flex items-center gap-2 text-sm font-semibold text-danger">
        <BellRing size={16} /> Alert · {alert.camera_name || alert.camera_id}
        <span className="ml-auto text-xs font-normal text-muted">{fmtDayTime(alert.t)}</span>
      </div>
      <div className="mt-1 text-sm">{alert.message}</div>
      {alert.human && <div className="text-xs text-muted">Rule: {alert.human}</div>}
      {alert.suppressed && <div className="mt-1 text-xs text-amber-700">Suppressed by the AI check — not notified.</div>}
      {alert.snapshot_url && (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={alert.snapshot_url} alt="alert snapshot" className="mt-2 max-h-56 w-full rounded-xl object-contain bg-black" />
      )}
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {alert.audio_url ? <AudioReply url={alert.audio_url} autoPlay={autoPlay} /> : <span className="text-xs text-muted">Voice note pending…</span>}
        <button
          onClick={() => onOpen({ track_id: alert.track_id, camera_id: alert.camera_id, t_start: alert.t, level: "confirmed", why: "rule hit" })}
          className="rounded-full bg-primary px-3 py-1 text-xs font-medium text-on-primary"
        >
          Open clip
        </button>
        <button
          disabled={ack || busy}
          onClick={async () => {
            setBusy(true);
            try {
              await api.ackAlert(alert.id);
              setAck(true);
            } finally {
              setBusy(false);
            }
          }}
          className="rounded-full border border-line px-3 py-1 text-xs disabled:opacity-60"
        >
          {busy ? <Spinner /> : ack ? "Acknowledged" : "Acknowledge"}
        </button>
      </div>
    </div>
  );
}
