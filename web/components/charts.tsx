"use client";

import { useState } from "react";
import { Bar, BarChart, Cell, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ChevronDown, Code2 } from "lucide-react";
import type { SeriesPoint } from "@/lib/types";
import type { ChartOut, TableOut } from "@/lib/types2";

const TZ = "Asia/Kolkata";
const PALETTE = ["#2F6BFF", "#D4F53C", "#10B981", "#F59E0B", "#A78BFA", "#22D3EE", "#F43F5E"];

function bucketLabel(iso: string, bucket?: string) {
  const d = new Date(iso);
  if (bucket === "day") return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: TZ });
  const opts: Intl.DateTimeFormatOptions = { hour: "numeric", minute: "2-digit", timeZone: TZ };
  if (bucket === "10s") opts.second = "2-digit";
  return d.toLocaleTimeString("en-IN", opts).replace(" ", "").toLowerCase();
}

const tooltipStyle = {
  background: "var(--surface)", border: "1px solid var(--line)", borderRadius: 12, color: "var(--foreground)", fontSize: 12,
};

/** Count chart: bars are clickable (filters the receipts to that bucket). */
export function ActivityChart({ series, bucket, selected, onSelect, height = 150 }: {
  series: SeriesPoint[]; bucket?: string; selected?: string | null; onSelect?: (t: string | null) => void; height?: number;
}) {
  const data = series.map((p) => ({ t: p.t, n: p.n, label: bucketLabel(p.t, bucket) }));
  if (!data.length) return null;
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 6, right: 4, left: -24, bottom: 0 }}>
          <XAxis dataKey="label" tick={{ fill: "var(--muted)", fontSize: 10 }} tickLine={false} axisLine={false} interval="preserveStartEnd" minTickGap={18} />
          <YAxis allowDecimals={false} tick={{ fill: "var(--muted)", fontSize: 10 }} tickLine={false} axisLine={false} width={40} />
          <Tooltip cursor={{ fill: "var(--primary-soft)" }} contentStyle={tooltipStyle} formatter={(v) => [v as number, "count"]} />
          <Bar dataKey="n" radius={[6, 6, 2, 2]} onClick={(d) => onSelect?.(selected === (d as { t: string }).t ? null : (d as { t: string }).t)}
            style={{ cursor: onSelect ? "pointer" : "default" }}>
            {data.map((d) => (
              <Cell key={d.t} fill={selected && selected !== d.t ? "var(--line)" : d.n ? "#2F6BFF" : "var(--line)"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function ChartCard({ chart }: { chart: ChartOut }) {
  const data = chart.data.map((d) => ({ x: String(d.x).replace(/T(\d\d:\d\d).*/, " $1"), y: Number(d.y) || 0 }));
  return (
    <div className="rounded-2xl border border-line bg-surface-2 p-3">
      <div className="mb-2 text-sm font-medium">{chart.title}</div>
      <div className="h-48 w-full">
        <ResponsiveContainer width="100%" height="100%">
          {chart.type === "line" ? (
            <LineChart data={data} margin={{ top: 6, right: 8, left: -20, bottom: 0 }}>
              <XAxis dataKey="x" tick={{ fill: "var(--muted)", fontSize: 10 }} tickLine={false} axisLine={false} />
              <YAxis tick={{ fill: "var(--muted)", fontSize: 10 }} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={tooltipStyle} />
              <Line type="monotone" dataKey="y" stroke="#2F6BFF" strokeWidth={2.5} dot={false} />
            </LineChart>
          ) : chart.type === "pie" ? (
            <PieChart>
              <Tooltip contentStyle={tooltipStyle} />
              <Pie data={data} dataKey="y" nameKey="x" innerRadius="45%" outerRadius="80%" paddingAngle={2}>
                {data.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
              </Pie>
            </PieChart>
          ) : (
            <BarChart data={data} margin={{ top: 6, right: 8, left: -20, bottom: 0 }}>
              <XAxis dataKey="x" tick={{ fill: "var(--muted)", fontSize: 10 }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
              <YAxis tick={{ fill: "var(--muted)", fontSize: 10 }} tickLine={false} axisLine={false} />
              <Tooltip cursor={{ fill: "var(--primary-soft)" }} contentStyle={tooltipStyle} />
              <Bar dataKey="y" fill="#2F6BFF" radius={[6, 6, 2, 2]} />
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
      {chart.unit && <div className="mt-1 text-right text-[11px] text-muted">{chart.unit}</div>}
    </div>
  );
}

function cell(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return Number.isInteger(v) ? v.toLocaleString("en-IN") : v.toFixed(2);
  const s = String(v);
  if (/^\d{4}-\d\d-\d\dT\d\d:\d\d/.test(s)) {
    const d = new Date(s);
    if (!isNaN(d.getTime())) return d.toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit", timeZone: TZ });
  }
  if (Array.isArray(v)) return v.join(", ");
  return s;
}

export function DataTable({ table }: { table: TableOut }) {
  const [sql, setSql] = useState(false);
  const rows = table.rows.slice(0, 50);
  return (
    <div className="rounded-2xl border border-line bg-surface-2 p-3">
      <div className="mb-2 flex items-center gap-2">
        <div className="text-sm font-medium">{table.title}</div>
        {typeof table.change_pct === "number" && (
          <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${table.change_pct >= 0 ? "bg-success/15 text-success" : "bg-danger/15 text-danger"}`}>
            {table.change_pct >= 0 ? "+" : ""}{table.change_pct}%
          </span>
        )}
        <span className="ml-auto text-[11px] text-muted">{table.row_count} row{table.row_count === 1 ? "" : "s"} · database fact</span>
      </div>
      <div className="overflow-x-auto scroll-thin">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="text-[11px] uppercase tracking-wide text-muted">
              {table.columns.map((c) => <th key={c} className="whitespace-nowrap px-2 py-1 font-medium">{c.replace(/_/g, " ")}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-t border-line">
                {table.columns.map((c) => <td key={c} className="whitespace-nowrap px-2 py-1.5 tabular-nums">{cell(r[c])}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {table.sql && (
        <div className="mt-2">
          <button onClick={() => setSql(!sql)} className="inline-flex items-center gap-1 text-xs text-muted hover:text-foreground">
            <Code2 size={13} /> How this was computed <ChevronDown size={13} className={sql ? "rotate-180" : ""} />
          </button>
          {sql && <pre className="mt-1 overflow-x-auto whitespace-pre-wrap rounded-xl bg-background p-2 text-[11px] text-muted">{table.sql}</pre>}
        </div>
      )}
    </div>
  );
}
