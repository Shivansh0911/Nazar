"""camera_status heartbeat every 5 s (+ job progress when processing an upload/demo file)."""
from __future__ import annotations

import logging
import time
from datetime import datetime

from ..core import db

log = logging.getLogger("nazar.edge.heartbeat")


class Heartbeat:
    def __init__(self, camera_id: str, job_id: int | None = None, every: float = 5.0):
        self.camera_id = camera_id
        self.job_id = job_id
        self.every = every
        self._last = 0.0
        self._frames = 0
        self._dets = 0
        self._t0 = time.monotonic()

    def count(self, frames: int = 0, dets: int = 0) -> None:
        self._frames += frames
        self._dets += dets

    def tick(self, t: datetime, ok: bool, active_tracks: int, note: str | None = None, force: bool = False,
             processed_s: float | None = None, duration_s: float | None = None) -> None:
        now = time.monotonic()
        if not force and now - self._last < self.every:
            return
        span = max(1e-3, now - (self._last or self._t0))
        fps_in, fps_proc = self._frames / span, self._dets / span
        self._frames = self._dets = 0
        self._last = now
        try:
            db.execute("INSERT INTO camera_status(camera_id, t, ok, fps_in, fps_proc, active_tracks, note) "
                       "VALUES (%s,%s,%s,%s,%s,%s,%s)", (self.camera_id, t, ok, fps_in, fps_proc, active_tracks, note))
            if self.job_id is not None and processed_s is not None:
                db.execute("UPDATE jobs SET processed_s=%s, duration_s=COALESCE(%s, duration_s), state='processing', "
                           "updated_at=now() WHERE id=%s AND state IN ('queued','processing')",
                           (processed_s, duration_s, self.job_id))
        except Exception as e:
            log.warning("heartbeat failed: %s", e)
