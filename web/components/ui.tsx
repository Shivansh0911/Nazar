"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import {
  AlertTriangle, BarChart3, Bell, Camera, FileText, Home, Loader2, LogOut, MessageCircle, Moon, MoreHorizontal, Radio,
  Search, Settings, Sparkles, Sun, Volume2, VolumeX, X,
} from "lucide-react";
import type { Level, SeriesPoint } from "@/lib/types";
import { fmtHour } from "@/lib/format";
import { setToken } from "@/lib/api";
import { useApp } from "./Providers";

/** Original mark: an eye inside a camera-lens ring. */
export function LogoMark({ className = "h-8 w-8" }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" className={className} aria-hidden>
      <defs>
        <linearGradient id="nz-g" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#FFB020" />
          <stop offset="1" stopColor="#3A2A0A" />
        </linearGradient>
      </defs>
      <circle cx="32" cy="32" r="30" fill="url(#nz-g)" />
      <circle cx="32" cy="32" r="24" fill="none" stroke="#0B0D0E" strokeOpacity=".35" strokeWidth="3" />
      <path d="M12 32c5-8.5 12-13 20-13s15 4.5 20 13c-5 8.5-12 13-20 13s-15-4.5-20-13z" fill="#fff" />
      <circle cx="32" cy="32" r="8.5" fill="#0B0D0E" />
      <circle cx="32" cy="32" r="4" fill="#FFB020" />
      <circle cx="35" cy="29" r="1.6" fill="#fff" />
    </svg>
  );
}

export function Logo() {
  return (
    <Link href="/" className="flex items-center gap-2.5 font-semibold tracking-tight">
      <LogoMark />
      <span className="text-lg">Nazar</span>
    </Link>
  );
}

export const NAV = [
  { href: "/", label: "Today", icon: Home },
  { href: "/ask/", label: "Ask", icon: MessageCircle },
  { href: "/agent/", label: "Investigate", icon: Sparkles },
  { href: "/search/", label: "Search", icon: Search },
  { href: "/live/", label: "Live", icon: Radio },
  { href: "/cameras/", label: "Cameras", icon: Camera },
  { href: "/alerts/", label: "Alerts & rules", icon: Bell },
  { href: "/reports/", label: "Reports", icon: FileText },
  { href: "/metrics/", label: "Insights", icon: BarChart3 },
  { href: "/settings/", label: "Settings", icon: Settings },
];
const MOBILE_MAIN = ["/", "/ask/", "/search/", "/alerts/"];

function isActive(path: string, href: string) {
  if (href === "/") return path === "/";
  const base = href.replace(/\/$/, "");
  return path.startsWith(base) || (href === "/cameras/" && path.startsWith("/camera")) || (href === "/alerts/" && path.startsWith("/rules"));
}

export function ThemeToggle({ compact = false }: { compact?: boolean }) {
  const { theme, setTheme } = useApp();
  return (
    <button
      onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
      className="inline-flex items-center gap-2 rounded-xl p-2 text-sm text-muted hover:bg-surface-2 hover:text-foreground"
      aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
    >
      {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
      {!compact && (theme === "dark" ? "Light theme" : "Dark theme")}
    </button>
  );
}

function SideNav() {
  const path = usePathname() || "/";
  const { alerts, wsConnected, soundOn, setSoundOn } = useApp();
  const unread = alerts.filter((a) => !a.ack && !a.suppressed).length;
  return (
    <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col border-r border-line bg-surface/60 px-3 py-4 md:flex">
      <div className="px-2"><Logo /></div>
      <div className="mt-1 flex items-center gap-1.5 px-2 text-[11px] text-muted">
        <span className={`h-1.5 w-1.5 rounded-full ${wsConnected ? "bg-success live-dot" : "bg-amber"}`} />
        {wsConnected ? "Live alerts connected" : "Reconnecting…"}
      </div>
      <nav className="mt-5 flex flex-1 flex-col gap-0.5">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = isActive(path, href);
          return (
            <Link key={href} href={href}
              className={`flex items-center gap-3 rounded-xl px-3 py-2 text-sm transition ${active ? "bg-primary-soft font-medium text-foreground" : "text-muted hover:bg-surface-2 hover:text-foreground"}`}>
              <Icon size={18} className={active ? "text-primary" : ""} />
              {label}
              {href === "/alerts/" && unread > 0 && <span className="ml-auto rounded-full bg-danger px-1.5 text-[11px] font-semibold text-white">{unread}</span>}
            </Link>
          );
        })}
      </nav>
      <div className="flex items-center gap-1 border-t border-line pt-3">
        <ThemeToggle compact />
        <button onClick={() => setSoundOn(!soundOn)} className="rounded-xl p-2 text-muted hover:bg-surface-2 hover:text-foreground"
          aria-label={soundOn ? "Mute voice replies" : "Unmute voice replies"}>
          {soundOn ? <Volume2 size={18} /> : <VolumeX size={18} />}
        </button>
        <button onClick={() => { setToken(null); window.location.href = "/login/"; }}
          className="ml-auto rounded-xl p-2 text-muted hover:bg-surface-2 hover:text-foreground" aria-label="Log out">
          <LogOut size={18} />
        </button>
      </div>
    </aside>
  );
}

function BottomNav() {
  const path = usePathname() || "/";
  const [more, setMore] = useState(false);
  const { alerts } = useApp();
  const unread = alerts.filter((a) => !a.ack && !a.suppressed).length;
  const main = NAV.filter((n) => MOBILE_MAIN.includes(n.href));
  const rest = NAV.filter((n) => !MOBILE_MAIN.includes(n.href));
  return (
    <>
      <nav className="glass fixed inset-x-0 bottom-0 z-40 flex border-t border-line pb-[env(safe-area-inset-bottom)] md:hidden">
        {main.map(({ href, label, icon: Icon }) => {
          const active = isActive(path, href);
          return (
            <Link key={href} href={href} className={`relative flex flex-1 flex-col items-center gap-0.5 py-2 text-[11px] ${active ? "text-primary" : "text-muted"}`}>
              <Icon size={21} />
              {label.split(" ")[0]}
              {href === "/alerts/" && unread > 0 && <span className="absolute right-[28%] top-1 h-2 w-2 rounded-full bg-danger" />}
            </Link>
          );
        })}
        <button onClick={() => setMore(true)} className="flex flex-1 flex-col items-center gap-0.5 py-2 text-[11px] text-muted" aria-label="More">
          <MoreHorizontal size={21} /> More
        </button>
      </nav>
      {more && (
        <div className="fixed inset-0 z-50 bg-black/50 md:hidden" onClick={() => setMore(false)}>
          <div className="absolute inset-x-0 bottom-0 rounded-t-3xl border-t border-line bg-surface p-4 pb-[max(1rem,env(safe-area-inset-bottom))]" onClick={(e) => e.stopPropagation()}>
            <div className="mb-2 flex items-center"><span className="font-medium">More</span>
              <button onClick={() => setMore(false)} className="ml-auto rounded-full p-2" aria-label="Close"><X size={18} /></button></div>
            <div className="grid grid-cols-3 gap-2">
              {rest.map(({ href, label, icon: Icon }) => (
                <Link key={href} href={href} onClick={() => setMore(false)}
                  className="flex flex-col items-center gap-1 rounded-2xl bg-surface-2 p-3 text-xs">
                  <Icon size={20} className="text-primary" /> {label}
                </Link>
              ))}
            </div>
            <div className="mt-3 flex items-center justify-between"><ThemeToggle /></div>
          </div>
        </div>
      )}
    </>
  );
}

export function MobileHeader({ title, children }: { title?: string; children?: React.ReactNode }) {
  return (
    <header className="glass sticky top-0 z-30 flex items-center gap-2 border-b border-line px-4 py-2.5 md:hidden">
      <Link href="/" aria-label="Nazar home"><LogoMark className="h-7 w-7" /></Link>
      <span className="truncate font-semibold">{title || "Nazar"}</span>
      <div className="ml-auto flex items-center gap-1">{children}</div>
    </header>
  );
}

/** App shell: side rail on desktop, header + bottom tabs on phones. */
export function Shell({ children, title, actions, bare = false }: { children: React.ReactNode; title?: string; actions?: React.ReactNode; bare?: boolean }) {
  return (
    <div className="flex min-h-dvh">
      <SideNav />
      <div className="flex min-w-0 flex-1 flex-col">
        <MobileHeader title={title}>{actions}</MobileHeader>
        <div className={bare ? "flex min-h-0 flex-1 flex-col" : "flex-1 pb-24 md:pb-8"}>{children}</div>
      </div>
      <BottomNav />
    </div>
  );
}

export function Page({ children, title, subtitle, actions, wide = true }: {
  children: React.ReactNode; title?: string; subtitle?: React.ReactNode; actions?: React.ReactNode; wide?: boolean;
}) {
  return (
    <Shell title={title}>
      <main className={`mx-auto w-full ${wide ? "max-w-6xl" : "max-w-3xl"} px-4 py-5 md:px-8 md:py-8`}>
        {(title || actions) && (
          <div className="mb-5 flex flex-wrap items-end gap-3">
            <div className="min-w-0">
              {title && <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">{title}</h1>}
              {subtitle && <div className="mt-1 text-sm text-muted">{subtitle}</div>}
            </div>
            {actions && <div className="ml-auto flex flex-wrap items-center gap-2">{actions}</div>}
          </div>
        )}
        {children}
      </main>
    </Shell>
  );
}

const LEVEL_TEXT: Record<Level, string> = { confirmed: "Confirmed", probable: "Probable", candidate: "Candidate · check this" };

/** Levels differ by more than colour: solid / half-filled / dashed outline + hollow dot. */
export function LevelBadge({ level, verified }: { level: Level; verified?: boolean }) {
  if (level === "confirmed")
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-success px-2.5 py-0.5 text-xs font-medium text-white">
        <svg width="8" height="8" aria-hidden><circle cx="4" cy="4" r="4" fill="currentColor" /></svg>
        {LEVEL_TEXT.confirmed}
      </span>
    );
  if (level === "probable")
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-amber/15 px-2.5 py-0.5 text-xs font-medium text-amber ring-1 ring-amber/60">
        <svg width="8" height="8" aria-hidden>
          <circle cx="4" cy="4" r="3.5" fill="none" stroke="currentColor" />
          <path d="M4 0.5 A3.5 3.5 0 0 0 4 7.5 Z" fill="currentColor" />
        </svg>
        {LEVEL_TEXT.probable}{verified ? " · AI-verified" : ""}
      </span>
    );
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-dashed border-muted/70 px-2.5 py-0.5 text-xs text-muted">
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

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton rounded-xl ${className}`} />;
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex items-start gap-2 rounded-2xl border border-danger/40 bg-danger/10 p-3 text-sm text-foreground">
      <AlertTriangle size={16} className="mt-0.5 shrink-0 text-danger" />
      <div className="flex-1">{message}</div>
      {onRetry && <button onClick={onRetry} className="font-medium text-primary underline">Retry</button>}
    </div>
  );
}

export function Empty({ title, children, icon }: { title: string; children?: React.ReactNode; icon?: React.ReactNode }) {
  return (
    <div className="rounded-3xl border border-dashed border-line bg-surface/50 p-8 text-center">
      {icon && <div className="mb-2 flex justify-center text-muted">{icon}</div>}
      <div className="font-medium">{title}</div>
      {children && <div className="mt-1 text-sm text-muted">{children}</div>}
    </div>
  );
}

export function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`rounded-3xl border border-line bg-surface p-4 md:p-5 ${className}`}>{children}</div>;
}

export function Stat({ label, value, hint, accent = false }: { label: string; value: React.ReactNode; hint?: React.ReactNode; accent?: boolean }) {
  return (
    <div className={`rounded-3xl border p-4 ${accent ? "border-primary/40 bg-primary-soft" : "border-line bg-surface"}`}>
      <div className="text-xs font-medium uppercase tracking-wide text-muted">{label}</div>
      <div className="font-display mt-1 text-4xl leading-none">{value}</div>
      {hint && <div className="mt-1.5 text-xs text-muted">{hint}</div>}
    </div>
  );
}

export function Btn({ children, onClick, disabled, kind = "primary", type = "button", className = "", ...rest }: {
  children: React.ReactNode; onClick?: () => void; disabled?: boolean; kind?: "primary" | "ghost" | "soft" | "lime" | "danger";
  type?: "button" | "submit"; className?: string; "aria-label"?: string; title?: string;
}) {
  const k = {
    primary: "bg-primary text-on-primary hover:brightness-110",
    ghost: "border border-line text-foreground hover:bg-surface-2",
    soft: "bg-primary-soft text-primary hover:brightness-110",
    lime: "bg-lime text-slate-900 hover:brightness-105",
    danger: "bg-danger text-white",
  }[kind];
  return (
    <button type={type} onClick={onClick} disabled={disabled} {...rest}
      className={`inline-flex items-center justify-center gap-1.5 rounded-full px-4 py-2 text-sm font-medium transition active:scale-[.98] disabled:opacity-50 ${k} ${className}`}>
      {children}
    </button>
  );
}

export function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-muted">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11px] text-muted">{hint}</span>}
    </label>
  );
}

export const inputCls = "w-full rounded-xl border border-line bg-surface-2 px-3 py-2.5 text-sm outline-none focus:border-primary";

export function MiniBars({ series, height = 56 }: { series: SeriesPoint[]; height?: number }) {
  const pts = series.length > 48 ? series.slice(-48) : series;
  const max = Math.max(1, ...pts.map((p) => p.n));
  const w = 100 / Math.max(1, pts.length);
  return (
    <div>
      <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" className="h-14 w-full" role="img" aria-label="activity chart">
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
          <span>{fmtHour(pts[0].t)}</span>
          <span>{fmtHour(pts[pts.length - 1].t)}</span>
        </div>
      )}
    </div>
  );
}
