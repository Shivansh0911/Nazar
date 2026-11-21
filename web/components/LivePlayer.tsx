"use client";

import { useEffect, useRef, useState } from "react";
import { API_BASE, mjpegUrl, snapshotUrl } from "@/lib/api";

// MediaMTX WebRTC: local dev = same host as the API on :8889; behind Caddy (no port) = <api>/webrtc
export const WEBRTC_BASE = (process.env.NEXT_PUBLIC_WEBRTC_URL ||
  (/:\d+$/.test(API_BASE) ? API_BASE.replace(/:\d+$/, ":8889") : `${API_BASE}/webrtc`)).replace(/\/$/, "");

/** WHEP (no SDK): a recv-only peer connection to MediaMTX for the face-blurred <camera>_view stream. */
async function playWhep(video: HTMLVideoElement, url: string): Promise<RTCPeerConnection> {
  const pc = new RTCPeerConnection();
  pc.addTransceiver("video", { direction: "recvonly" });
  pc.ontrack = (e) => {
    video.srcObject = e.streams[0] ?? new MediaStream([e.track]);
  };
  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);
  await new Promise<void>((resolve) => {  // non-trickle: wait for ICE gathering (max 1.5 s)
    if (pc.iceGatheringState === "complete") return resolve();
    const t = setTimeout(resolve, 1500);
    pc.addEventListener("icegatheringstatechange", () => {
      if (pc.iceGatheringState === "complete") {
        clearTimeout(t);
        resolve();
      }
    });
  });
  const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/sdp" }, body: pc.localDescription?.sdp });
  if (!res.ok) {
    pc.close();
    throw new Error(`WHEP ${res.status}`);
  }
  await pc.setRemoteDescription({ type: "answer", sdp: await res.text() });
  return pc;
}

/** Low-latency live view (WebRTC) with the tracker overlay burned in; falls back to the blurred MJPEG overlay. */
export function LivePlayer({ cameraId, live, className = "" }: { cameraId: string; live: boolean; className?: string }) {
  const video = useRef<HTMLVideoElement>(null);
  const [mode, setMode] = useState<"webrtc" | "mjpeg" | "connecting">("connecting");

  useEffect(() => {
    if (!live) return;
    let pc: RTCPeerConnection | null = null;
    let cancelled = false;
    setMode("connecting");
    const v = video.current;
    if (!v || typeof RTCPeerConnection === "undefined") {
      setMode("mjpeg");
      return;
    }
    const fallback = setTimeout(() => !cancelled && setMode((m) => (m === "connecting" ? "mjpeg" : m)), 6000);
    playWhep(v, `${WEBRTC_BASE}/${encodeURIComponent(cameraId)}_view/whep`)
      .then((p) => {
        pc = p;
        if (cancelled) return p.close();
        p.onconnectionstatechange = () => {
          if (p.connectionState === "failed" || p.connectionState === "disconnected") setMode("mjpeg");
        };
        v.onplaying = () => !cancelled && setMode("webrtc");
      })
      .catch(() => !cancelled && setMode("mjpeg"));
    return () => {
      cancelled = true;
      clearTimeout(fallback);
      pc?.close();
    };
  }, [cameraId, live]);

  return (
    <div className={`relative h-full w-full ${className}`}>
      <video ref={video} autoPlay muted playsInline className={`absolute inset-0 h-full w-full object-contain ${mode === "webrtc" ? "" : "invisible"}`} />
      {mode !== "webrtc" && (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={live ? `${mjpegUrl(cameraId)}&overlay=1` : snapshotUrl(cameraId)} alt="live view (faces blurred)" className="absolute inset-0 h-full w-full object-contain" />
      )}
      {live && (
        <span className="absolute bottom-2 right-2 rounded-full bg-black/60 px-2 py-0.5 text-[10px] font-medium text-white">
          {mode === "webrtc" ? "WebRTC · < 1 s" : mode === "connecting" ? "connecting…" : "MJPEG"}
        </span>
      )}
    </div>
  );
}
