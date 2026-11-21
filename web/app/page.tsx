"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Mic, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { fmtDuration } from "@/lib/format";
import type { AlertOut, AskResponse } from "@/lib/types";
import { Composer } from "@/components/Composer";
import { ClipPlayer, type ClipTarget } from "@/components/ClipPlayer";
import { AlertBubble, AudioReply, ClipCard, CountCard, GapNote, RuleCard } from "@/components/cards";
import { ErrorBox, Spinner, TopBar } from "@/components/ui";
import { useApp } from "@/components/Providers";

type Msg =
  | { id: string; role: "user"; text?: string; voiceSeconds?: number; transcript?: string | null }
  | { id: string; role: "nazar"; resp?: AskResponse; pending?: boolean; error?: string; autoPlay?: boolean }
  | { id: string; role: "alert"; alert: AlertOut; autoPlay?: boolean };

const SUGGESTIONS = [
  "Aaj kitne log aaye?",
  "Kal raat 10 baje ke baad shop counter pe kitne log aaye?",
  "Show people carrying a bag",
  "Desk 14 se bag kisne uthaya?",
  "Jab bhi koi desk 14 se bag uthaye, mujhe batana",
  "रात 2 बजे के बाद night stall पर कितने लोग आए?",
];
const STORE = "nazar_chat_v1";
const uid = () => Math.random().toString(36).slice(2);

export default function ChatPage() {
  const { cameras, onAlert } = useApp();
  const [camera, setCamera] = useState<string>("");
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<ClipTarget | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const loaded = useRef(false);

  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(STORE) || "[]") as Msg[];
      setMsgs(saved.filter((m) => !(m.role === "nazar" && m.pending)).map((m) => ({ ...m, autoPlay: false }) as Msg));
    } catch {
      /* ignore */
    }
    const p = new URLSearchParams(window.location.search).get("camera");
    if (p) setCamera(p);
    loaded.current = true;
  }, []);

  useEffect(() => {
    if (!loaded.current) return;
    try {
      localStorage.setItem(STORE, JSON.stringify(msgs.filter((m) => !(m.role === "nazar" && m.pending)).slice(-40)));
    } catch {
      /* ignore */
    }
  }, [msgs]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [msgs]);

  // live alerts arrive as red bubbles
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

  const runAsk = useCallback(
    async (p: Promise<AskResponse>, userId: string) => {
      const nid = uid();
      setMsgs((m) => [...m, { id: nid, role: "nazar", pending: true }]);
      setBusy(true);
      try {
        const resp = await p;
        setMsgs((m) =>
          m.map((x) => {
            if (x.id === nid) return { id: nid, role: "nazar", resp, autoPlay: true };
            if (x.id === userId && x.role === "user" && resp.transcript) return { ...x, transcript: resp.transcript };
            return x;
          }),
        );
      } catch (e) {
        setMsgs((m) => m.map((x) => (x.id === nid ? { id: nid, role: "nazar", error: (e as Error).message } : x)));
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  const askText = (text: string) => {
    const id = uid();
    setMsgs((m) => [...m, { id, role: "user", text }]);
    runAsk(api.askText(text, camera || null), id);
  };

  const askVoice = (blob: Blob, filename: string, seconds: number) => {
    const id = uid();
    setMsgs((m) => [...m, { id, role: "user", voiceSeconds: seconds }]);
    runAsk(api.askVoice(blob, filename, camera || null), id);
  };

  return (
    <div className="flex min-h-dvh flex-col">
      <TopBar>
        <select
          value={camera}
          onChange={(e) => setCamera(e.target.value)}
          className="max-w-[9.5rem] rounded-full border border-line bg-background px-3 py-1.5 text-sm"
          aria-label="Camera"
        >
          <option value="">All cameras</option>
          {cameras.map((c) => (
            <option key={c.id} value={c.id}>
              {c.live ? "● " : ""}
              {c.name}
            </option>
          ))}
        </select>
      </TopBar>
      <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col px-3">
        <div className="flex-1 space-y-3 py-4">
          {msgs.length === 0 && (
            <div className="mt-6 text-center">
              <div className="text-2xl font-semibold tracking-tight">Ask your CCTV anything</div>
              <div className="mt-1 text-sm text-muted">Tap the lime mic and speak in Hindi, English or Hinglish — or try one of these:</div>
              <div className="mt-5 flex flex-wrap justify-center gap-2">
                {SUGGESTIONS.map((s) => (
                  <button key={s} onClick={() => askText(s)} disabled={busy}
                    className="rounded-full border border-line bg-surface px-3 py-2 text-sm hover:border-primary hover:text-primary">
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}
          {msgs.map((m) => {
            if (m.role === "user")
              return (
                <div key={m.id} className="flex justify-end">
                  <div className="max-w-[85%] rounded-2xl rounded-br-md bg-primary px-3.5 py-2 text-white">
                    {m.voiceSeconds !== undefined ? (
                      <div>
                        <div className="flex items-center gap-1.5 text-sm"><Mic size={14} /> voice note {fmtDuration(m.voiceSeconds)}</div>
                        {m.transcript && <div className="mt-1 text-[13px] text-white/85">“{m.transcript}”</div>}
                      </div>
                    ) : (
                      <div className="text-[15px]">{m.text}</div>
                    )}
                  </div>
                </div>
              );
            if (m.role === "alert")
              return (
                <div key={m.id} className="max-w-[92%]">
                  <AlertBubble alert={m.alert} onOpen={setOpen} autoPlay={!!m.autoPlay} />
                </div>
              );
            return (
              <div key={m.id} className="flex justify-start">
                <div className="w-full max-w-[92%] space-y-2 rounded-2xl rounded-bl-md border border-line bg-surface p-3 shadow-sm">
                  {m.pending && <Spinner label="Watching the footage…" />}
                  {m.error && <ErrorBox message={m.error} />}
                  {m.resp && <Answer resp={m.resp} autoPlay={!!m.autoPlay} onOpen={setOpen} onFollow={askText} busy={busy} />}
                </div>
              </div>
            );
          })}
          <div ref={bottom} />
        </div>
        {msgs.length > 0 && (
          <div className="flex justify-center pb-2">
            <button onClick={() => setMsgs([])} className="inline-flex items-center gap-1 text-xs text-muted hover:text-danger">
              <Trash2 size={12} /> Clear chat
            </button>
          </div>
        )}
      </main>
      <div className="sticky bottom-0 z-20 mx-auto w-full max-w-3xl">
        <Composer onText={askText} onVoice={askVoice} busy={busy} />
      </div>
      {open && <ClipPlayer target={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

function Answer({ resp, autoPlay, onOpen, onFollow, busy }: {
  resp: AskResponse; autoPlay: boolean; onOpen: (t: ClipTarget) => void; onFollow: (t: string) => void; busy: boolean;
}) {
  return (
    <>
      <div className="text-[15px] leading-relaxed">{resp.reply_text}</div>
      {resp.audio_url && <AudioReply url={resp.audio_url} autoPlay={autoPlay} />}
      {resp.count && <CountCard count={resp.count} />}
      {resp.clips.length > 0 && (
        <div className="space-y-2">
          {resp.clips.map((c) => (
            <ClipCard key={c.track_id} clip={c} onOpen={onOpen} />
          ))}
        </div>
      )}
      {resp.rule && <RuleCard rule={resp.rule} onOpen={onOpen} />}
      <GapNote gaps={resp.gaps} />
      {resp.followups.length > 0 && (
        <div className="flex flex-wrap gap-1.5 pt-1">
          {resp.followups.map((f) => (
            <button key={f} disabled={busy} onClick={() => onFollow(f)}
              className="rounded-full bg-primary-soft px-3 py-1 text-xs text-primary hover:bg-primary hover:text-white">
              {f}
            </button>
          ))}
        </div>
      )}
      <div className="text-[10px] text-muted">
        {(resp.latency_ms / 1000).toFixed(1)} s · ₹{(resp.cost_inr ?? 0).toFixed(2)}
      </div>
    </>
  );
}
