"use client";

import { useRef, useState } from "react";
import { ArrowLeftRight, Minus, Plus, Save, Sparkles, Trash2, Undo2 } from "lucide-react";
import type { Zone } from "@/lib/types";

const COLORS = ["#2F6BFF", "#16a34a", "#e11d48", "#d97706", "#7c3aed", "#0891b2"];

function slugify(s: string) {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 40) || "zone";
}

export function ZoneEditor({
  imageUrl,
  aspect,
  initial,
  onSave,
  onSuggest,
}: {
  imageUrl: string;
  aspect: number;
  initial: Zone[];
  onSave: (z: Zone[]) => Promise<void>;
  onSuggest: () => Promise<Zone[]>;
}) {
  const [zones, setZones] = useState<Zone[]>(initial);
  const [sel, setSel] = useState<number>(initial.length ? 0 : -1);
  const [drag, setDrag] = useState<{ z: number; p: number } | null>(null);
  const [busy, setBusy] = useState<"save" | "suggest" | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const svg = useRef<SVGSVGElement>(null);
  const H = 1000 / aspect;

  const toNorm = (e: React.PointerEvent): [number, number] => {
    const r = svg.current!.getBoundingClientRect();
    return [Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (e.clientY - r.top) / r.height))];
  };
  const update = (fn: (z: Zone[]) => Zone[]) => {
    setZones((z) => fn(z));
    setDirty(true);
  };

  const onBgClick = (e: React.PointerEvent) => {
    if (drag || sel < 0) return;
    const [x, y] = toNorm(e);
    update((zs) => zs.map((z, i) => (i === sel && !(z.type === "line" && z.polygon.length >= 2) ? { ...z, polygon: [...z.polygon, [+x.toFixed(4), +y.toFixed(4)]] } : z)));
  };

  const addLine = () => {
    const n = zones.filter((z) => z.type === "line").length + 1;
    update((zs) => [...zs, { name: `door_line_${n}`, label: `Door line ${n}`, polygon: [], type: "line", direction: "right" }]);
    setSel(zones.length);
    setMsg("Tap two points across the doorway. The arrow shows the IN direction - flip it if needed.");
  };

  const addZone = () => {
    const n = zones.length + 1;
    update((zs) => [...zs, { name: `zone_${n}`, label: `Zone ${n}`, polygon: [] }]);
    setSel(zones.length);
    setMsg("Tap on the picture to add corners (3+), drag corners to adjust.");
  };

  const save = async () => {
    const bad = zones.find((z) => (z.type === "line" ? z.polygon.length !== 2 : z.polygon.length < 3));
    if (bad) {
      setMsg(bad.type === "line" ? `"${bad.label}" needs exactly 2 points.` : `"${bad.label}" needs at least 3 corners.`);
      return;
    }
    setBusy("save");
    setMsg(null);
    try {
      await onSave(zones.map((z) => ({ ...z, name: slugify(z.name) })));
      setDirty(false);
      setMsg("Saved. Past footage is being re-checked with the new zones.");
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const suggest = async () => {
    setBusy("suggest");
    setMsg(null);
    try {
      const s = await onSuggest();
      if (!s.length) setMsg("No suggestions.");
      else {
        setZones(s);
        setSel(0);
        setDirty(true);
        setMsg("AI suggestions loaded — edit them, then Save.");
      }
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div>
      <div className="relative w-full overflow-hidden rounded-2xl bg-black" style={{ aspectRatio: String(aspect) }}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={imageUrl} alt="camera view" className="absolute inset-0 h-full w-full object-fill" />
        <svg
          ref={svg}
          viewBox={`0 0 1000 ${H}`}
          preserveAspectRatio="none"
          className="absolute inset-0 h-full w-full touch-none"
          onPointerUp={(e) => (drag ? setDrag(null) : onBgClick(e))}
          onPointerMove={(e) => {
            if (!drag) return;
            const [x, y] = toNorm(e);
            update((zs) => zs.map((z, i) => (i === drag.z ? { ...z, polygon: z.polygon.map((p, j) => (j === drag.p ? [+x.toFixed(4), +y.toFixed(4)] : p)) } : z)));
          }}
        >
          <defs><marker id="nz-arrow" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="4" markerHeight="4" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#D4F53C" /></marker></defs>
          {zones.map((z, i) => {
            const c = COLORS[i % COLORS.length];
            const pts = z.polygon.map(([x, y]) => `${x * 1000},${y * H}`).join(" ");
            return (
              <g key={i} onPointerDown={(e) => { e.stopPropagation(); setSel(i); }}>
                {z.type === "line" ? (
                  <g>
                    {z.polygon.length === 2 && (() => {
                      const [a, b] = z.polygon;
                      const ax = a[0] * 1000, ay = a[1] * H, bx = b[0] * 1000, by = b[1] * H;
                      const mx = (ax + bx) / 2, my = (ay + by) / 2;
                      const len = Math.hypot(bx - ax, by - ay) || 1;
                      const s = z.direction === "left" ? -1 : 1;
                      const nx = (-(by - ay) / len) * s, ny = ((bx - ax) / len) * s;
                      return (
                        <>
                          <line x1={ax} y1={ay} x2={bx} y2={by} stroke={c} strokeWidth={i === sel ? 7 : 5} strokeLinecap="round" />
                          <line x1={mx} y1={my} x2={mx + nx * 60} y2={my + ny * 60} stroke="#D4F53C" strokeWidth={5} markerEnd="url(#nz-arrow)" />
                          <text x={mx + nx * 75} y={my + ny * 75} fill="#D4F53C" fontSize={H / 26} fontWeight={700} textAnchor="middle" style={{ paintOrder: "stroke", stroke: "#000", strokeWidth: 4 }}>IN</text>
                        </>
                      );
                    })()}
                    {z.polygon.length === 1 && <circle cx={z.polygon[0][0] * 1000} cy={z.polygon[0][1] * H} r={10} fill={c} />}
                  </g>
                ) : z.polygon.length >= 3 ? (
                  <polygon points={pts} fill={c} fillOpacity={i === sel ? 0.28 : 0.15} stroke={c} strokeWidth={i === sel ? 5 : 3} />
                ) : (
                  <polyline points={pts} fill="none" stroke={c} strokeWidth={4} strokeDasharray="10 8" />
                )}
                {z.polygon.length > 0 && (
                  <text x={z.polygon[0][0] * 1000 + 6} y={z.polygon[0][1] * H - 10} fill="#fff" fontSize={H / 22} fontWeight={600}
                    style={{ paintOrder: "stroke", stroke: "#000", strokeWidth: 4 }}>
                    {z.label}
                  </text>
                )}
                {i === sel &&
                  z.polygon.map(([x, y], j) => (
                    <circle key={j} cx={x * 1000} cy={y * H} r={14} fill="#fff" stroke={c} strokeWidth={5} className="cursor-move"
                      onPointerDown={(e) => { e.stopPropagation(); (e.target as Element).setPointerCapture?.(e.pointerId); setDrag({ z: i, p: j }); }} />
                  ))}
              </g>
            );
          })}
        </svg>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <button onClick={addZone} className="inline-flex items-center gap-1 rounded-full border border-line px-3 py-1.5 text-sm"><Plus size={14} /> Zone</button>
        <button onClick={addLine} className="inline-flex items-center gap-1 rounded-full border border-line px-3 py-1.5 text-sm"><Minus size={14} /> Count line</button>
        <button onClick={suggest} disabled={!!busy} className="inline-flex items-center gap-1 rounded-full border border-line px-3 py-1.5 text-sm disabled:opacity-50">
          <Sparkles size={14} /> {busy === "suggest" ? "Thinking…" : "Suggest zones with AI"}
        </button>
        <button onClick={save} disabled={!!busy || !dirty} className="ml-auto inline-flex items-center gap-1 rounded-full bg-primary px-4 py-1.5 text-sm font-semibold text-white disabled:opacity-50">
          <Save size={14} /> {busy === "save" ? "Saving…" : "Save"}
        </button>
      </div>
      {msg && <div className="mt-2 text-xs text-muted">{msg}</div>}
      <div className="mt-3 space-y-2">
        {zones.map((z, i) => (
          <div key={i} onClick={() => setSel(i)}
            className={`flex items-center gap-2 rounded-xl border p-2 ${i === sel ? "border-primary bg-primary-soft" : "border-line"}`}>
            <span className="h-3 w-3 shrink-0 rounded-full" style={{ background: COLORS[i % COLORS.length] }} />
            <input value={z.label} onChange={(e) => update((zs) => zs.map((x, k) => (k === i ? { ...x, label: e.target.value, name: slugify(e.target.value) } : x)))}
              className="min-w-0 flex-1 bg-transparent text-sm outline-none" aria-label="Zone label" />
            <code className="hidden text-[11px] text-muted sm:block">{slugify(z.name)}</code>
            <span className="text-[11px] text-muted">{z.type === "line" ? "line" : `${z.polygon.length} pts`}</span>
            {z.type === "line" && (
              <button title="Flip the IN direction" onClick={(e) => { e.stopPropagation(); update((zs) => zs.map((x, k) => (k === i ? { ...x, direction: x.direction === "left" ? "right" : "left" } : x))); }}
                className="rounded-full p-1 text-muted hover:text-foreground"><ArrowLeftRight size={14} /></button>
            )}
            <button title="Remove last corner" onClick={(e) => { e.stopPropagation(); update((zs) => zs.map((x, k) => (k === i ? { ...x, polygon: x.polygon.slice(0, -1) } : x))); }}
              className="rounded-full p-1 text-muted hover:text-foreground"><Undo2 size={14} /></button>
            <button title="Delete zone" onClick={(e) => { e.stopPropagation(); update((zs) => zs.filter((_, k) => k !== i)); setSel(-1); }}
              className="rounded-full p-1 text-muted hover:text-danger"><Trash2 size={14} /></button>
          </div>
        ))}
      </div>
    </div>
  );
}
