"""Frame sources: files (time = start + PTS), live streams (wall clock) and files acting as live cameras."""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterator

import cv2
import numpy as np

log = logging.getLogger("nazar.edge.source")
LIVE_KINDS = {"rtsp", "srt", "rtmp", "phone"}


def infer_kind(url: str) -> str:
    u = url.lower()
    for k in ("rtsps", "rtsp", "srt", "rtmp"):
        if u.startswith(k + "://"):
            return "rtsp" if k == "rtsps" else k
    return "file"


@dataclass
class Frame:
    image: np.ndarray
    t: datetime  # UTC aware
    pos_s: float  # seconds into the source (files) or since start (live)
    index: int


class FrameSource:
    """Yields frames at most every `min_interval` seconds of source time (frames in between are grabbed, not decoded)."""

    def __init__(self, url: str, kind: str, *, start_time: datetime | None = None, simulate_live: bool = False,
                 loop: bool = False, pace: bool = False, min_interval: float = 0.1,
                 on_status: Callable[[bool, str], None] | None = None, max_width: int = 1920, upscale: float = 1.0,
                 stop: Callable[[], bool] | None = None):
        self.url = url
        self.kind = kind
        self.live = kind in LIVE_KINDS
        self.simulate_live = simulate_live
        self.loop = loop
        self.pace = pace or simulate_live
        self.min_interval = min_interval
        self.on_status = on_status or (lambda ok, note: None)
        self.max_width = max_width
        self.upscale = upscale
        self.stop = stop or (lambda: False)
        self.start_time = start_time
        self.duration_s: float | None = None
        self.fps_in = 0.0
        self.width = self.height = None
        if self.live and kind == "rtsp":
            os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

    def _open(self) -> cv2.VideoCapture:
        cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
        if self.live:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)
        return cap

    def _prep(self, img: np.ndarray) -> np.ndarray:
        h, w = img.shape[:2]
        scale = self.upscale if self.upscale and self.upscale != 1 else 1.0
        if w * scale > self.max_width:
            scale = self.max_width / w
        if scale != 1.0:
            img = cv2.resize(img, (int(round(w * scale)) // 2 * 2, int(round(h * scale)) // 2 * 2),
                             interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA)
        return img

    def frames(self) -> Iterator[Frame]:
        if self.live:
            yield from self._live_frames()
        else:
            while True:
                yield from self._file_frames()
                if not (self.loop and self.simulate_live) or self.stop():
                    return

    # ---- files ---------------------------------------------------------------
    def _file_frames(self) -> Iterator[Frame]:
        cap = self._open()
        if not cap.isOpened():
            raise RuntimeError(f"cannot open video {self.url}")
        declared_fps = cap.get(cv2.CAP_PROP_FPS) or 0
        n_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        if declared_fps > 0 and n_frames > 0:
            self.duration_s = n_frames / declared_fps
        self.fps_in = declared_fps
        if self.start_time is None and not self.simulate_live:
            mtime = datetime.fromtimestamp(Path(self.url).stat().st_mtime, tz=timezone.utc)
            self.start_time = mtime - timedelta(seconds=self.duration_s or 0)
        wall0 = time.monotonic()
        live_t0 = datetime.now(timezone.utc)
        idx = -1
        last_out = -1e9
        last_pos = -1.0
        warned = False
        try:
            while not self.stop():
                if not cap.grab():
                    break
                idx += 1
                pos_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
                if not pos_ms or pos_ms <= 0 or pos_ms / 1000.0 <= last_pos - 1.0:
                    if idx > 0:
                        if not warned:
                            log.warning("POS_MSEC invalid; using frame_index / fps")
                            warned = True
                        pos_ms = idx * 1000.0 / (declared_fps or 25.0)
                    else:
                        pos_ms = 0.0
                pos = pos_ms / 1000.0
                last_pos = pos
                if pos - last_out < self.min_interval - 1e-6:
                    continue
                ok, img = cap.retrieve()
                if not ok or img is None:
                    continue
                last_out = pos
                if self.pace:
                    lag = pos - (time.monotonic() - wall0)
                    if lag > 0:
                        time.sleep(min(lag, 1.0))
                if self.simulate_live:
                    t = datetime.now(timezone.utc)
                else:
                    t = self.start_time + timedelta(seconds=pos)
                img = self._prep(img)
                self.height, self.width = img.shape[:2]
                yield Frame(img, t, pos if not self.simulate_live else (t - live_t0).total_seconds(), idx)
        finally:
            cap.release()

    # ---- live --------------------------------------------------------------------
    def _live_frames(self) -> Iterator[Frame]:
        backoff = 1.0
        idx = 0
        t0 = time.monotonic()
        while not self.stop():
            cap = self._open()
            if not cap.isOpened():
                self.on_status(False, f"cannot connect; retry in {backoff:.0f}s")
                log.warning("cannot open %s; retry in %.0fs", self._safe_url(), backoff)
                self._sleep(backoff)
                backoff = min(30.0, backoff * 2)
                continue
            self.fps_in = cap.get(cv2.CAP_PROP_FPS) or 0
            log.info("connected to %s", self._safe_url())
            self.on_status(True, "connected")
            backoff = 1.0
            last_out = 0.0
            fails = 0
            while not self.stop():
                if not cap.grab():
                    fails += 1
                    if fails > 25:
                        break
                    time.sleep(0.04)
                    continue
                fails = 0
                now = time.monotonic()
                if now - last_out < self.min_interval - 1e-3:
                    continue
                ok, img = cap.retrieve()
                if not ok or img is None:
                    continue
                last_out = now
                idx += 1
                img = self._prep(img)
                self.height, self.width = img.shape[:2]
                yield Frame(img, datetime.now(timezone.utc), now - t0, idx)
            cap.release()
            if not self.stop():
                self.on_status(False, f"stream lost; reconnecting in {backoff:.0f}s")
                log.warning("stream lost; reconnecting in %.0fs", backoff)
                self._sleep(backoff)
                backoff = min(30.0, backoff * 2)

    def _sleep(self, s: float) -> None:
        end = time.monotonic() + s
        while time.monotonic() < end and not self.stop():
            time.sleep(0.2)

    def _safe_url(self) -> str:
        # hide credentials in rtsp://user:pass@host
        import re

        return re.sub(r"//[^/@]+@", "//***@", self.url)
