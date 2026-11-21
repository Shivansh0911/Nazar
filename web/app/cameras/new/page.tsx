"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import QRCode from "qrcode";
import { CheckCircle2, Cctv, Smartphone, Upload } from "lucide-react";
import { api, uploadVideo } from "@/lib/api";
import type { CameraOut, Progress } from "@/lib/types";
import { Card, ErrorBox, Page, Spinner } from "@/components/ui";
import { useApp } from "@/components/Providers";

type Tab = "upload" | "phone" | "rtsp";

export default function NewCameraPage() {
  const [tab, setTab] = useState<Tab>("upload");
  const tabs: { id: Tab; label: string; icon: typeof Upload }[] = [
    { id: "upload", label: "Upload", icon: Upload },
    { id: "phone", label: "Phone", icon: Smartphone },
    { id: "rtsp", label: "CCTV / RTSP", icon: Cctv },
  ];
  return (
    <Page>
      <h1 className="mb-3 text-xl font-semibold">Add camera</h1>
      <div className="mb-4 flex gap-1 overflow-x-auto rounded-full bg-surface p-1 shadow-sm scroll-thin">
        {tabs.map(({ id, label, icon: Icon }) => (
          <button key={id} onClick={() => setTab(id)}
            className={`flex flex-1 items-center justify-center gap-1.5 whitespace-nowrap rounded-full px-3 py-2 text-sm ${tab === id ? "bg-primary text-white" : "text-muted"}`}>
            <Icon size={15} /> {label}
          </button>
        ))}
      </div>
      {tab === "upload" && <UploadTab />}
      {tab === "phone" && <PhoneTab />}
      {tab === "rtsp" && <RtspTab />}
    </Page>
  );
}

function UploadTab() {
  const { refreshCameras } = useApp();
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [start, setStart] = useState("");
  const [up, setUp] = useState<number | null>(null);
  const [cam, setCam] = useState<CameraOut | null>(null);
  const [prog, setProg] = useState<Progress | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);

  useEffect(() => {
    if (!cam) return;
    let alive = true;
    const tick = async () => {
      try {
        const p = await api.progress(cam.id);
        if (!alive) return;
        setProg(p);
        if (p.state === "ready" || p.state === "error") {
          refreshCameras();
          return;
        }
      } catch {
        /* keep polling */
      }
      if (alive) setTimeout(tick, 2000);
    };
    tick();
    return () => {
      alive = false;
    };
  }, [cam, refreshCameras]);

  const pick = (f: File | null) => {
    setFile(f);
    if (f && !name) setName(f.name.replace(/\.[^.]+$/, "").slice(0, 40));
  };

  const submit = async () => {
    if (!file || !name.trim()) return;
    setErr(null);
    setUp(0);
    try {
      const r = await uploadVideo(file, name.trim(), start || null, setUp);
      setCam(r.camera);
    } catch (e) {
      setErr((e as Error).message);
      setUp(null);
    }
  };

  if (cam) {
    const frac = prog && prog.duration_seconds ? prog.processed_seconds / prog.duration_seconds : 0;
    return (
      <Card>
        <div className="font-medium">{cam.name}</div>
        {!prog || prog.state === "queued" || prog.state === "processing" ? (
          <div className="mt-3">
            <div className="mb-1 flex justify-between text-sm"><span>Watching the video…</span><span>{Math.round(frac * 100)}%</span></div>
            <div className="h-2 overflow-hidden rounded-full bg-line"><div className="h-full bg-primary transition-all" style={{ width: `${Math.round(frac * 100)}%` }} /></div>
            <div className="mt-2 text-xs text-muted">{prog?.tracks ?? 0} people/vehicles tracked so far</div>
          </div>
        ) : prog.state === "enriching" ? (
          <div className="mt-3"><Spinner label={`Describing ${prog.tracks} tracks (${prog.enriched} done)…`} /></div>
        ) : prog.state === "error" ? (
          <div className="mt-3"><ErrorBox message={prog.error || "Processing failed"} /></div>
        ) : (
          <div className="mt-3">
            <div className="flex items-center gap-2 text-emerald-600"><CheckCircle2 size={18} /> Ready — {prog.tracks} tracks</div>
            {prog.note && <div className="mt-1 text-xs text-muted">{prog.note}</div>}
            <Link href={`/?camera=${encodeURIComponent(cam.id)}`} className="mt-3 inline-block rounded-full bg-primary px-4 py-2 text-sm font-semibold text-white">
              Ready — ask about it
            </Link>
          </div>
        )}
      </Card>
    );
  }

  return (
    <Card>
      <label
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files?.[0] || null); }}
        className={`flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed p-8 text-center ${drag ? "border-primary bg-primary-soft" : "border-line"}`}
      >
        <Upload className="text-primary" />
        <div className="mt-2 text-sm font-medium">{file ? file.name : "Drop a video here or tap to choose"}</div>
        <div className="text-xs text-muted">Any phone or CCTV export · up to 60 min / 2 GB · faces are blurred</div>
        <input type="file" accept="video/*" className="hidden" onChange={(e) => pick(e.target.files?.[0] || null)} />
      </label>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <label className="text-sm">Camera name
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Shop entrance"
            className="mt-1 w-full rounded-xl border border-line bg-background px-3 py-2 outline-none focus:border-primary" />
        </label>
        <label className="text-sm">Recorded at (optional)
          <input type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)}
            className="mt-1 w-full rounded-xl border border-line bg-background px-3 py-2 outline-none focus:border-primary" />
        </label>
      </div>
      {up !== null && (
        <div className="mt-3">
          <div className="mb-1 text-sm">Uploading… {Math.round(up * 100)}%</div>
          <div className="h-2 overflow-hidden rounded-full bg-line"><div className="h-full bg-primary" style={{ width: `${Math.round(up * 100)}%` }} /></div>
        </div>
      )}
      {err && <div className="mt-3"><ErrorBox message={err} /></div>}
      <button onClick={submit} disabled={!file || !name.trim() || up !== null}
        className="mt-4 rounded-full bg-primary px-5 py-2 text-sm font-semibold text-white disabled:opacity-50">
        Upload and process
      </button>
    </Card>
  );
}

function slug(s: string) {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40);
}

function PhoneTab() {
  const { refreshCameras } = useApp();
  const [name, setName] = useState("Phone camera");
  const [setup, setSetup] = useState<{ srt: string; rtmp: string; source_url: string } | null>(null);
  const [cam, setCam] = useState<CameraOut | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const canvas = useRef<HTMLCanvasElement>(null);
  const id = slug(name) || "phone";

  useEffect(() => {
    api.phoneSetup(id).then(setSetup).catch((e) => setErr(e.message));
  }, [id]);

  useEffect(() => {
    if (setup && canvas.current) QRCode.toCanvas(canvas.current, setup.srt, { width: 200, margin: 1 }).catch(() => undefined);
  }, [setup]);

  const create = async () => {
    if (!setup) return;
    setBusy(true);
    setErr(null);
    try {
      const c = await api.createCamera({ id, name, source_url: setup.source_url, kind: "phone", start: true });
      setCam(c);
      refreshCameras();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <label className="text-sm">Camera name
        <input value={name} onChange={(e) => setName(e.target.value)} disabled={!!cam}
          className="mt-1 w-full rounded-xl border border-line bg-background px-3 py-2 outline-none focus:border-primary" />
      </label>
      {setup && (
        <div className="mt-4 grid gap-4 sm:grid-cols-[200px,1fr]">
          <canvas ref={canvas} className="mx-auto rounded-xl bg-white" />
          <div className="text-sm">
            <ol className="list-decimal space-y-1.5 pl-5">
              <li>Install <b>Larix Broadcaster</b> (Android / iPhone, free).</li>
              <li>Settings → Connections → New connection. Scan the QR or paste:
                <code className="mt-1 block break-all rounded-lg bg-background p-2 text-xs">{setup.srt}</code>
                <span className="text-xs text-muted">or RTMP: <code className="break-all">{setup.rtmp}</code></span>
              </li>
              <li>Settings → Video: 1280×720, 15 fps, 2–3 Mbps, H.264.</li>
              <li>Mount the phone where it can see the area, tap the red record button.</li>
              <li>Press <b>Create &amp; start</b> below. Nazar reads <code className="text-xs">{setup.source_url}</code>.</li>
            </ol>
            <p className="mt-2 text-xs text-muted">Venue Wi-Fi may block phone-to-laptop traffic; streaming to the cloud server&apos;s public IP avoids that. On a laptop, allow ports 8890/udp and 1935 in Windows Firewall.</p>
          </div>
        </div>
      )}
      {err && <div className="mt-3"><ErrorBox message={err} /></div>}
      {cam ? (
        <div className="mt-4 flex items-center gap-2 text-sm text-emerald-600">
          <CheckCircle2 size={18} /> Created. The edge starts reading as soon as the phone streams.
          <Link href={`/camera/?id=${encodeURIComponent(cam.id)}`} className="font-medium text-primary underline">Open camera →</Link>
        </div>
      ) : (
        <button onClick={create} disabled={busy || !setup} className="mt-4 rounded-full bg-primary px-5 py-2 text-sm font-semibold text-white disabled:opacity-50">
          {busy ? "Creating…" : "Create & start"}
        </button>
      )}
    </Card>
  );
}

function RtspTab() {
  const { refreshCameras } = useApp();
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [cam, setCam] = useState<CameraOut | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const create = async () => {
    setBusy(true);
    setErr(null);
    try {
      setCam(await api.createCamera({ name: name.trim(), source_url: url.trim(), start: true }));
      refreshCameras();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card>
      <div className="grid gap-3">
        <label className="text-sm">Camera name
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Counter DVR ch1"
            className="mt-1 w-full rounded-xl border border-line bg-background px-3 py-2 outline-none focus:border-primary" />
        </label>
        <label className="text-sm">Stream URL
          <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="rtsp://user:pass@192.168.1.64:554/Streaming/Channels/102"
            className="mt-1 w-full rounded-xl border border-line bg-background px-3 py-2 font-mono text-sm outline-none focus:border-primary" />
        </label>
        <div className="rounded-xl bg-background p-3 text-xs text-muted">
          Common DVR formats — Hikvision: <code>rtsp://user:pass@IP:554/Streaming/Channels/102</code> · CP Plus / Dahua:{" "}
          <code>rtsp://user:pass@IP:554/cam/realmonitor?channel=1&amp;subtype=1</code> · also <code>srt://</code> and <code>rtmp://</code>.
          Use the sub-stream (lower resolution) — it is enough and saves CPU.
        </div>
      </div>
      {err && <div className="mt-3"><ErrorBox message={err} /></div>}
      {cam ? (
        <div className="mt-4 flex items-center gap-2 text-sm text-emerald-600">
          <CheckCircle2 size={18} /> Started.
          <Link href={`/camera/?id=${encodeURIComponent(cam.id)}`} className="font-medium text-primary underline">Draw zones →</Link>
        </div>
      ) : (
        <button onClick={create} disabled={busy || !name.trim() || !url.trim()}
          className="mt-4 rounded-full bg-primary px-5 py-2 text-sm font-semibold text-white disabled:opacity-50">
          {busy ? "Starting…" : "Start"}
        </button>
      )}
    </Card>
  );
}
