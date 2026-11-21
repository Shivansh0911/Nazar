"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, setToken } from "@/lib/api";
import { Logo } from "@/components/ui";

export default function LoginPage() {
  const router = useRouter();
  const [pass, setPass] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const { token } = await api.auth(pass);
      setToken(token);
      router.replace("/");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="flex min-h-dvh items-center justify-center px-4">
      <form onSubmit={submit} className="w-full max-w-sm rounded-3xl border border-line bg-surface p-6 shadow-sm">
        <Logo />
        <h1 className="mt-5 text-2xl font-semibold tracking-tight">Ask your CCTV anything</h1>
        <p className="mt-1 text-sm text-muted">In Hindi, English or Hinglish. Enter the demo passcode to continue.</p>
        <input
          type="password"
          autoFocus
          value={pass}
          onChange={(e) => setPass(e.target.value)}
          placeholder="Passcode"
          className="mt-5 w-full rounded-2xl border border-line bg-background px-4 py-3 outline-none focus:border-primary"
        />
        {err && <div className="mt-2 text-sm text-danger">{err}</div>}
        <button disabled={busy || !pass} className="mt-4 w-full rounded-2xl bg-primary py-3 font-semibold text-white disabled:opacity-50">
          {busy ? "Checking…" : "Continue"}
        </button>
        <p className="mt-4 text-xs text-muted">Faces are blurred before anything is saved. No face recognition, ever.</p>
      </form>
    </main>
  );
}
