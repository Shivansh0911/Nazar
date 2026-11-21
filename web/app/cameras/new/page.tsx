"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import QRCode from "qrcode";
import { Cctv, CheckCircle2, Download, FileSpreadsheet, Plug, Radar, Smartphone, Upload, XCircle } from "lucide-react";
import { API_BASE, api, getToken, mjpegUrl } from "@/lib/api";
import { api2 } from "@/lib/api2";
import type { CameraOut } from "@/lib/types";
import type { ProbeResult } from "@/lib/types2";
import { Btn, Card, ErrorBox, Field, Page, Spinner, inputCls } from "@/components/ui";
import { useApp } from "@/components/Providers";

type Tab = "upload" | "rtsp" | "phone" | "excel";
const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40);

export default function NewCameraPage() {
  const [tab, setTab] = useState<Tab>("upload");
  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get("tab") as Tab | null;
    if (t && ["upload", "rtsp", "phone", "excel"].includes(t)) setTab(t);
  }, []);
  const tabs: { id: Tab; label: string; icon: typeof Upload }[] = [
    { id: "upload", label: "Upload video", icon: Upload },
    { id: "rtsp", label: "CCTV / DVR", icon: Cctv },
    { id: "phone", label: "Phone", icon: Smartphone },
    { id: "excel", label: "Excel import", icon: FileSpreadsheet },
  ];
  return (
    <Page title="Add camera" subtitle="Any video, any camera. Faces are blurred in everything Nazar shows or sends.">
      <div className="mb-5 grid grid-cols-2 gap-1 rounded-3xl border border-line bg-surface p-1 md:flex md:w-fit md:rounded-full">
        {tabs.map(({ id, label, icon: Icon }) => (
          <button key={id} onClick={() => setTab(id)}
            className={`flex items-center justify-center gap-1.5 whitespace-nowrap rounded-full px-4 py-2 text-sm ${tab === id ? "bg-primary text-white" : "text-muted hover:text-foreground"}`}>
            <Icon size={15} /> {label}
          </button>
        ))}
      </div>
      {tab === "upload" && <UploadTab />}
      {tab === "rtsp" && <CctvTab />}
      {tab === "phone" && <PhoneTab />}
      {tab === "excel" && <ExcelTab />}
    </Page>
  );
}

// ---- upload: resumable chunks, several files, live analysis view ------------------------------------------------
type Up = { file: File; name: string; recorded: string; pct: number; state: "waiting" | "uploading" | "processing" | "error"; err?: string; cam?: CameraOut };

function UploadTab() {
  const { refreshCameras } = useApp();
  const [items, setItems] = useState<Up[]>([]);
  const [drag, setDrag] = useState(false);
  const [running, setRunning] = useState(false);

  const add = (files: FileList | null) => {
    if (!files) return;
    setItems((x) => [...x, ...Array.from(files).map((f) => ({ file: f, name: f.name.replace(/\.[^.]+$/, "").slice(0, 40), recorded: "", pct: 0, state: "waiting" as const }))]);
  };
  const patch = (i: number, p: Partial<Up>) => setItems((x) => x.map((it, k) => (k === i ? { ...it, ...p } : it)));

  const uploadOne = async (i: number, it: Up) => {
    patch(i, { state: "uploading", pct: 0, err: undefined });
    try {
      const init = await api2.uploadInit({ filename: it.file.name, size: it.file.size, name: it.name, recorded_at: it.recorded || null });
      const have = new Set(init.received);
      for (let k = 0; k < init.parts; k++) {
        if (have.has(k)) continue;
        const blob = it.file.slice(k * init.chunk_size, Math.min(it.file.size, (k + 1) * init.chunk_size));
        let tries = 0;
        for (;;) {
          try {
            await api2.uploadPart(init.upload_id, k, blob);
            break;
          } catch (e) {
            if (++tries >= 5) throw e; // a flaky connection retries each 8 MB part
            await new Promise((r) => setTimeout(r, 1000 * tries));
          }
        }
        patch(i, { pct: (k + 1) / init.parts });
      }
      const done = await api2.uploadComplete(init.upload_id);
      patch(i, { state: "processing", cam: done.camera, pct: 1 });
      refreshCameras();
    } catch (e) {
      patch(i, { state: "error", err: (e as Error).message });
    }
  };
  const start = async () => {
    setRunning(true);
    for (let i = 0; i < items.length; i++) if (items[i].state === "waiting" || items[i].state === "error") await uploadOne(i, items[i]);
    setRunning(false);
  };

  return (
    <div className="space-y-4">
      <label onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); add(e.dataTransfer.files); }}
        className={`flex cursor-pointer flex-col items-center gap-2 rounded-3xl border-2 border-dashed p-10 text-center ${drag ? "border-primary bg-primary-soft" : "border-line bg-surface"}`}>
        <Upload size={30} className="text-primary" />
        <div className="font-medium">Drop videos here or tap to choose</div>
        <div className="text-xs text-muted">MP4, MOV, MKV, AVI or DVR exports · up to 4 GB / 3 hours each · uploads resume if the Wi-Fi drops</div>
        <input type="file" accept="video/*,.mkv,.avi,.dav,.ts" multiple className="hidden" onChange={(e) => add(e.target.files)} />
      </label>
      {items.map((it, i) => (
        <Card key={i} className="!p-4">
          {it.state === "processing" && it.cam ? <Analysis cam={it.cam} /> : (
            <div className="space-y-3">
              <div className="flex items-center gap-2 text-sm"><span className="truncate font-medium">{it.file.name}</span>
                <span className="ml-auto shrink-0 text-xs text-muted">{(it.file.size / 1024 / 1024).toFixed(1)} MB</span></div>
              {it.state === "waiting" || it.state === "error" ? (
                <div className="grid gap-2 sm:grid-cols-2">
                  <Field label="Camera / place name"><input value={it.name} onChange={(e) => patch(i, { name: e.target.value })} className={inputCls} /></Field>
                  <Field label="Recorded at (optional)" hint="Leave empty: it ends now"><input type="datetime-local" value={it.recorded} onChange={(e) => patch(i, { recorded: e.target.value })} className={inputCls} /></Field>
                </div>
              ) : null}
              {it.state === "uploading" && (
                <div><div className="mb-1 flex justify-between text-xs"><span>Uploading…</span><span>{Math.round(it.pct * 100)}%</span></div>
                  <div className="h-2 overflow-hidden rounded-full bg-line"><div className="h-full bg-primary transition-all" style={{ width: `${it.pct * 100}%` }} /></div></div>
              )}
              {it.err && <ErrorBox message={it.err} />}
            </div>
          )}
        </Card>
      ))}
      {items.some((x) => x.state === "waiting" || x.state === "error") && (
        <Btn onClick={start} disabled={running} className="w-full sm:w-auto">{running ? <Spinner label="Uploading…" /> : `Upload & analyse ${items.filter((x) => x.state === "waiting" || x.state === "error").length} video(s)`}</Btn>
      )}
    </div>
  );
}

/** Live analysis view: the video is watched at many times real time; boxes and counts appear as they are found. */
function Analysis({ cam }: { cam: CameraOut }) {
  const [a, setA] = useState<Awaited<ReturnType<typeof api2.analysis>> | null>(null);
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const r = await api2.analysis(cam.id);
        if (!alive) return;
        setA(r);
        if (r.job && (r.job.state === "ready" || r.job.state === "error")) return;
      } catch {
        /* keep polling */
      }
      if (alive) setTimeout(tick, 1000);
    };
    tick();
    return () => { alive = false; };
  }, [cam.id]);
  const st = a?.stats || {};
  const dur = a?.job?.duration_s || st.duration_s || 0;
  const done = a?.job?.processed_s || st.processed_s || 0;
  const frac = dur ? Math.min(1, done / dur) : 0;
  const ready = a?.job?.state === "ready";
  return (
    <div className="grid gap-4 md:grid-cols-[1.4fr_1fr]">
      <div className="relative aspect-video overflow-hidden rounded-2xl bg-black">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={mjpegUrl(cam.id)} alt="analysis view" className="h-full w-full object-contain" />
        {!ready && <span className="absolute left-2 top-2 rounded-full bg-primary px-2 py-0.5 text-[10px] font-semibold text-white">ANALYSING {st.speed_x ? `${st.speed_x}×` : ""}</span>}
      </div>
      <div className="flex flex-col">
        <div className="font-medium">{cam.name}</div>
        <div className="mt-3 grid grid-cols-2 gap-2">
          <div className="rounded-2xl bg-surface-2 p-3"><div className="text-xs text-muted">People so far</div><div className="font-display text-4xl">{st.people_so_far ?? 0}</div></div>
          <div className="rounded-2xl bg-surface-2 p-3"><div className="text-xs text-muted">In view now</div><div className="font-display text-4xl">{st.in_view ?? 0}</div></div>
        </div>
        <div className="mt-3"><div className="mb-1 flex justify-between text-xs"><span>{a?.job?.state === "error" ? "Failed" : ready ? "Done" : "Watching the video"}</span><span>{Math.round(frac * 100)}% · {Math.round(done)}/{Math.round(dur)} s</span></div>
          <div className="h-2 overflow-hidden rounded-full bg-line"><div className="h-full bg-lime transition-all" style={{ width: `${frac * 100}%` }} /></div></div>
        {a?.job?.error && <div className="mt-2"><ErrorBox message={a.job.error} /></div>}
        <div className="mt-auto flex flex-wrap gap-2 pt-4">
          <Link href={`/ask/?camera=${encodeURIComponent(cam.id)}&q=${encodeURIComponent("Is video mein kitne log aaye?")}`}
            className={`rounded-full px-4 py-2 text-sm font-medium ${done >= 60 || ready ? "bg-primary text-white" : "pointer-events-none bg-line text-muted"}`}>
            {ready ? "Ask about it" : `Ask now about the first ${Math.max(1, Math.floor(done / 60))} min`}
          </Link>
          <Link href={`/camera/?id=${encodeURIComponent(cam.id)}`} className="rounded-full border border-line px-4 py-2 text-sm">Draw zones</Link>
        </div>
      </div>
    </div>
  );
}

// ---- CCTV builder ---------------------------------------------------------------------------------------------------
function CctvTab() {
  const { refreshCameras } = useApp();
  const [presets, setPresets] = useState<{ id: string; label: string; note: string; path: string | null }[]>([]);
  const [f, setF] = useState({ name: "", location: "", brand: "hikvision", ip: "", port: "554", username: "admin", password: "", channel: "1", stream: "sub", rtsp_url: "" });
  const [probe, setProbe] = useState<ProbeResult | null>(null);
  const [busy, setBusy] = useState<"test" | "add" | "scan" | null>(null);
  const [cam, setCam] = useState<CameraOut | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [found, setFound] = useState<{ ip: string; maker: string | null }[] | null>(null);
  useEffect(() => { api2.presets().then(setPresets).catch(() => undefined); }, []);
  const custom = f.brand === "custom" || f.brand === "godrej";
  const body = () => ({ ...f, port: Number(f.port) || null, channel: Number(f.channel) || 1, rtsp_url: custom ? f.rtsp_url : null });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  const test = async () => {
    setBusy("test"); setErr(null); setProbe(null);
    try { setProbe(await api2.testCamera(body())); } catch (e) { setErr((e as Error).message); } finally { setBusy(null); }
  };
  const add = async () => {
    setBusy("add"); setErr(null);
    try { setCam(await api2.createRtsp(body())); refreshCameras(); } catch (e) { setErr((e as Error).message); } finally { setBusy(null); }
  };
  const scan = async () => {
    setBusy("scan");
    try { const r = await api2.discover(); setFound(r.cameras); if (r.error) setErr(r.error); } catch (e) { setErr((e as Error).message); } finally { setBusy(null); }
  };
  if (cam) return (
    <Card><div className="flex items-center gap-2 text-success"><CheckCircle2 size={18} /> {cam.name} added and starting.</div>
      <Link href={`/camera/?id=${encodeURIComponent(cam.id)}`} className="mt-3 inline-block rounded-full bg-primary px-4 py-2 text-sm text-white">Draw zones →</Link></Card>
  );
  return (
    <div className="grid gap-4 lg:grid-cols-[1.3fr_1fr]">
      <Card>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Name"><input value={f.name} onChange={set("name")} placeholder="Counter" className={inputCls} /></Field>
          <Field label="Location"><input value={f.location} onChange={set("location")} placeholder="Main bazaar shop" className={inputCls} /></Field>
          <Field label="Brand" hint={presets.find((p) => p.id === f.brand)?.note}>
            <select value={f.brand} onChange={set("brand")} className={inputCls}>{presets.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}</select>
          </Field>
          {custom ? (
            <Field label="RTSP / SRT / RTMP URL"><input value={f.rtsp_url} onChange={set("rtsp_url")} placeholder="rtsp://192.168.1.70:554/stream1" className={`${inputCls} font-mono`} /></Field>
          ) : (
            <Field label="IP address"><input value={f.ip} onChange={set("ip")} placeholder="192.168.1.64" className={`${inputCls} font-mono`} /></Field>
          )}
          <Field label="Username"><input value={f.username} onChange={set("username")} className={inputCls} autoComplete="off" /></Field>
          <Field label="Password" hint="Stored encrypted; never shown again"><input type="password" value={f.password} onChange={set("password")} className={inputCls} autoComplete="new-password" /></Field>
          {!custom && <>
            <Field label="Port"><input value={f.port} onChange={set("port")} className={inputCls} /></Field>
            <div className="grid grid-cols-2 gap-2">
              <Field label="Channel"><input value={f.channel} onChange={set("channel")} className={inputCls} /></Field>
              <Field label="Stream"><select value={f.stream} onChange={set("stream")} className={inputCls}><option value="sub">Sub (light)</option><option value="main">Main</option></select></Field>
            </div>
          </>}
        </div>
        {err && <div className="mt-3"><ErrorBox message={err} /></div>}
        <div className="mt-4 flex flex-wrap gap-2">
          <Btn kind="ghost" onClick={test} disabled={!!busy}><Plug size={15} /> {busy === "test" ? "Testing (8 s)…" : "Test connection"}</Btn>
          <Btn onClick={add} disabled={!!busy || !f.name.trim() || (custom ? !f.rtsp_url : !f.ip)}>{busy === "add" ? "Adding…" : "Add camera"}</Btn>
        </div>
        {probe && (
          <div className={`mt-4 flex gap-3 rounded-2xl p-3 ${probe.ok ? "bg-success/10" : "bg-danger/10"}`}>
            {probe.thumbnail && (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={probe.thumbnail} alt="camera snapshot" className="h-20 w-32 rounded-lg object-cover" />
            )}
            <div className="text-sm">
              {probe.ok ? <div className="flex items-center gap-1.5 font-medium text-success"><CheckCircle2 size={16} /> Reachable</div> : <div className="flex items-center gap-1.5 font-medium text-danger"><XCircle size={16} /> {probe.error}</div>}
              {probe.ok && <div className="text-xs text-muted">{probe.codec?.toUpperCase()} · {probe.width}×{probe.height}{probe.fps ? ` · ${probe.fps} fps` : ""}</div>}
              {probe.url_preview && <div className="mt-1 break-all font-mono text-[11px] text-muted">{probe.url_preview}</div>}
            </div>
          </div>
        )}
      </Card>
      <Card>
        <div className="mb-2 flex items-center gap-2 font-medium"><Radar size={17} className="text-primary" /> Find cameras on this network</div>
        <p className="text-xs text-muted">ONVIF discovery lists DVRs/IP cameras on the same Wi-Fi/LAN.</p>
        <Btn kind="soft" onClick={scan} disabled={!!busy} className="mt-3">{busy === "scan" ? "Scanning…" : "Scan network"}</Btn>
        {found && (found.length === 0 ? <div className="mt-3 text-sm text-muted">No ONVIF cameras answered.</div> : (
          <div className="mt-3 space-y-1">{found.map((c) => (
            <button key={c.ip} onClick={() => setF({ ...f, ip: c.ip, brand: (c.maker || "").toLowerCase().includes("dahua") ? "dahua" : f.brand })}
              className="flex w-full justify-between rounded-xl border border-line px-3 py-2 text-sm hover:border-primary"><span className="font-mono">{c.ip}</span><span className="text-xs text-muted">{c.maker || "camera"}</span></button>
          ))}</div>
        ))}
        <div className="mt-4 rounded-2xl bg-surface-2 p-3 text-xs text-muted">Tip: use the sub-stream (lower resolution). It is enough for Nazar and saves bandwidth. The DVR must be reachable from this computer.</div>
      </Card>
    </div>
  );
}

// ---- Excel / CSV import ----------------------------------------------------------------------------------------------
function ExcelTab() {
  const { refreshCameras } = useApp();
  const [res, setRes] = useState<{ import_id: string; rows: ProbeResult[]; working: number } | null>(null);
  const [busy, setBusy] = useState<"probe" | "add" | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [added, setAdded] = useState<number | null>(null);
  const tpl = (fmt: string) => `${API_BASE}/api/cameras/import/template.${fmt}?token=${encodeURIComponent(getToken() || "")}`;
  const upload = async (file: File | null) => {
    if (!file) return;
    setBusy("probe"); setErr(null); setRes(null); setAdded(null);
    try { setRes(await api2.importCameras(file)); } catch (e) { setErr((e as Error).message); } finally { setBusy(null); }
  };
  const commit = async () => {
    if (!res) return;
    setBusy("add");
    try {
      const r = await api2.importCommit(res.import_id, res.rows.filter((x) => x.ok && x.row).map((x) => x.row as number));
      setAdded(r.added.length);
      if (r.errors.length) setErr(r.errors.map((e) => `row ${e.row}: ${e.error}`).join("; "));
      refreshCameras();
    } catch (e) { setErr((e as Error).message); } finally { setBusy(null); }
  };
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2">
        <a href={tpl("xlsx")} className="inline-flex items-center gap-1.5 rounded-full border border-line px-4 py-2 text-sm hover:bg-surface-2"><Download size={15} /> Template .xlsx</a>
        <a href={tpl("csv")} className="inline-flex items-center gap-1.5 rounded-full border border-line px-4 py-2 text-sm hover:bg-surface-2"><Download size={15} /> Template .csv</a>
        <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-full bg-primary px-4 py-2 text-sm font-medium text-white">
          <FileSpreadsheet size={15} /> {busy === "probe" ? "Checking every camera…" : "Upload filled sheet"}
          <input type="file" accept=".xlsx,.csv" className="hidden" onChange={(e) => upload(e.target.files?.[0] || null)} />
        </label>
      </div>
      <p className="mt-2 text-xs text-muted">Columns: name, location, brand, ip, port, username, password, channel, stream, rtsp_url, zone_template, active. Every row is probed (4 at a time) before anything is added.</p>
      {busy === "probe" && <div className="mt-4"><Spinner label="Testing connections…" /></div>}
      {err && <div className="mt-3"><ErrorBox message={err} /></div>}
      {res && (
        <div className="mt-4">
          <div className="overflow-x-auto scroll-thin">
            <table className="w-full text-sm">
              <thead><tr className="text-left text-xs text-muted"><th className="py-1">Row</th><th>Name</th><th>Status</th><th>Stream</th></tr></thead>
              <tbody>{res.rows.map((r) => (
                <tr key={r.row} className="border-t border-line align-top">
                  <td className="py-2">{r.row}</td><td>{r.name || "—"}</td>
                  <td>{r.ok ? <span className="inline-flex items-center gap-1 text-success"><CheckCircle2 size={14} /> reachable</span> : <span className="inline-flex items-start gap-1 text-danger"><XCircle size={14} className="mt-0.5 shrink-0" /> {r.error}</span>}</td>
                  <td className="text-xs text-muted">{r.ok ? `${r.codec} ${r.width}×${r.height}` : r.url_preview || ""}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
          {added !== null ? <div className="mt-3 flex items-center gap-2 text-success"><CheckCircle2 size={16} /> Added {added} camera(s).</div> : (
            <Btn onClick={commit} disabled={!res.working || !!busy} className="mt-3">{busy === "add" ? "Adding…" : `Add all working (${res.working})`}</Btn>
          )}
        </div>
      )}
    </Card>
  );
}

// ---- phone -----------------------------------------------------------------------------------------------------------
function PhoneTab() {
  const { refreshCameras } = useApp();
  const [name, setName] = useState("Phone camera");
  const [setup, setSetup] = useState<{ srt: string; rtmp: string; source_url: string } | null>(null);
  const [cam, setCam] = useState<CameraOut | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const canvas = useRef<HTMLCanvasElement>(null);
  const id = slug(name) || "phone";
  useEffect(() => { api.phoneSetup(id).then(setSetup).catch((e) => setErr(e.message)); }, [id]);
  useEffect(() => { if (setup && canvas.current) QRCode.toCanvas(canvas.current, setup.srt, { width: 200, margin: 1 }).catch(() => undefined); }, [setup]);
  const create = async () => {
    if (!setup) return;
    setBusy(true); setErr(null);
    try { setCam(await api.createCamera({ id, name, source_url: setup.source_url, kind: "phone", start: true })); refreshCameras(); }
    catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <Card>
      <Field label="Camera name"><input value={name} onChange={(e) => setName(e.target.value)} disabled={!!cam} className={inputCls} /></Field>
      {setup && (
        <div className="mt-4 grid gap-4 sm:grid-cols-[200px_1fr]">
          <canvas ref={canvas} className="mx-auto rounded-xl bg-white" />
          <div className="text-sm">
            <ol className="list-decimal space-y-1.5 pl-5">
              <li>Install <b>Larix Broadcaster</b> (Android / iPhone, free).</li>
              <li>Settings → Connections → New connection. Scan the QR or paste:
                <code className="mt-1 block break-all rounded-lg bg-surface-2 p-2 text-xs">{setup.srt}</code>
                <span className="text-xs text-muted">or RTMP: <code className="break-all">{setup.rtmp}</code></span></li>
              <li>Video: 1280×720, 15 fps, 2–3 Mbps, H.264. Tap the red button.</li>
              <li>Press <b>Create &amp; start</b>.</li>
            </ol>
            <p className="mt-2 text-xs text-muted">The phone must reach this computer (same Wi-Fi; allow ports 8890/udp and 1935 in the firewall).</p>
          </div>
        </div>
      )}
      {err && <div className="mt-3"><ErrorBox message={err} /></div>}
      {cam ? (
        <div className="mt-4 flex items-center gap-2 text-sm text-success"><CheckCircle2 size={18} /> Created — it goes live as soon as the phone streams.
          <Link href={`/camera/?id=${encodeURIComponent(cam.id)}`} className="font-medium text-primary underline">Open camera →</Link></div>
      ) : <Btn onClick={create} disabled={busy || !setup} className="mt-4">{busy ? "Creating…" : "Create & start"}</Btn>}
    </Card>
  );
}
