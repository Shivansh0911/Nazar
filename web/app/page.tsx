"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { ArrowRight, Bell, Cctv, FileSpreadsheet, Mic, Search, ShieldAlert, Smartphone, Sparkles, Upload } from "lucide-react";
import { api2 } from "@/lib/api2";
import { mjpegUrl, snapshotUrl } from "@/lib/api";
import { fmtDayTime, fmtTime } from "@/lib/format";
import type { Digest } from "@/lib/types2";
import { AudioReply } from "@/components/cards";
import { Card, Empty, LevelBadge, Page, Skeleton } from "@/components/ui";
import { useApp } from "@/components/Providers";

function greeting() {
  const h = Number(new Date().toLocaleString("en-IN", { hour: "numeric", hour12: false, timeZone: "Asia/Kolkata" }));
  return h < 5 ? "Late night watch" : h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

export default function TodayPage() {
  const router = useRouter();
  const { cameras, camerasLoading, alerts } = useApp();
  const [q, setQ] = useState("");
  const [digest, setDigest] = useState<Digest | null>(null);
  const [digestErr, setDigestErr] = useState(false);

  useEffect(() => {
    api2.digest().then(setDigest).catch(() => setDigestErr(true));
  }, []);

  const ask = (text: string) => router.push(`/ask/?q=${encodeURIComponent(text)}`);
  const open = alerts.filter((a) => !a.ack && !a.suppressed).slice(0, 3);

  return (
    <Page>
      <div className="mb-6">
        <div className="text-sm text-muted">{greeting()}</div>
        <h1 className="font-display mt-1 text-4xl md:text-5xl">What happened while you were away?</h1>
        <form onSubmit={(e) => { e.preventDefault(); if (q.trim()) ask(q.trim()); }}
          className="mt-4 flex items-center gap-2 rounded-full border border-line bg-surface p-1.5 pl-4 shadow-[0_8px_30px_rgba(0,0,0,.25)]">
          <Search size={18} className="shrink-0 text-muted" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask anything — “raat 2 baje ke baad counter pe kitne log aaye?”"
            aria-label="Ask anything" className="min-w-0 flex-1 bg-transparent py-2 text-[15px] outline-none" />
          <Link href="/ask/" aria-label="Ask with your voice" className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-lime text-slate-900"><Mic size={18} /></Link>
          <button type="submit" className="hidden rounded-full bg-primary px-4 py-2 text-sm font-medium text-white sm:block">Ask</button>
        </form>
      </div>

      {!camerasLoading && cameras.length === 0 ? <FirstRun /> : (
        <div className="grid gap-5 lg:grid-cols-[1fr_22rem]">
          <div className="min-w-0 space-y-5">
            <section>
              <div className="mb-2 flex items-center"><h2 className="text-sm font-semibold uppercase tracking-wide text-muted">Cameras</h2>
                <Link href="/cameras/new/" className="ml-auto text-xs text-primary">+ Add camera</Link></div>
              <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
                {camerasLoading && [0, 1, 2].map((i) => <Skeleton key={i} className="aspect-[4/3]" />)}
                {cameras.map((c, i) => {
                  const tot = digest?.totals?.find((t) => t.camera_id === c.id);
                  const normal = tot?.normal;
                  const shownCount = c.today_count || tot?.people || 0;
                  const countLabel = c.today_count ? "people today" : tot ? "people · last 12 h of footage" : "people today";
                  return (
                    <motion.div key={c.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.03 }}>
                      <Link href={`/camera/?id=${encodeURIComponent(c.id)}`} className="group block overflow-hidden rounded-3xl border border-line bg-surface hover:border-primary/60">
                        <div className="relative aspect-video bg-black">
                          {/* eslint-disable-next-line @next/next/no-img-element */}
                          <img src={c.live ? mjpegUrl(c.id) : snapshotUrl(c.id)} alt={c.name} loading="lazy" className="h-full w-full object-cover opacity-90 group-hover:opacity-100"
                            onError={(e) => ((e.target as HTMLImageElement).style.opacity = "0")} />
                          <span className={`absolute left-2 top-2 rounded-full px-2 py-0.5 text-[10px] font-semibold ${c.live ? "bg-danger text-white" : "bg-black/60 text-white/90"}`}>
                            {c.live ? <><span className="live-dot">●</span> LIVE</> : c.kind === "file" ? "RECORDED" : "OFFLINE"}
                          </span>
                        </div>
                        <div className="p-3">
                          <div className="truncate text-sm font-medium">{c.name}</div>
                          <div className="mt-0.5 flex items-baseline gap-1.5">
                            <span className="font-display text-2xl">{shownCount}</span>
                            <span className="truncate text-xs text-muted">{countLabel}{typeof normal === "number" && c.today_count ? ` · normal ${normal}` : ""}</span>
                          </div>
                          <div className="truncate text-[11px] text-muted">{c.coverage_to ? `last footage ${fmtDayTime(c.coverage_to)}` : "no footage yet"}</div>
                        </div>
                      </Link>
                    </motion.div>
                  );
                })}
              </div>
            </section>
            <section className="grid gap-3 sm:grid-cols-3">
              {[
                { t: "Kal raat counter pe kitne log aaye?", d: "Count with receipts" },
                { t: "Show me a green backpack", d: "Visual search, AI-verified" },
                { t: "Which hour was busiest on each camera?", d: "Any analysis, with the SQL" },
              ].map((x) => (
                <button key={x.t} onClick={() => ask(x.t)} className="rounded-3xl border border-line bg-surface p-4 text-left hover:border-primary/60">
                  <Sparkles size={16} className="text-primary" />
                  <div className="mt-2 text-sm font-medium">{x.t}</div>
                  <div className="text-xs text-muted">{x.d}</div>
                </button>
              ))}
            </section>
          </div>
          <div className="space-y-5">
            <Card>
              <div className="mb-2 flex items-center gap-2 text-sm font-semibold"><Sparkles size={16} className="text-lime" /> Overnight digest</div>
              {!digest && !digestErr && <div className="space-y-2"><Skeleton className="h-4 w-3/4" /><Skeleton className="h-4 w-2/3" /><Skeleton className="h-4 w-1/2" /></div>}
              {digestErr && <div className="text-sm text-muted">The digest is prepared every morning at 8:00. Ask “aaj raat kya hua?” any time.</div>}
              {digest && (
                <div className="space-y-2">
                  <p className="text-sm leading-relaxed">{digest.text}</p>
                  {digest.audio_url && <AudioReply url={digest.audio_url} autoPlay={false} />}
                  {digest.anomalies.slice(0, 3).map((a, i) => (
                    <div key={i} className="rounded-xl bg-amber/10 px-3 py-2 text-xs"><b>{a.camera_id}</b> · {fmtTime(a.hour)}: {a.count} people vs {a.normal} usual{a.note ? ` (${a.note})` : ""}</div>
                  ))}
                  {digest.items.slice(0, 4).map((e) => (
                    <div key={e.id} className="flex items-center gap-2 text-xs"><LevelBadge level={e.level} /><span>{e.type.replace(/_/g, " ")}</span><span className="ml-auto text-muted">{e.camera_id} · {fmtTime(e.t)}</span></div>
                  ))}
                </div>
              )}
            </Card>
            <Card>
              <div className="mb-2 flex items-center gap-2 text-sm font-semibold"><Bell size={16} className="text-danger" /> Alerts
                <Link href="/alerts/" className="ml-auto text-xs font-normal text-primary">All <ArrowRight size={12} className="inline" /></Link></div>
              {open.length === 0 ? <div className="text-sm text-muted">No open alerts.</div> : open.map((a) => (
                <Link key={a.id} href="/alerts/" className="mb-2 flex gap-2 rounded-2xl border border-danger/40 p-2 last:mb-0 hover:bg-surface-2">
                  {a.snapshot_url && (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={a.snapshot_url} alt="" className="h-12 w-16 rounded-lg object-cover" />
                  )}
                  <div className="min-w-0"><div className="line-clamp-2 text-xs">{a.message}</div><div className="text-[10px] text-muted">{fmtDayTime(a.t)}</div></div>
                </Link>
              ))}
            </Card>
            <Card className="!p-0 overflow-hidden">
              <Link href="/alerts/" className="flex items-center gap-3 p-4 hover:bg-surface-2">
                <ShieldAlert size={20} className="text-primary" />
                <div><div className="text-sm font-medium">Security pack</div><div className="text-xs text-muted">Loitering, abandoned bag, running, fall, crowding, after-hours</div></div>
                <ArrowRight size={16} className="ml-auto text-muted" />
              </Link>
            </Card>
          </div>
        </div>
      )}
    </Page>
  );
}

function FirstRun() {
  const opts = [
    { href: "/cameras/new/?tab=upload", icon: Upload, t: "Upload a video", d: "Any MP4/MOV/DVR export — analysed in minutes" },
    { href: "/cameras/new/?tab=rtsp", icon: Cctv, t: "Connect CCTV", d: "Hikvision, Dahua, CP Plus or any RTSP" },
    { href: "/cameras/new/?tab=phone", icon: Smartphone, t: "Use a phone", d: "Stream from Larix with a QR code" },
    { href: "/cameras/new/?tab=excel", icon: FileSpreadsheet, t: "Import from Excel", d: "Add many cameras at once" },
  ];
  return (
    <div>
      <Empty title="No cameras yet">Start with any of these. Every face is blurred before anything is saved or shown.</Empty>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {opts.map(({ href, icon: Icon, t, d }) => (
          <Link key={href} href={href} className="flex items-center gap-4 rounded-3xl border border-line bg-surface p-5 hover:border-primary">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary-soft text-primary"><Icon size={22} /></div>
            <div><div className="font-medium">{t}</div><div className="text-xs text-muted">{d}</div></div>
          </Link>
        ))}
      </div>
      <div className="mt-4 rounded-3xl border border-dashed border-line p-4 text-sm text-muted">
        Demo footage: run <code className="rounded bg-surface-2 px-1">python scripts/demo_setup.py</code> to load 7 sample cameras (incl. the Builders venue clip).
      </div>
    </div>
  );
}
