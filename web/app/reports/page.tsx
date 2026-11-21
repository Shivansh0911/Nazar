"use client";

import { useCallback, useEffect, useState } from "react";
import { FileText, ShieldCheck } from "lucide-react";
import { api2 } from "@/lib/api2";
import { fmtDayTime } from "@/lib/format";
import type { ReportOut } from "@/lib/types2";
import { Empty, ErrorBox, Page, Skeleton } from "@/components/ui";

export default function ReportsPage() {
  const [items, setItems] = useState<ReportOut[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(() => {
    api2.reports().then((r) => { setItems(r); setErr(null); }).catch((e) => setErr(e.message));
  }, []);
  useEffect(() => { load(); }, [load]);
  return (
    <Page title="Reports" subtitle="Police-ready incident PDFs: timeline, blurred key frames, evidence levels and SHA-256 hashes of every exported file.">
      {err && <ErrorBox message={err} onRetry={load} />}
      {!items && !err && <div className="space-y-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-16" />)}</div>}
      {items && items.length === 0 && (
        <Empty title="No reports yet" icon={<FileText size={22} />}>Open an alert or a security event and tap “Incident report”, or ask: “is alert ki report banao”.</Empty>
      )}
      <div className="space-y-2">
        {items?.map((r) => (
          <a key={r.id} href={r.pdf_url || "#"} target="_blank" rel="noreferrer"
            className="flex items-center gap-3 rounded-2xl border border-line bg-surface p-3 hover:border-primary/60">
            {r.preview_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={r.preview_url} alt="" className="h-16 w-12 rounded-lg border border-line object-cover object-top" />
            ) : <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-primary-soft text-primary"><FileText size={20} /></div>}
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium">{r.title}</div>
              <div className="text-xs text-muted">#{r.id} · {fmtDayTime(r.at)} · {r.language === "hi" ? "हिन्दी" : "English"}</div>
              {r.manifest_sha256 && <div className="truncate font-mono text-[10px] text-muted">manifest SHA-256 {r.manifest_sha256}</div>}
            </div>
            <span className="text-xs text-primary">Open PDF</span>
          </a>
        ))}
      </div>
      <div className="mt-6 flex items-start gap-2 text-xs text-muted"><ShieldCheck size={14} className="mt-0.5 shrink-0" />
        Reports never use face recognition. Faces are blurred in every frame; identification, if needed, is for the authorities from the original recording.</div>
    </Page>
  );
}
