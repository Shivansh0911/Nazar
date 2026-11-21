"use client";

import { useCallback, useEffect, useState } from "react";
import { Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { fmtDayTime } from "@/lib/format";
import type { RuleDraft } from "@/lib/types";
import { Composer } from "@/components/Composer";
import { ClipPlayer, type ClipTarget } from "@/components/ClipPlayer";
import { RuleCard } from "@/components/cards";
import { Card, Empty, ErrorBox, Page, Spinner } from "@/components/ui";
import { useApp } from "@/components/Providers";

export default function RulesPage() {
  const { cameras } = useApp();
  const [rules, setRules] = useState<RuleDraft[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [camera, setCamera] = useState("");
  const [draft, setDraft] = useState<RuleDraft | null>(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<ClipTarget | null>(null);

  const load = useCallback(async () => {
    try {
      setRules(await api.rules());
      setErr(null);
    } catch (e) {
      setErr((e as Error).message);
    }
  }, []);
  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    if (!camera && cameras.length) setCamera(cameras[0].id);
  }, [cameras, camera]);

  const compileText = async (text: string) => {
    if (!camera) return;
    setBusy(true);
    setDraft(null);
    setErr(null);
    try {
      setDraft(await api.compileRule(text, camera));
      load();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const compileVoice = async (blob: Blob, filename: string) => {
    // a voice rule goes through /api/ask: the agent transcribes it and calls create_rule
    setBusy(true);
    setDraft(null);
    setErr(null);
    try {
      const r = await api.askVoice(blob, filename, camera || null);
      if (r.rule) setDraft(r.rule);
      else setErr(`Heard: "${r.transcript}" — ${r.reply_text}`);
      load();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-dvh flex-col">
      <Page>
        <h1 className="text-xl font-semibold">Watch rules</h1>
        <p className="mt-1 text-sm text-muted">
          Say what to watch for. Nazar first replays it on past footage so you see how often it would fire — then you activate it.
        </p>
        <Card className="mt-4">
          <label className="text-sm">Camera
            <select value={camera} onChange={(e) => setCamera(e.target.value)}
              className="mt-1 w-full rounded-xl border border-line bg-background px-3 py-2">
              {cameras.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </label>
          <div className="mt-2 text-xs text-muted">Try: “Jab bhi koi desk 14 se bag uthaye, mujhe batana” · “Raat 11 ke baad counter pe koi aaye toh batao”</div>
        </Card>
        {busy && <div className="mt-3"><Spinner label="Compiling and replaying on past footage…" /></div>}
        {err && <div className="mt-3"><ErrorBox message={err} /></div>}
        {draft && <div className="mt-3"><RuleCard rule={draft} onOpen={setOpen} onChange={load} /></div>}
        <h2 className="mt-6 mb-2 text-sm font-semibold text-muted">Your rules</h2>
        {!rules ? <Spinner /> : rules.length === 0 ? <Empty title="No rules yet">Create one above by text or voice.</Empty> : (
          <div className="space-y-3 pb-28">
            {rules.map((r) => (
              <div key={r.rule_id} className="relative">
                <RuleCard rule={r} onOpen={setOpen} onChange={load} />
                <div className="mt-1 flex items-center gap-3 px-2 text-[11px] text-muted">
                  <span>{r.camera_name || r.camera_id}</span>
                  <span>{r.alert_count || 0} alerts{r.last_alert ? ` · last ${fmtDayTime(r.last_alert)}` : ""}</span>
                  <button onClick={async () => { await api.deleteRule(r.rule_id!); load(); }} className="ml-auto inline-flex items-center gap-1 hover:text-danger">
                    <Trash2 size={12} /> Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Page>
      <div className="sticky bottom-0 z-20 mx-auto mt-auto w-full max-w-3xl">
        <Composer onText={compileText} onVoice={compileVoice} busy={busy} placeholder="Describe a rule in your words…" />
      </div>
      {open && <ClipPlayer target={open} onClose={() => setOpen(null)} />}
    </div>
  );
}
