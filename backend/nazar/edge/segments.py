"""10-second face-blurred MP4 segments written by an ffmpeg process fed raw BGR frames on stdin."""
from __future__ import annotations

import logging
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import cv2
import numpy as np

from ..core import db, storage
from ..core.config import ffmpeg_bin
from ..core.timeutil import dt_to_ms, to_local

log = logging.getLogger("nazar.edge.segments")


class SegmentWriter:
    def __init__(self, camera_id: str, fps: float, seconds: float, width: int):
        self.camera_id = camera_id
        self.fps = fps
        self.seconds = seconds
        self.width = width
        self.proc: subprocess.Popen | None = None
        self.key: str | None = None
        self.t_first: datetime | None = None
        self.t_last: datetime | None = None
        self.size: tuple[int, int] | None = None
        self.frames = 0
        self.closed_count = 0
        self._last_img: np.ndarray | None = None

    def _open(self, t: datetime, w: int, h: int) -> None:
        lt = to_local(t)
        self.key = f"segments/{self.camera_id}/{lt:%Y%m%d}/{dt_to_ms(t)}.mp4"
        path = storage.local_path(self.key)
        path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
               "-s", f"{w}x{h}", "-r", f"{self.fps:g}", "-i", "-", "-an", "-c:v", "libx264", "-preset", "veryfast",
               "-crf", "28", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.t_first = t
        self.t_last = t
        self.size = (w, h)
        self.frames = 0

    def _resize(self, img: np.ndarray) -> np.ndarray:
        h, w = img.shape[:2]
        if w != self.width:
            nh = int(round(h * self.width / w / 2)) * 2
            img = cv2.resize(img, (self.width, nh), interpolation=cv2.INTER_AREA)
        return img

    def write(self, blurred: np.ndarray, t: datetime) -> None:
        img = self._resize(blurred)
        h, w = img.shape[:2]
        if self.proc is None or (t - self.t_first).total_seconds() >= self.seconds or self.size != (w, h):
            if self.proc is not None:
                self.close()
            self._open(t, w, h)
        else:
            # keep the timeline exact: duplicate the previous frame to fill gaps in the input
            step = 1.0 / self.fps
            expected = self.t_first + timedelta(seconds=self.frames * step)
            gap = (t - expected).total_seconds()
            if gap > 1.5 * step and self._last_img is not None:
                for _ in range(min(int(gap / step), int(self.fps * self.seconds))):
                    self._push(self._last_img)
        self._push(img)
        self.t_last = t

    def _push(self, img: np.ndarray) -> None:
        try:
            self.proc.stdin.write(img.tobytes())  # type: ignore[union-attr]
            self.frames += 1
            self._last_img = img
        except (BrokenPipeError, OSError) as e:
            err = self.proc.stderr.read().decode(errors="ignore")[:300] if self.proc and self.proc.stderr else ""
            log.error("segment ffmpeg died: %s %s", e, err)
            self.proc = None

    def close(self) -> None:
        if self.proc is None:
            return
        proc, key, t0, frames, size = self.proc, self.key, self.t_first, self.frames, self.size
        self.proc = None
        try:
            proc.stdin.close()  # type: ignore[union-attr]
            proc.wait(timeout=60)
        except Exception as e:
            log.error("segment close failed: %s", e)
            proc.kill()
            return
        if proc.returncode != 0 or frames == 0:
            log.error("segment %s failed (rc=%s)", key, proc.returncode)
            return
        t_end = t0 + timedelta(seconds=frames / self.fps)
        try:
            db.execute("INSERT INTO segments(camera_id, t_start, t_end, key, fps, width, height) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                       (self.camera_id, t0, t_end, key, self.fps, size[0], size[1]))
            self.closed_count += 1
        except Exception as e:
            log.error("could not record segment %s: %s", key, e)
        self._last_img = None
