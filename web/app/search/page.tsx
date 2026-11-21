"use client";

import { useState } from "react";
import { Camera, Search as SearchIcon, ShieldCheck, Sparkles } from "lucide-react";
import { api2 } from "@/lib/api2";
import type { Hit, Journey } from "@/lib/types2";
import { ClipPlayer, type ClipTarget } from "@/components/ClipPlayer";
import { HitCard, JourneyView, VideoModal } from "@/components/evidence";
import { PhotoSearchSheet } from "@/components/PhotoSearch";
import { Btn, Empty, ErrorBox, Page, Skeleton, inputCls } from "@/components/ui";
import { useApp } from "@/components/Providers";

const CLASSES = [["", "Anything"], ["person", "People"], ["any_bag", "Bags"], ["vehicle", "Vehicles"]];
const EXAMPLES = ["green backpack on a desk", "person in a white shirt", "red scooter", "laptop on a table", "crowd near the door"];

export default function SearchPage() {
  const { cameras } = useApp();
  const [text, setText] = useState("");
  const [cam, setCam] = useState("");
  const [cls, setCls] = useState("");
  const [hours, setHours] = useState("168");
  const [hits, setHits] = useState<Hit[] | null>(null);
  const [busy, setBusy] = useState<"search" | "verify" | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [photo, setPhoto] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);
  const [open, setOpen] = useState<ClipTarget | null>(null);
  const [journey, setJourney] = useState<Journey | null>(null);
  const [kf, setKf] = useState<{ url: string | null; poster?: string | null; camera_id: string; t: string } | null>(null);

  const run = async (q = text) => {
    if (!q.trim()) return;
    setBusy("search");
    setErr(null);
    setPreview(null);
    setJourney(null);
    try {
      const fd = new FormData();
      fd.append("text", q.trim());
      if (cam) fd.append("camera_ids", cam);
      if (cls) fd.append("cls", cls);
      fd.append("time_from", new Date(Date.now() - Number(hours) * 3600 * 1000).toISOString());
      fd.append("limit", "24");
      setHits((await api2.visualSearch(fd)).hits);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  };
  const verify = async () => {
    if (!hits?.length || !text.trim()) return;
    setBusy("verify");
    try {
      setHits((await api2.verify(text.trim(), hits.slice(0, 8))).hits.concat(hits.slice(8)));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  };
  const openKf = async (h: { camera_id: string; t: string }) => {
    const t = new Date(h.t).getTime();
    setKf({ url: null, camera_id: h.camera_id, t: h.t });
    try {
      const r = await api2.clipRange(h.camera_id, new Date(t - 4000).toISOString(), new Date(t + 6000).toISOString());
      setKf({ url: r.url, poster: r.poster_url, camera_id: h.camera_id, t: h.t });
    } catch (e) {
      setKf(null);
      setErr((e as Error).message);
    }
  };
  const showJourney = async (h: Hit) => {
    if (!h.track_id) return;
    try {
      setJourney(await api2.journey(h.track_id));
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  const probable = hits?.filter((h) => h.level === "probable").length || 0;

  return (
    <Page title="Search" subtitle="Find any moment by words or by photo — across every camera. Runs on the local visual index (₹0); AI only checks the top hits when you ask.">
      <div className="rounded-3xl border border-line bg-surface p-4">
        <form onSubmit={(e) => { e.preventDefault(); run(); }} className="flex flex-col gap-2 md:flex-row">
          <div className="flex flex-1 items-center gap-2 rounded-2xl border border-line bg-surface-2 px-3 focus-within:border-primary">
            <SearchIcon size={18} className="text-muted" />
            <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Describe it: “green backpack on a desk”, “laal scooter”…"
              aria-label="Search text" className="min-w-0 flex-1 bg-transparent py-3 outline-none" />
          </div>
          <div className="flex gap-2">
            <Btn type="submit" disabled={!!busy || !text.trim()}>{busy === "search" ? "Searching…" : "Search"}</Btn>
            <Btn kind="ghost" onClick={() => setPhoto(true)}><Camera size={16} /> Photo</Btn>
          </div>
        </form>
        <div className="mt-3 grid grid-cols-3 gap-2">
          <select value={cam} onChange={(e) => setCam(e.target.value)} className={inputCls} aria-label="Camera filter">
            <option value="">All cameras</option>
            {cameras.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <select value={cls} onChange={(e) => setCls(e.target.value)} className={inputCls} aria-label="Object type">
            {CLASSES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
          <select value={hours} onChange={(e) => setHours(e.target.value)} className={inputCls} aria-label="Time range">
            <option value="24">Last 24 h</option><option value="72">Last 3 days</option><option value="168">Last 7 days</option>
          </select>
        </div>
        {!hits && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {EXAMPLES.map((x) => <button key={x} onClick={() => { setText(x); run(x); }} className="rounded-full border border-line px-3 py-1 text-xs hover:border-primary hover:text-primary">{x}</button>)}
          </div>
        )}
      </div>

      {err && <div className="mt-4"><ErrorBox message={err} /></div>}
      {busy === "search" && <div className="mt-4 grid gap-3 md:grid-cols-2">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-28" />)}</div>}
      {hits && busy !== "search" && (
        <div className="mt-5">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            {preview && (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={preview} alt="" className="h-10 w-10 rounded-lg object-cover" />
            )}
            <div className="text-sm"><b>{hits.length}</b> similar moments{probable ? <> · <b>{probable}</b> verified by AI</> : null}</div>
            {text.trim() && hits.length > 0 && (
              <Btn kind="soft" onClick={verify} disabled={!!busy} className="ml-auto !py-1.5 text-xs">
                <Sparkles size={14} /> {busy === "verify" ? "Checking top 8…" : "Verify top 8 with AI"}
              </Btn>
            )}
          </div>
          {hits.length === 0 ? <Empty title="Nothing similar found">Try other words, a longer time range or another camera.</Empty> : (
            <div className="grid gap-3 md:grid-cols-2">
              {hits.map((h) => (
                <div key={`${h.kind}-${h.id}`} className="relative">
                  <HitCard hit={h} onOpen={setOpen} onKeyframe={openKf} />
                  {h.kind === "track" && <button onClick={() => showJourney(h)} className="absolute right-3 top-3 rounded-full bg-surface-2 px-2 py-0.5 text-[11px] text-primary">Journey</button>}
                </div>
              ))}
            </div>
          )}
          {journey && <div className="mt-4"><JourneyView journey={journey} onOpen={setOpen} /></div>}
        </div>
      )}
      <div className="mt-6 flex items-start gap-2 text-xs text-muted"><ShieldCheck size={14} className="mt-0.5 shrink-0" />
        Results start as Candidates (similar look). They become Probable only when an AI check of the blurred image agrees. Photo searches are logged with their purpose. No face recognition.</div>
      {photo && <PhotoSearchSheet cameraId={cam || null} onClose={() => setPhoto(false)} onResult={(r) => { setHits(r.hits); setPreview(r.preview); setText(r.text); setJourney(null); }} />}
      {open && <ClipPlayer target={open} onClose={() => setOpen(null)} />}
      {kf && <VideoModal title={`Scene · ${kf.camera_id}`} url={kf.url} poster={kf.poster} onClose={() => setKf(null)} />}
    </Page>
  );
}
