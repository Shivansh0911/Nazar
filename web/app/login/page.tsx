"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { Lock, ShieldCheck } from "lucide-react";
import { api, setToken } from "@/lib/api";
import { LogoMark } from "@/components/ui";

export default function LoginPage() {
  const router = useRouter();
  const [pass, setPass] = useState("");
  const [remember, setRemember] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const { token } = await api.auth(pass);
      setToken(token, remember);
      router.replace("/");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="relative flex min-h-dvh items-center justify-center overflow-hidden px-4">
      <div aria-hidden className="pointer-events-none absolute -top-40 left-1/2 h-[36rem] w-[36rem] -translate-x-1/2 rounded-full bg-primary/25 blur-[120px]" />
      <motion.form onSubmit={submit} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}
        className="relative w-full max-w-sm rounded-[2rem] border border-line bg-surface/90 p-7 shadow-2xl backdrop-blur">
        <div className="flex items-center gap-3"><LogoMark className="h-11 w-11" /><span className="text-xl font-semibold">Nazar</span></div>
        <h1 className="font-display mt-6 text-4xl leading-tight">Your CCTV,<br />now you can talk to it.</h1>
        <p className="mt-2 text-sm text-muted">Ask in Hindi, English or Hinglish. Counts with receipts, search by words or photo, alerts that check yesterday first.</p>
        <label className="mt-6 block">
          <span className="sr-only">Passcode</span>
          <div className="flex items-center gap-2 rounded-2xl border border-line bg-surface-2 px-4 focus-within:border-primary">
            <Lock size={16} className="text-muted" />
            <input type="password" autoFocus value={pass} onChange={(e) => setPass(e.target.value)} placeholder="Passcode"
              className="min-w-0 flex-1 bg-transparent py-3 outline-none" autoComplete="current-password" />
          </div>
        </label>
        <label className="mt-3 flex items-center gap-2 text-sm text-muted">
          <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} className="accent-[var(--primary)]" /> Remember this device
        </label>
        {err && <div role="alert" className="mt-3 text-sm text-danger">{err}</div>}
        <button type="submit" disabled={busy || !pass} className="mt-5 w-full rounded-2xl bg-primary py-3 font-semibold text-white transition hover:brightness-110 disabled:opacity-50">
          {busy ? "Checking…" : "Continue"}
        </button>
        <p className="mt-5 flex items-start gap-1.5 text-xs text-muted"><ShieldCheck size={14} className="mt-px shrink-0" /> Faces are blurred before anything is shown or sent. No face recognition, ever.</p>
      </motion.form>
    </main>
  );
}
