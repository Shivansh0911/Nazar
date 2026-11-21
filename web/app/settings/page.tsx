"use client";

import { useEffect, useState } from "react";
import QRCode from "qrcode";
import { LogOut, MessageSquare, ShieldCheck } from "lucide-react";
import { setToken } from "@/lib/api";
import { api2 } from "@/lib/api2";
import { fmtDayTime } from "@/lib/format";
import { Btn, Card, ErrorBox, Page, Spinner, ThemeToggle } from "@/components/ui";

type S = {
  enrich_mode: string; retention_days: number; openai: boolean; storage: string; max_edges: number; digest_time: string;
  telegram: { configured: boolean; bot: string | null; paired: { chat_id: number; name: string | null; paired_at: string }[] };
  models: Record<string, string>;
};

export default function SettingsPage() {
  const [s, setS] = useState<S | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [pair, setPair] = useState<{ code: string; link: string | null; bot: string | null } | null>(null);
  const [qr, setQr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api2.settings().then((x) => setS(x as unknown as S)).catch((e) => setErr(e.message));
  }, []);

  const getCode = async () => {
    setBusy(true);
    try {
      const p = await api2.pairCode();
      setPair(p);
      if (p.link) setQr(await QRCode.toDataURL(p.link, { margin: 1, width: 220 }));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Page title="Settings" wide={false}>
      {err && <div className="mb-3"><ErrorBox message={err} /></div>}
      {!s ? <Spinner label="Loading…" /> : (
        <div className="space-y-4">
          <Card>
            <div className="mb-2 flex items-center gap-2 font-medium"><MessageSquare size={18} className="text-primary" /> Telegram</div>
            {!s.telegram.configured ? (
              <div className="text-sm text-muted">Add <code>TELEGRAM_BOT_TOKEN</code> to <code>.env</code> and start <code>python -m nazar.telegram.run</code>.</div>
            ) : (
              <div className="text-sm">
                <p className="text-muted">Ask questions by text or voice note, search by photo, and receive alerts with clip + voice note in Telegram.</p>
                <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm">
                  <li>Open {s.telegram.bot ? <a className="text-primary underline" href={`https://t.me/${s.telegram.bot}`} target="_blank" rel="noreferrer">@{s.telegram.bot}</a> : "your bot"} and tap Start.</li>
                  <li>Get a code below and send <code>/pair &lt;code&gt;</code> to the bot (valid 10 minutes).</li>
                </ol>
                <div className="mt-3 flex flex-wrap items-center gap-4">
                  <Btn onClick={getCode} disabled={busy}>{busy ? "…" : pair ? "New code" : "Get pairing code"}</Btn>
                  {pair && <div className="font-display text-4xl tracking-widest">{pair.code}</div>}
                  {qr && (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={qr} alt="QR code to open the bot" className="h-28 w-28 rounded-xl bg-white p-1" />
                  )}
                </div>
                <div className="mt-3 text-xs text-muted">
                  Paired chats: {s.telegram.paired.length ? s.telegram.paired.map((c) => `${c.name || c.chat_id} (${fmtDayTime(c.paired_at)})`).join(", ") : "none yet"}
                </div>
              </div>
            )}
          </Card>
          <Card>
            <div className="mb-2 font-medium">How Nazar spends AI</div>
            <div className="grid grid-cols-2 gap-2 text-sm">
              <div className="rounded-xl bg-surface-2 p-3"><div className="text-xs text-muted">Descriptions</div>{s.enrich_mode === "smart" ? "On demand (smart)" : s.enrich_mode}</div>
              <div className="rounded-xl bg-surface-2 p-3"><div className="text-xs text-muted">Video kept</div>{s.retention_days} days</div>
              <div className="rounded-xl bg-surface-2 p-3"><div className="text-xs text-muted">Morning digest</div>{s.digest_time}</div>
              <div className="rounded-xl bg-surface-2 p-3"><div className="text-xs text-muted">Max live cameras</div>{s.max_edges}</div>
            </div>
            <div className="mt-3 space-y-1 text-xs text-muted">
              {Object.entries(s.models).map(([k, v]) => <div key={k} className="flex justify-between"><span>{k.replace("_", " ")}</span><code>{v}</code></div>)}
            </div>
          </Card>
          <Card>
            <div className="mb-2 flex items-center gap-2 font-medium"><ShieldCheck size={18} className="text-success" /> Privacy</div>
            <ul className="list-disc space-y-1 pl-5 text-sm text-muted">
              <li>No face recognition, ever. Photo search compares clothes, objects and vehicles.</li>
              <li>Faces are blurred in everything that leaves the pipeline: clips, crops, keyframes, live view, PDFs, Telegram.</li>
              <li>Raw video stays on this machine. OpenAI only sees up to 3 blurred crops or a few blurred frames, and your questions.</li>
              <li>Every photo search is kept in an audit log with its purpose.</li>
            </ul>
          </Card>
          <Card>
            <div className="flex items-center gap-2"><ThemeToggle /><Btn kind="ghost" className="ml-auto" onClick={() => { setToken(null); window.location.href = "/login/"; }}><LogOut size={15} /> Log out</Btn></div>
          </Card>
        </div>
      )}
    </Page>
  );
}
