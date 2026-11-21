"use client";

import { useEffect, useRef, useState } from "react";
import { Camera, Mic, SendHorizontal, Square } from "lucide-react";

const MAX_S = 30;

function pickMime(): { mime: string; ext: string } {
  const opts = [
    { mime: "audio/webm;codecs=opus", ext: "webm" },
    { mime: "audio/webm", ext: "webm" },
    { mime: "audio/mp4", ext: "mp4" },
    { mime: "audio/ogg;codecs=opus", ext: "ogg" },
  ];
  if (typeof MediaRecorder === "undefined") return { mime: "", ext: "webm" };
  for (const o of opts) if (MediaRecorder.isTypeSupported(o.mime)) return o;
  return { mime: "", ext: "webm" };
}

export function Composer({
  onText,
  onVoice,
  busy,
  onPhoto,
  placeholder = "Ask in Hindi, English or Hinglish…",
}: {
  onPhoto?: () => void;
  onText: (t: string) => void;
  onVoice: (blob: Blob, filename: string, seconds: number) => void;
  busy: boolean;
  placeholder?: string;
}) {
  const [text, setText] = useState("");
  const [rec, setRec] = useState(false);
  const [secs, setSecs] = useState(0);
  const [level, setLevel] = useState(0);
  const [micErr, setMicErr] = useState<string | null>(null);
  const mr = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const started = useRef(0);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const raf = useRef(0);
  const ctxRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const cleanup = () => {
    if (timer.current) clearInterval(timer.current);
    cancelAnimationFrame(raf.current);
    streamRef.current?.getTracks().forEach((t) => t.stop());
    ctxRef.current?.close().catch(() => undefined);
    ctxRef.current = null;
    setLevel(0);
  };
  useEffect(() => cleanup, []);

  const start = async () => {
    setMicErr(null);
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      setMicErr("The microphone needs HTTPS (or localhost). Type your question instead.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      streamRef.current = stream;
      const { mime, ext } = pickMime();
      const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      chunks.current = [];
      recorder.ondataavailable = (e) => {
        if (e.data.size) chunks.current.push(e.data);
      };
      recorder.onstop = () => {
        const seconds = (Date.now() - started.current) / 1000;
        const type = recorder.mimeType || mime || "audio/webm";
        const blob = new Blob(chunks.current, { type });
        const realExt = type.includes("mp4") ? "mp4" : type.includes("ogg") ? "ogg" : ext;
        cleanup();
        setRec(false);
        if (seconds >= 0.6 && blob.size > 500) onVoice(blob, `voice-note.${realExt}`, seconds);
        else setMicErr("That was too short — hold on a little longer.");
      };
      // level meter
      const ctx = new AudioContext();
      ctxRef.current = ctx;
      const an = ctx.createAnalyser();
      an.fftSize = 256;
      ctx.createMediaStreamSource(stream).connect(an);
      const buf = new Uint8Array(an.frequencyBinCount);
      const tick = () => {
        an.getByteTimeDomainData(buf);
        let peak = 0;
        for (const v of buf) peak = Math.max(peak, Math.abs(v - 128));
        setLevel(Math.min(1, peak / 64));
        raf.current = requestAnimationFrame(tick);
      };
      tick();
      started.current = Date.now();
      setSecs(0);
      timer.current = setInterval(() => {
        const s = (Date.now() - started.current) / 1000;
        setSecs(s);
        if (s >= MAX_S && recorder.state === "recording") recorder.stop();
      }, 200);
      recorder.start();
      mr.current = recorder;
      setRec(true);
    } catch {
      cleanup();
      setMicErr("Microphone permission was blocked. Allow it in the browser, or type instead.");
    }
  };

  const stop = () => {
    if (mr.current && mr.current.state === "recording") mr.current.stop();
  };

  const send = () => {
    const t = text.trim();
    if (!t || busy) return;
    onText(t);
    setText("");
  };

  return (
    <div className="glass border-t border-line px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-2">
      {micErr && <div className="mb-2 text-xs text-danger">{micErr}</div>}
      <div className="flex items-center gap-2">
        <button
          onClick={rec ? stop : start}
          disabled={busy && !rec}
          aria-label={rec ? "Stop recording" : "Record a voice note"}
          className={`flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-lime text-slate-900 shadow-md transition active:scale-95 disabled:opacity-50 ${rec ? "mic-recording" : ""}`}
        >
          {rec ? <Square size={22} fill="currentColor" /> : <Mic size={26} />}
        </button>
        {rec ? (
          <div className="flex flex-1 items-center gap-3 rounded-full bg-surface-2 px-4 py-3">
            <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-danger" />
            <span className="font-mono text-sm tabular-nums">
              0:{String(Math.floor(secs)).padStart(2, "0")} / 0:{MAX_S}
            </span>
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-line">
              <div className="h-full bg-primary transition-[width] duration-75" style={{ width: `${Math.round(level * 100)}%` }} />
            </div>
            <span className="text-xs text-muted">tap ■ to send</span>
          </div>
        ) : (
          <>
            {onPhoto && (
              <button onClick={onPhoto} disabled={busy} aria-label="Search by photo" title="Search by photo"
                className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full border border-line text-muted hover:border-primary hover:text-primary disabled:opacity-50">
                <Camera size={20} />
              </button>
            )}
            <input
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && send()}
              placeholder={placeholder}
              className="min-w-0 flex-1 rounded-full border border-line bg-surface-2 px-4 py-3 text-[15px] outline-none focus:border-primary"
              disabled={busy}
            />
            <button
              onClick={send}
              disabled={busy || !text.trim()}
              aria-label="Send"
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-primary text-white disabled:opacity-40"
            >
              <SendHorizontal size={20} />
            </button>
          </>
        )}
      </div>
    </div>
  );
}
