"""Live view publisher (W10): the FACE-BLURRED frame with the tracker overlay (boxes, ids, zone lines, counts and a
wall-clock stamp) is pushed to MediaMTX as <camera>_view over RTSP; browsers play it over WebRTC (WHEP).
H.264 baseline, zerolatency; NVENC when available, else libx264 ultrafast. Restarts itself if ffmpeg dies."""
from __future__ import annotations

import logging
import subprocess
import time
from datetime import datetime

import cv2
import numpy as np

from ..core.config import ffmpeg_bin, get_settings
from ..core.timeutil import to_local

log = logging.getLogger("nazar.edge.view")
WIDTH = 854
COLORS = {"person": (60, 220, 60)}


def annotate(img: np.ndarray, dets, zones: list[dict], width: int = WIDTH, stamp: datetime | None = None,
             counts: dict | None = None) -> np.ndarray:
    h, w = img.shape[:2]
    if w != width:
        img = cv2.resize(img, (width, int(round(h * width / w / 2)) * 2), interpolation=cv2.INTER_AREA)
    else:
        img = img.copy()
    h, w = img.shape[:2]
    for z in zones or []:
        pts = np.array([[int(x * w), int(y * h)] for x, y in z.get("polygon", [])], np.int32)
        if len(pts) >= 2:
            cv2.polylines(img, [pts], z.get("type") != "line", (0, 200, 255), 2)
    for d in dets:
        x1, y1, x2, y2 = int(d.box[0] * w), int(d.box[1] * h), int(d.box[2] * w), int(d.box[3] * h)
        c = COLORS.get(d.cls, (60, 245, 212) if d.cls.startswith("custom:") else (255, 140, 0))
        cv2.rectangle(img, (x1, y1), (x2, y2), c, 2)
        label = f"{d.cls.replace('custom:', '')} {d.track_id % 1_000_000}"
        cv2.putText(img, label, (x1, max(12, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, c, 1, cv2.LINE_AA)
    if stamp is not None:
        txt = to_local(stamp).strftime("%H:%M:%S.") + f"{to_local(stamp).microsecond // 1000:03d}"
        cv2.rectangle(img, (w - 150, 6), (w - 6, 30), (10, 15, 31), -1)
        cv2.putText(img, txt, (w - 144, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
    if counts:
        txt = "  ".join(f"{k}: {v}" for k, v in counts.items())
        cv2.rectangle(img, (6, 6), (14 + 9 * len(txt), 30), (10, 15, 31), -1)
        cv2.putText(img, txt, (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (212, 245, 60), 1, cv2.LINE_AA)
    return img


def _nvenc_ok() -> bool:
    try:
        r = subprocess.run([ffmpeg_bin(), "-hide_banner", "-f", "lavfi", "-i", "color=c=black:s=256x144:d=0.2", "-c:v",
                            "h264_nvenc", "-f", "null", "-"], capture_output=True, timeout=20)
        return r.returncode == 0
    except Exception:
        return False


class ViewPublisher:
    def __init__(self, camera_id: str, fps: float = 10.0):
        s = get_settings()
        self.url = f"rtsp://{s.MEDIAMTX_HOST}:8554/{camera_id}_view"
        self.fps = fps
        self.proc: subprocess.Popen | None = None
        self.size: tuple[int, int] | None = None
        self.last = 0.0
        self.next_try = 0.0
        self.nvenc = _nvenc_ok()
        self.enabled = True

    def _start(self, w: int, h: int) -> None:
        enc = (["-c:v", "h264_nvenc", "-preset", "p1", "-tune", "ull", "-profile:v", "baseline", "-zerolatency", "1"]
               if self.nvenc else ["-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-profile:v", "baseline"])
        cmd = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}",
               "-r", f"{self.fps:g}", "-i", "-", "-an", *enc, "-pix_fmt", "yuv420p", "-g", str(int(self.fps * 2)),
               "-bf", "0", "-f", "rtsp", "-rtsp_transport", "tcp", self.url]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.size = (w, h)
        log.info("publishing blurred live view to %s (%s)", self.url, "nvenc" if self.nvenc else "x264")

    def write(self, img: np.ndarray) -> None:
        if not self.enabled:
            return
        now = time.monotonic()
        if now - self.last < 1.0 / self.fps - 1e-3:
            return
        self.last = now
        h, w = img.shape[:2]
        if self.proc is None or self.proc.poll() is not None or self.size != (w, h):
            if now < self.next_try:
                return
            self.close()
            try:
                self._start(w, h)
            except Exception as e:
                log.warning("view publisher failed to start: %s", e)
                self.next_try = now + 10
                return
        try:
            self.proc.stdin.write(img.tobytes())  # type: ignore[union-attr]
        except (BrokenPipeError, OSError):
            err = self.proc.stderr.read(300).decode(errors="ignore") if self.proc and self.proc.stderr else ""
            log.warning("view publisher died (%s); retry in 5 s", err.strip()[:200])
            self.close()
            self.next_try = now + 5

    def close(self) -> None:
        if self.proc is not None:
            try:
                self.proc.stdin.close()  # type: ignore[union-attr]
                self.proc.wait(timeout=5)
            except Exception:
                self.proc.kill()
            self.proc = None
