"use client";

import { useEffect, useState } from "react";
import { Film, Images, MapPin, PlayCircle, ShieldCheck, X } from "lucide-react";
import { api2 } from "@/lib/api2";
import { clsLabel, fmtDayTime, fmtTime } from "@/lib/format";
import type { ClipV2, CountV2, Hit, Journey, Receipt } from "@/lib/types2";
import type { ClipTarget } from "./ClipPlayer";
import { ActivityChart } from "./charts";
import { Btn, LevelBadge, Spinner } from "./ui";
import { useApp } from "./Providers";

export function VideoModal({ title, url, poster, onClose, sub }: { title: string; url: string | null; poster?: string | null; onClose: () => void; sub?: string }) {
  const [err, setErr] = useState(false);
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/75 sm:items-center" onClick={onClose}>
      <div className="w-full max-w-3xl rounded-t-3xl border border-line bg-surface p-3 sm:rounded-3xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-2 flex items-center gap-2">
          <div className="min-w-0 flex-1"><div className="truncate font-medium">{title}</div>{sub && <div className="text-xs text-muted">{sub}</div>}</div>
          <button onClick={onClose} className="rounded-full p-2 hover:bg-surface-2" aria-label="Close"><X size={18} /></button>
        </div>
        <div className="relative aspect-video w-full overflow-hidden rounded-2xl bg-black">
          {!url ? (
            <div className="absolute inset-0 flex items-center justify-center text-white/70"><Spinner label="Cutting the clip (faces blurred)…" /></div>
          ) : err ? (
            <div className="absolute inset-0 flex items-center justify-center p-4 text-center text-sm text-white/80">This clip could not be played. The footage for that time may not be stored any more.</div>
          ) : (
            <video src={url} poster={poster || undefined} controls autoPlay muted playsInline onError={() => setErr(true)} className="absolute inset-0 h-full w-full object-contain" />
          )}
        </div>
      </div>
    </div>
  );
}

/** A count with its receipts: every counted track is listed, playable and can be marked wrong by a human. */
export function CountCardV2({ count, queryId, onOpen }: { count: CountV2; queryId?: number; onOpen: (t: ClipTarget) => void }) {
  const { toast } = useApp();
  const [hour, setHour] = useState<string | null>(null);
  const [items, setItems] = useState<Receipt[]>(count.receipts || []);
  const [total, setTotal] = useState(count.receipts_total ?? count.value);
  const [page, setPage] = useState(0);
  const [wrong, setWrong] = useState<Set<number>>(new Set());
  const [verify, setVerify] = useState(false);
  const [loading, setLoading] = useState(false);
  const [reel, setReel] = useState<{ url: string | null; poster?: string | null } | null>(null);

  useEffect(() => {
    if (!queryId || (hour === null && page === 0)) {
      setItems(count.receipts || []);
      setTotal(count.receipts_total ?? count.value);
      return;
    }
    setLoading(true);
    api2.receipts(queryId, page, hour || undefined).then((r) => {
      setItems((prev) => (page > 0 ? [...prev, ...r.items] : r.items));
      setTotal(r.total);
      setWrong((w) => {
        const n = new Set(w);
        r.items.filter((i) => i.marked_wrong).forEach((i) => n.add(i.track_id));
        return n;
      });
    }).catch((e) => toast(e.message, "err")).finally(() => setLoading(false));
  }, [hour, page, queryId, count, toast]);

  const mark = async (r: Receipt) => {
    const isWrong = !wrong.has(r.track_id);
    const next = new Set(wrong);
    if (isWrong) next.add(r.track_id);
    else next.delete(r.track_id);
    setWrong(next);
    try {
      await api2.feedback("receipt", String(r.track_id), !isWrong);
    } catch (e) {
      toast((e as Error).message, "err");
    }
  };

  const playReel = async () => {
    const ids = hour ? items.map((i) => i.track_id) : (count.receipt_ids || items.map((i) => i.track_id));
    setReel({ url: null });
    try {
      const r = await api2.reel(ids.slice(0, 24), hour ? total : count.value);
      setReel({ url: r.url, poster: r.poster_url });
    } catch (e) {
      setReel(null);
      toast((e as Error).message, "err");
    }
  };

  return (
    <div className="rounded-3xl border border-line bg-surface p-4">
      <div className="flex flex-wrap items-start gap-3">
        <div>
          <div className="font-display text-6xl leading-none">{count.value}</div>
          <div className="mt-1 text-sm text-muted">{count.label}</div>
          {wrong.size > 0 && (
            <div className="mt-1 text-xs"><b>{count.value}</b> by AI · <b>{count.value - wrong.size}</b> after your review</div>
          )}
        </div>
        <div className="ml-auto flex flex-col items-end gap-2">
          <LevelBadge level="confirmed" />
          <span className="text-[11px] text-muted">counted from tracker records (SQL)</span>
        </div>
      </div>
      {count.series.length > 1 && (
        <div className="mt-3">
          <ActivityChart series={count.series} bucket={count.bucket} selected={hour} onSelect={(t) => { setPage(0); setHour(t); }} />
          <div className="text-[11px] text-muted">{hour ? `Showing who was counted at ${fmtTime(hour)} — tap the bar again to clear` : "Tap a bar to see who was counted then"}</div>
        </div>
      )}
      {count.value > 0 && (
        <div className="mt-3">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <div className="text-sm font-medium">Receipts <span className="font-normal text-muted">· {total} counted</span></div>
            <label className="ml-auto inline-flex cursor-pointer items-center gap-1.5 text-xs text-muted">
              <input type="checkbox" checked={verify} onChange={(e) => setVerify(e.target.checked)} className="accent-[var(--primary)]" /> Verify
            </label>
            <Btn kind="soft" onClick={playReel} className="!px-3 !py-1.5 text-xs"><Film size={14} /> Play proof reel</Btn>
          </div>
          <div className="grid grid-cols-4 gap-2 sm:grid-cols-6">
            {items.map((r, i) => (
              <div key={`${r.track_id}-${i}`} className={`relative overflow-hidden rounded-xl border ${wrong.has(r.track_id) ? "border-danger opacity-60" : "border-line"}`}>
                <button onClick={() => onOpen({ track_id: r.track_id, camera_id: r.camera_id, t_start: r.t, level: "confirmed", why: "counted by the tracker" })}
                  className="block w-full text-left" aria-label={`Play receipt ${i + 1}`}>
                  {r.thumb_url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={r.thumb_url} alt="" loading="lazy" className="aspect-[3/4] w-full object-cover" />
                  ) : <div className="aspect-[3/4] w-full bg-line" />}
                  <div className="px-1 py-0.5 text-[10px] tabular-nums">{i + 1} · {fmtTime(r.t)}</div>
                </button>
                {verify && (
                  <button onClick={() => mark(r)} className={`absolute right-1 top-1 rounded-full px-1.5 py-0.5 text-[10px] font-semibold ${wrong.has(r.track_id) ? "bg-danger text-white" : "bg-black/60 text-white"}`}>
                    {wrong.has(r.track_id) ? "wrong" : "ok?"}
                  </button>
                )}
              </div>
            ))}
          </div>
          {loading && <div className="mt-2"><Spinner /></div>}
          {!loading && items.length < total && (queryId ? (
            <button onClick={() => setPage(page + 1)} className="mt-2 text-xs font-medium text-primary">Show more receipts ({total - items.length} left)</button>
          ) : <div className="mt-2 text-xs text-muted">+{total - items.length} more</div>)}
        </div>
      )}
      {reel && <VideoModal title="Proof reel" sub="Every counted moment, 2.5 s each · faces blurred" url={reel.url} poster={reel.poster} onClose={() => setReel(null)} />}
    </div>
  );
}

export function HitCard({ hit, onOpen, onKeyframe }: { hit: ClipV2 | Hit; onOpen: (t: ClipTarget) => void; onKeyframe?: (h: { camera_id: string; t: string }) => void }) {
  const quiet = hit.level === "candidate";
  const isKf = (hit as Hit).kind === "keyframe" || (hit as ClipV2).kind === "keyframe";
  const t = (hit as Hit).t || hit.t_start;
  return (
    <button
      onClick={() => (isKf ? onKeyframe?.({ camera_id: hit.camera_id, t }) : hit.track_id && onOpen({ track_id: hit.track_id, camera_id: hit.camera_id, cls: hit.cls, t_start: hit.t_start, level: hit.level, why: hit.why, caption: hit.caption }))}
      className={`group flex w-full gap-3 rounded-2xl p-2 text-left transition hover:bg-surface-2 ${quiet ? "border border-dashed border-muted/50" : "border border-line bg-surface"}`}
    >
      <div className={`relative shrink-0 overflow-hidden rounded-xl bg-line ${isKf ? "h-20 w-32" : "h-24 w-[4.5rem]"}`}>
        {hit.thumb_url && (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={hit.thumb_url} alt="" loading="lazy" className="h-full w-full object-cover" />
        )}
        <PlayCircle className="absolute bottom-1 right-1 text-white drop-shadow" size={18} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <LevelBadge level={hit.level} verified={(hit as Hit).verified === "yes"} />
          <span className="text-xs text-muted">{fmtDayTime(t)}</span>
        </div>
        <div className="mt-1 line-clamp-2 text-sm">
          {hit.caption || (isKf ? `Scene on ${hit.camera_id}` : `${clsLabel[hit.cls] || hit.cls} on ${hit.camera_id}`)}
        </div>
        {hit.why && <div className="mt-0.5 line-clamp-2 text-[11px] text-muted">{hit.why}</div>}
      </div>
    </button>
  );
}

export function JourneyView({ journey, onOpen }: { journey: Journey; onOpen: (t: ClipTarget) => void }) {
  const steps = journey.steps;
  if (!steps.length) return <div className="text-sm text-muted">{journey.note || "No other sightings."}</div>;
  return (
    <div className="rounded-2xl border border-line bg-surface-2 p-3">
      <div className="mb-2 flex items-center gap-2 text-sm font-medium"><MapPin size={15} className="text-primary" /> Journey {journey.summary && <span className="font-normal text-muted">· {journey.summary}</span>}</div>
      <ol className="relative ml-2 border-l border-line pl-4">
        {steps.map((s) => (
          <li key={s.track_id} className="relative mb-3 last:mb-0">
            <span className={`absolute -left-[21px] top-5 h-2.5 w-2.5 rounded-full ${s.anchor ? "bg-lime" : "bg-primary"}`} />
            <button onClick={() => onOpen({ track_id: s.track_id, camera_id: s.camera_id, cls: s.cls, t_start: s.t_start, level: s.level, why: s.why })}
              aria-label={`Play journey step at ${s.camera_id}`}
              className="flex w-full items-center gap-3 rounded-xl p-1 text-left hover:bg-surface">
              {s.thumb_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={s.thumb_url} alt="" className="h-14 w-11 rounded-lg object-cover" />
              ) : <div className="h-14 w-11 rounded-lg bg-line" />}
              <div className="min-w-0">
                <div className="text-sm font-medium">{s.camera_name || s.camera_id} · {fmtTime(s.t_start)}</div>
                <div className="flex items-center gap-1.5"><LevelBadge level={s.level} /><span className="truncate text-[11px] text-muted">{s.why}</span></div>
              </div>
            </button>
          </li>
        ))}
      </ol>
      <div className="mt-2 flex items-center gap-1 text-[11px] text-muted"><ShieldCheck size={12} /> Appearance only (clothes, colours, shape) — no face recognition.</div>
    </div>
  );
}

export function NoteCard({ text, ai }: { text: string; ai: boolean }) {
  return (
    <div className="rounded-2xl border border-dashed border-line bg-surface-2 p-3 text-sm">
      {text}
      {ai && <div className="mt-1 flex items-center gap-1 text-[11px] text-muted"><Images size={12} /> AI-generated description from blurred frames — check the clip</div>}
    </div>
  );
}
