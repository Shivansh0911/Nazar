"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { AlertTriangle, BarChart3, Bell, Camera, Loader2, MessageCircle, Volume2, VolumeX } from "lucide-react";
import type { Level, SeriesPoint } from "@/lib/types";
import { fmtHour } from "@/lib/format";
import { useApp } from "./Providers";

export function Logo({ small = false }: { small?: boolean }) {
  return (
    <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
      <svg viewBox="0 0 64 64" className={small ? "h-7 w-7" : "h-8 w-8"} aria-hidden>
        <rect width="64" height="64" rx="16" fill="#0B5FFF" />
        <path d="M10 32c6-10 14-15 22-15s16 5 22 15c-6 10-14 15-22 15S16 42 10 32z" fill="#fff" />
        <circle cx="32" cy="32" r="9" fill="#0B5FFF" />
        <circle cx="32" cy="32" r="4" fill="#D4F53C" />
      </svg>
      <span className="text-lg">Nazar</span>
    </Link>
  );
}

const NAV = [
  { href: "/", label: "Chat", icon: MessageCircle },
  { href: "/cameras/", label: "Cameras", icon: Camera },
  { href: "/rules/", label: "Rules", icon: Bell },
  { href: "/metrics/", label: "Metrics", icon: BarChart3 },
];

export function TopBar({ children }: { children?: React.ReactNode }) {
  const path = usePathname() || "/";
  const { soundOn, setSoundOn, wsConnected } = useApp();
  return (
    <header className="sticky top-0 z-30 border-b border-line bg-surface/90 backdrop-blur">
      <div className="mx-auto flex max-w-5xl items-center gap-3 px-4 py-2.5">
        <Logo />
        <span
          title={wsConnected ? "Live alerts connected" : "Reconnecting…"}
          className={`h-2 w-2 rounded-full ${wsConnected ? "bg-emerald-500" : "bg-amber-400"}`}
        />
        <div className="ml-auto flex items-center gap-1">
          {children}
          <button
            onClick={() => setSoundOn(!soundOn)}
            className="rounded-full p-2 text-muted hover:bg-primary-soft hover:text-primary"
            aria-label={soundOn ? "Sound on" : "Sound off"}
            title={soundOn ? "🔊 Sound on" : "Sound off"}
          >
            {soundOn ? <Volume2 size={18} /> : <VolumeX size={18} />}
          </button>
        </div>
      </div>
      <nav className="mx-auto flex max-w-5xl gap-1 overflow-x-auto px-3 pb-2 scroll-thin">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = href === "/" ? path === "/" : path.startsWith(href.replace(/\/$/, "")) || (href === "/cameras/" && path.startsWith("/camera"));
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm whitespace-nowrap ${
                active ? "bg-primary text-white" : "text-muted hover:bg-primary-soft hover:text-primary"
              }`}
            >
              <Icon size={15} /> {label}
            </Link>
          );
        })}
      </nav>
    </header>
  );
}

export function Page({ children, wide = false }: { children: React.ReactNode; wide?: boolean }) {
  return (
    <>
      <TopBar />
      <main className={`mx-auto w-full ${wide ? "max-w-5xl" : "max-w-3xl"} px-4 py-4`}>{children}</main>
    </>
  );
}

const LEVEL_TEXT: Record<Level, string> = { confirmed: "Confirmed", probable: "Probable", candidate: "Candidate · check this" };

/** Levels differ by more than colour: solid / half-filled / dashed outline + hollow dot. */
export function LevelBadge({ level }: { level: Level }) {
  if (level === "confirmed")
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-600 px-2.5 py-0.5 text-xs font-medium text-white">
        <svg width="8" height="8" aria-hidden><circle cx="4" cy="4" r="4" fill="currentColor" /></svg>
        {LEVEL_TEXT.confirmed}
      </span>
    );
  if (level === "probable")
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-medium text-amber-900 ring-1 ring-amber-400 dark:bg-amber-900/40 dark:text-amber-200">
        <svg width="8" height="8" aria-hidden>
          <circle cx="4" cy="4" r="3.5" fill="none" stroke="currentColor" />
          <path d="M4 0.5 A3.5 3.5 0 0 0 4 7.5 Z" fill="currentColor" />
        </svg>
        {LEVEL_TEXT.probable}
      </span>
    );
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-dashed border-slate-400 px-2.5 py-0.5 text-xs text-muted">
      <svg width="8" height="8" aria-hidden><circle cx="4" cy="4" r="3.2" fill="none" stroke="currentColor" /></svg>
      {LEVEL_TEXT.candidate}
    </span>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-muted">
      <Loader2 className="animate-spin" size={16} /> {label}
    </div>
  );
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex items-start gap-2 rounded-2xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-200">
      <AlertTriangle size={16} className="mt-0.5 shrink-0" />
      <div className="flex-1">{message}</div>
      {onRetry && (
        <button onClick={onRetry} className="font-medium underline">
          Retry
        </button>
      )}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-dashed border-line bg-surface p-6 text-center">
      <div className="font-medium">{title}</div>
      {children && <div className="mt-1 text-sm text-muted">{children}</div>}
    </div>
  );
}

export function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`rounded-2xl border border-line bg-surface p-4 shadow-sm ${className}`}>{children}</div>;
}

export function MiniBars({ series, height = 56 }: { series: SeriesPoint[]; height?: number }) {
  const pts = series.length > 48 ? series.slice(-48) : series;
  const max = Math.max(1, ...pts.map((p) => p.n));
  const w = 100 / Math.max(1, pts.length);
  const firstNonZero = pts.findIndex((p) => p.n > 0);
  return (
    <div>
      <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" className="h-14 w-full" role="img" aria-label="hourly chart">
        {pts.map((p, i) => {
          const h = (p.n / max) * (height - 4);
          return (
            <rect key={p.t} x={i * w + w * 0.12} y={height - h} width={w * 0.76} height={Math.max(h, p.n ? 1.5 : 0.6)} rx={0.8}
              className={p.n ? "fill-primary" : "fill-line"}>
              <title>{`${fmtHour(p.t)}: ${p.n}`}</title>
            </rect>
          );
        })}
      </svg>
      {pts.length > 1 && (
        <div className="mt-1 flex justify-between text-[10px] text-muted">
          <span>{fmtHour(pts[Math.max(0, firstNonZero > 0 ? 0 : 0)].t)}</span>
          <span>{fmtHour(pts[Math.floor(pts.length / 2)].t)}</span>
          <span>{fmtHour(pts[pts.length - 1].t)}</span>
        </div>
      )}
    </div>
  );
}
