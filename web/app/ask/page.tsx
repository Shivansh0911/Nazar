"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Camera, Layers, Mic, Trash2, X } from "lucide-react";
import { askStream } from "@/lib/api2";
import { fmtDuration } from "@/lib/format";
import type { AlertOut } from "@/lib/types";
import type { AskV2, Hit } from "@/lib/types2";
import { Composer } from "@/components/Composer";
import { ClipPlayer, type ClipTarget } from "@/components/ClipPlayer";
import { AlertBubble, AudioReply } from "@/components/cards";
import { EvidencePanel, hasEvidence } from "@/components/EvidencePanel";
import { HitCard } from "@/components/evidence";
import { PhotoSearchSheet } from "@/components/PhotoSearch";
import { ErrorBox, LevelBadge, Shell, Spinner } from "@/components/ui";
import { useApp } from "@/components/Providers";

type Msg =
  | { id: string; role: "user"; text?: string; voiceSeconds?: number; transcript?: string | null; photo?: string }
  | { id: string; role: "nazar"; resp?: AskV2; pending?: boolean; status?: string; partial?: string; error?: string; autoPlay?: boolean }
  | { id: string; role: "photo"; hits: Hit[]; text: string }
  | { id: string; role: "alert"; alert: AlertOut; autoPlay?: boolean };

const SUGGESTIONS = [
  "Kal raat 10 baje ke baad shop counter pe kitne log aaye?",
  "Which camera was busiest, and at what time?",
  "Builders venue pe kitne log dikhe?",
  "Show me a green backpack",
  "Desk 14 se bag kisne uthaya?",
  "Jab bhi koi desk 14 se bag uthaye, mujhe batana",
  "रात 2 बजे के बाद night stall पर कितने लोग आए?",
  "Lobby mein log kahan sabse zyada ruke? Heatmap dikhao",
];
const STORE = "nazar_chat_v2";
const uid = () => Math.random().toString(36).slice(2);

export default function AskPage() {
  const { cameras, onAlert } = useApp();
  const [camera, setCamera] = useState<string>("");
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<ClipTarget | null>(null);
  const [focus, setFocus] = useState<string | null>(null);
  const [sheet, setSheet] = useState(false);
  const [photo, setPhoto] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);
  const loaded = useRef(false);

  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(STORE) || "[]") as Msg[];
      setMsgs(saved.filter((m) => !(m.role === "nazar" && (m.pending || !m.resp))).map((m) => ({ ...m, autoPlay: false }) as Msg));
    } catch {
      /* ignore */
    }
    const p = new URLSearchParams(window.location.search);
    if (p.get("camera")) setCamera(p.get("camera") || "");
    loaded.current = true;
    const q0 = p.get("q");
    if (q0) setTimeout(() => askText(q0), 50);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!loaded.current) return;
    try {
      localStorage.setItem(STORE, JSON.stringify(msgs.filter((m) => !(m.role === "nazar" && m.pending)).slice(-30)));
    } catch {
      /* ignore */
    }
  }, [msgs]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [msgs]);

  useEffect(
    () =>
      onAlert((a, update) => {
        if (a.suppressed) return;
        setMsgs((prev) => {
          const i = prev.findIndex((m) => m.role === "alert" && m.alert.id === a.id);
          if (i >= 0) {
            const copy = [...prev];
            copy[i] = { id: prev[i].id, role: "alert", alert: a, autoPlay: update && !!a.audio_url };
            return copy;
          }
          return [...prev, { id: uid(), role: "alert", alert: a, autoPlay: !!a.audio_url }];
        });
      }),
    [onAlert],
  );

  const run = useCallback(async (input: { text?: string; audio?: { blob: Blob; filename: string } }, userId: string) => {
    const nid = uid();
    setMsgs((m) => [...m, { id: nid, role: "nazar", pending: true, status: "Thinking…", partial: "" }]);
    setBusy(true);
    const patch = (fn: (x: Extract<Msg, { role: "nazar" }>) => Extract<Msg, { role: "nazar" }>) =>
      setMsgs((m) => m.map((x) => (x.id === nid && x.role === "nazar" ? fn(x) : x)));
    try {
      const resp = await askStream(input, camera || null, {
        status: (s) => patch((x) => ({ ...x, status: s })),
        text: (d) => patch((x) => ({ ...x, partial: (x.partial || "") + d })),
        reset: () => patch((x) => ({ ...x, partial: "" })),
        transcript: (t) => setMsgs((m) => m.map((x) => (x.id === userId && x.role === "user" ? { ...x, transcript: t } : x))),
      });
      setMsgs((m) => m.map((x) => (x.id === nid ? { id: nid, role: "nazar", resp, autoPlay: true } : x)));
      if (hasEvidence(resp)) setFocus(nid);
    } catch (e) {
      setMsgs((m) => m.map((x) => (x.id === nid ? { id: nid, role: "nazar", error: (e as Error).message } : x)));
    } finally {
      setBusy(false);
    }
  }, [camera]);

  const askText = (text: string) => {
    const id = uid();
    setMsgs((m) => [...m, { id, role: "user", text }]);
    run({ text }, id);
  };
  const askVoice = (blob: Blob, filename: string, seconds: number) => {
    const id = uid();
    setMsgs((m) => [...m, { id, role: "user", voiceSeconds: seconds }]);
    run({ audio: { blob, filename } }, id);
  };

  const focused = msgs.find((m) => m.id === focus && m.role === "nazar") as Extract<Msg, { role: "nazar" }> | undefined;
  const lastWithEvidence = [...msgs].reverse().find((m) => m.role === "nazar" && m.resp && hasEvidence(m.resp)) as Extract<Msg, { role: "nazar" }> | undefined;
  const panelMsg = focused?.resp ? focused : lastWithEvidence;

  const camSelect = (
    <select value={camera} onChange={(e) => setCamera(e.target.value)} aria-label="Camera"
      className="max-w-[11rem] rounded-full border border-line bg-surface-2 px-3 py-1.5 text-sm">
      <option value="">All cameras</option>
      {cameras.map((c) => <option key={c.id} value={c.id}>{c.live ? "● " : ""}{c.name}</option>)}
    </select>
  );

  return (
    <Shell title="Ask" actions={camSelect} bare>
      <div className="flex min-h-0 flex-1">
        {/* chat */}
        <section className="flex min-w-0 flex-1 flex-col">
          <div className="hidden items-center gap-3 border-b border-line px-6 py-3 md:flex">
            <div className="text-lg font-semibold">Ask your cameras</div>
            <div className="ml-auto flex items-center gap-2">{camSelect}
              {msgs.length > 0 && <button onClick={() => { setMsgs([]); setFocus(null); }} className="inline-flex items-center gap-1 rounded-full px-2 py-1 text-xs text-muted hover:text-danger"><Trash2 size={13} /> Clear</button>}
            </div>
          </div>
          <div className="flex-1 overflow-y-auto px-3 pb-40 pt-4 md:px-6 md:pb-6 scroll-thin">
            <div className="mx-auto max-w-2xl space-y-3">
              {msgs.length === 0 && (
                <div className="mt-6 text-center md:mt-12">
                  <div className="font-display text-4xl md:text-5xl">Ask your CCTV anything</div>
                  <div className="mt-2 text-sm text-muted">Hindi, English or Hinglish — type, tap the lime mic, or search by photo.</div>
                  <div className="mt-6 flex flex-wrap justify-center gap-2">
                    {SUGGESTIONS.map((s) => (
                      <button key={s} onClick={() => askText(s)} disabled={busy}
                        className="rounded-full border border-line bg-surface px-3 py-2 text-sm hover:border-primary hover:text-primary">{s}</button>
                    ))}
                  </div>
                </div>
              )}
              <AnimatePresence initial={false}>
                {msgs.map((m) => (
                  <motion.div key={m.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.18 }}>
                    {m.role === "user" && (
                      <div className="flex justify-end">
                        <div className="max-w-[85%] rounded-3xl rounded-br-lg bg-primary px-4 py-2.5 text-on-primary">
                          {m.voiceSeconds !== undefined ? (
                            <div>
                              <div className="flex items-center gap-1.5 text-sm"><Mic size={14} /> voice note {fmtDuration(m.voiceSeconds)}</div>
                              {m.transcript && <div className="mt-1 text-[13px] text-white/85">“{m.transcript}”</div>}
                            </div>
                          ) : m.photo ? (
                            <div className="flex items-center gap-2 text-sm">
                              {/* eslint-disable-next-line @next/next/no-img-element */}
                              <img src={m.photo} alt="" className="h-12 w-12 rounded-lg object-cover" /> {m.text || "Find this"}
                            </div>
                          ) : <div className="text-[15px]">{m.text}</div>}
                        </div>
                      </div>
                    )}
                    {m.role === "alert" && <div className="max-w-[94%]"><AlertBubble alert={m.alert} onOpen={setOpen} autoPlay={!!m.autoPlay} /></div>}
                    {m.role === "photo" && (
                      <div className="space-y-2 rounded-3xl rounded-bl-lg border border-line bg-surface p-3">
                        <div className="text-sm">{m.hits.length ? `${m.hits.length} similar moments across your cameras (local visual index).` : "Nothing similar found."}
                          {" "}<span className="text-muted">Probable only when AI also verified it.</span></div>
                        {m.hits.slice(0, 8).map((h) => <HitCard key={`${h.kind}-${h.id}`} hit={h} onOpen={setOpen} />)}
                      </div>
                    )}
                    {m.role === "nazar" && (
                      <div className={`rounded-3xl rounded-bl-lg border bg-surface p-3.5 ${focus === m.id ? "border-primary/60" : "border-line"}`}>
                        {m.pending && (
                          <div>
                            {m.partial ? <div className="text-[15px] leading-relaxed">{m.partial}<span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-primary align-middle" /></div> : null}
                            <div className="mt-1"><Spinner label={m.status || "Thinking…"} /></div>
                          </div>
                        )}
                        {m.error && <ErrorBox message={m.error} />}
                        {m.resp && (
                          <div className="space-y-2">
                            <div className="text-[15px] leading-relaxed">{m.resp.reply_text}</div>
                            {m.resp.clarify && (
                              <div className="flex flex-wrap gap-1.5">
                                {m.resp.clarify.options.map((o) => <button key={o} onClick={() => askText(o)} disabled={busy}
                                  className="rounded-full border border-primary/50 px-3 py-1 text-xs text-primary hover:bg-primary hover:text-on-primary">{o}</button>)}
                              </div>
                            )}
                            {m.resp.audio_url && <AudioReply url={m.resp.audio_url} autoPlay={!!m.autoPlay} />}
                            {hasEvidence(m.resp) > 0 && (
                              <div className="flex flex-wrap items-center gap-2">
                                {m.resp.count && <span className="font-display text-2xl">{m.resp.count.value}</span>}
                                {m.resp.count && <LevelBadge level="confirmed" />}
                                <button onClick={() => { setFocus(m.id); setSheet(true); }}
                                  className="inline-flex items-center gap-1.5 rounded-full bg-primary-soft px-3 py-1 text-xs font-medium text-primary">
                                  <Layers size={13} /> {m.resp.count ? `${m.resp.count.receipts_total ?? m.resp.count.value} receipts` : `${hasEvidence(m.resp)} evidence item${hasEvidence(m.resp) === 1 ? "" : "s"}`}
                                </button>
                              </div>
                            )}
                            {m.resp.followups.length > 0 && (
                              <div className="flex flex-wrap gap-1.5 pt-1">
                                {m.resp.followups.map((f) => <button key={f} disabled={busy} onClick={() => askText(f)}
                                  className="rounded-full bg-surface-2 px-3 py-1 text-xs text-foreground hover:bg-primary hover:text-on-primary">{f}</button>)}
                              </div>
                            )}
                            <div className="text-[10px] text-muted">
                              {(m.resp.latency_ms / 1000).toFixed(1)} s{m.resp.first_text_ms ? ` (first words ${(m.resp.first_text_ms / 1000).toFixed(1)} s)` : ""} · ₹{(m.resp.cost_inr ?? 0).toFixed(2)}{m.resp.model ? ` · ${m.resp.model}` : ""}{m.resp.cached ? " · cached" : ""}
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </motion.div>
                ))}
              </AnimatePresence>
              <div ref={bottom} />
            </div>
          </div>
          <div className="fixed inset-x-0 bottom-[calc(3.6rem+env(safe-area-inset-bottom))] z-30 md:sticky md:bottom-0">
            <div className="mx-auto max-w-2xl"><Composer onText={askText} onVoice={askVoice} busy={busy} onPhoto={() => setPhoto(true)} /></div>
          </div>
        </section>
        {/* evidence panel (desktop) */}
        <aside className="hidden w-[30rem] shrink-0 overflow-y-auto border-l border-line bg-surface/40 p-5 xl:block scroll-thin" style={{ maxHeight: "100dvh" }}>
          <div className="mb-3 flex items-center gap-2 text-sm font-semibold"><Layers size={16} className="text-primary" /> Evidence</div>
          {panelMsg?.resp ? <EvidencePanel resp={panelMsg.resp} onOpen={setOpen} /> : (
            <div className="rounded-3xl border border-dashed border-line p-6 text-center text-sm text-muted">
              Counts, receipts, clips and charts for your answer show up here. Every number links to the people it counted.
            </div>
          )}
        </aside>
      </div>
      {/* evidence bottom sheet (phones/tablets) */}
      {sheet && panelMsg?.resp && (
        <div className="fixed inset-0 z-50 bg-black/60 xl:hidden" onClick={() => setSheet(false)}>
          <motion.div initial={{ y: 60, opacity: 0 }} animate={{ y: 0, opacity: 1 }}
            className="absolute inset-x-0 bottom-0 max-h-[88dvh] overflow-y-auto rounded-t-3xl border-t border-line bg-background p-4 pb-[max(1rem,env(safe-area-inset-bottom))]"
            onClick={(e) => e.stopPropagation()}>
            <div className="mx-auto mb-3 h-1.5 w-10 rounded-full bg-line" />
            <div className="mb-2 flex items-center gap-2 font-semibold"><Layers size={16} className="text-primary" /> Evidence
              <button onClick={() => setSheet(false)} className="ml-auto rounded-full p-1.5 hover:bg-surface-2" aria-label="Close"><X size={18} /></button></div>
            <EvidencePanel resp={panelMsg.resp} onOpen={setOpen} />
          </motion.div>
        </div>
      )}
      {photo && (
        <PhotoSearchSheet cameraId={camera || null} onClose={() => setPhoto(false)}
          onResult={({ hits, preview, text }) => setMsgs((m) => [...m, { id: uid(), role: "user", photo: preview, text: text || "Find this" }, { id: uid(), role: "photo", hits, text }])} />
      )}
      {open && <ClipPlayer target={open} onClose={() => setOpen(null)} />}
      <span className="hidden"><Camera /></span>
    </Shell>
  );
}
