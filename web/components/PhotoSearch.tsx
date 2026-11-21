"use client";

import { useRef, useState } from "react";
import { Camera, ImagePlus, ShieldCheck, X } from "lucide-react";
import { api2 } from "@/lib/api2";
import type { Hit } from "@/lib/types2";
import { Btn, ErrorBox, Spinner, inputCls } from "./ui";

/** Search by photo: pick or take a photo of a bag / jacket / vehicle, optionally draw a box around it. */
export function PhotoSearchSheet({ cameraId, onResult, onClose }: {
  cameraId?: string | null; onResult: (r: { hits: Hit[]; preview: string; text: string }) => void; onClose: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [purpose, setPurpose] = useState("");
  const [text, setText] = useState("");
  const [box, setBox] = useState<[number, number, number, number] | null>(null);
  const [drag, setDrag] = useState<[number, number] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const imgRef = useRef<HTMLDivElement>(null);

  const pick = (f: File | null) => {
    setFile(f);
    setBox(null);
    setErr(null);
    setPreview(f ? URL.createObjectURL(f) : null);
  };
  const norm = (e: React.PointerEvent): [number, number] => {
    const r = imgRef.current!.getBoundingClientRect();
    return [Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (e.clientY - r.top) / r.height))];
  };
  const go = async () => {
    if (!file) return;
    setBusy(true);
    setErr(null);
    try {
      const fd = new FormData();
      fd.append("image", file);
      if (purpose.trim()) fd.append("purpose", purpose.trim());
      if (text.trim()) {
        fd.append("text", text.trim());
        fd.append("verify", "true");
      }
      if (box) fd.append("box", JSON.stringify(box));
      if (cameraId) fd.append("camera_ids", cameraId);
      const r = await api2.visualSearch(fd);
      onResult({ hits: r.hits, preview: preview || "", text: text.trim() });
      onClose();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 sm:items-center" onClick={onClose}>
      <div className="max-h-dvh w-full max-w-lg overflow-y-auto rounded-t-3xl border border-line bg-surface p-4 sm:rounded-3xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center gap-2">
          <Camera size={18} className="text-primary" />
          <div className="font-semibold">Search by photo</div>
          <button onClick={onClose} className="ml-auto rounded-full p-2 hover:bg-surface-2" aria-label="Close"><X size={18} /></button>
        </div>
        {!preview ? (
          <label className="flex cursor-pointer flex-col items-center gap-2 rounded-2xl border-2 border-dashed border-line p-8 text-center text-sm text-muted hover:border-primary">
            <ImagePlus size={28} className="text-primary" />
            Choose or take a photo of a bag, jacket, helmet or vehicle
            <input type="file" accept="image/*" capture="environment" className="hidden" onChange={(e) => pick(e.target.files?.[0] || null)} />
          </label>
        ) : (
          <div>
            <div ref={imgRef} className="relative touch-none select-none overflow-hidden rounded-2xl bg-black"
              onPointerDown={(e) => { const p = norm(e); setDrag(p); setBox([p[0], p[1], p[0], p[1]]); }}
              onPointerMove={(e) => { if (!drag) return; const p = norm(e); setBox([Math.min(drag[0], p[0]), Math.min(drag[1], p[1]), Math.max(drag[0], p[0]), Math.max(drag[1], p[1])]); }}
              onPointerUp={() => { setDrag(null); if (box && (box[2] - box[0] < 0.03 || box[3] - box[1] < 0.03)) setBox(null); }}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={preview} alt="your photo" className="max-h-72 w-full object-contain" draggable={false} />
              {box && (
                <div className="pointer-events-none absolute border-2 border-lime bg-lime/10"
                  style={{ left: `${box[0] * 100}%`, top: `${box[1] * 100}%`, width: `${(box[2] - box[0]) * 100}%`, height: `${(box[3] - box[1]) * 100}%` }} />
              )}
            </div>
            <div className="mt-1 flex text-[11px] text-muted">
              <span>{box ? "Searching only inside the box" : "Optional: drag a box around the object"}</span>
              <button className="ml-auto text-primary" onClick={() => pick(null)}>Change photo</button>
            </div>
          </div>
        )}
        <div className="mt-3 space-y-2">
          <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Describe it (optional, lets AI verify): e.g. green backpack" className={inputCls} />
          <input value={purpose} onChange={(e) => setPurpose(e.target.value)} placeholder="Purpose (kept in the audit log): e.g. lost bag at gate" className={inputCls} />
        </div>
        <div className="mt-2 flex items-start gap-1.5 text-[11px] text-muted">
          <ShieldCheck size={13} className="mt-0.5 shrink-0" /> Faces in your photo are blurred before searching. Nazar never searches by face — it compares clothes, objects and vehicles.
        </div>
        {err && <div className="mt-3"><ErrorBox message={err} /></div>}
        <Btn onClick={go} disabled={!file || busy} className="mt-4 w-full">{busy ? <Spinner label="Searching every camera…" /> : "Find every sighting"}</Btn>
      </div>
    </div>
  );
}
