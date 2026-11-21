"""Per-track state: 5 Hz normalized paths, majority-vote class, crops; batch upserts; finalize."""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

import cv2
import numpy as np
from pgvector import Vector

from ..core import db, storage
from ..core.appearance import fingerprint
from ..core.timeutil import dt_to_ms, ms_to_dt
from .crops import CropKeeper, finish
from .detector import Det

log = logging.getLogger("nazar.edge.tracks")
MIN_OBS = 3
DB_BUFFER_S = 60.0


@dataclass
class TrackState:
    local_id: int
    path: list = field(default_factory=list)
    votes: Counter = field(default_factory=Counter)
    max_conf: float = 0.0
    last_seen: datetime | None = None
    first_seen: datetime | None = None
    crops: CropKeeper = field(default_factory=CropKeeper)
    dirty: bool = True
    db_id: int | None = None

    @property
    def cls(self) -> str:
        return self.votes.most_common(1)[0][0] if self.votes else "person"


UPSERT = """
INSERT INTO tracks(camera_id, run_id, local_id, cls, t_start, t_end, active, path, max_conf, job_id, updated_at)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s, now())
ON CONFLICT (camera_id, run_id, local_id) DO UPDATE SET
  path = EXCLUDED.path, t_end = EXCLUDED.t_end, cls = EXCLUDED.cls, max_conf = EXCLUDED.max_conf,
  active = EXCLUDED.active, updated_at = now()
RETURNING id
"""


class TrackManager:
    def __init__(self, camera_id: str, run_id: str, *, track_end_s: float, upsert_every_s: float,
                 job_id: int | None = None):
        self.camera_id = camera_id
        self.run_id = run_id
        self.track_end_s = track_end_s
        self.upsert_every_s = upsert_every_s
        self.job_id = job_id
        self.active: dict[int, TrackState] = {}
        self.pending_final: list[tuple[float, TrackState]] = []  # (monotonic time queued, state) when DB is down
        self._last_upsert: datetime | None = None
        self.stats = Counter()
        # ByteTrack may revive a lost id after we finalized it; give the revived track a new DB local_id
        self._generation: Counter = Counter()
        # finalize (crop encode + writes + DB) runs on a writer thread so crowded scenes don't stall decoding
        self._lock = threading.Lock()
        self._q: "queue.Queue[TrackState | None]" = queue.Queue()
        self._writer = threading.Thread(target=self._write_loop, name="track-writer", daemon=True)
        self._writer.start()

    # ---- updates -------------------------------------------------------------------
    def update(self, dets: list[Det], blurred: np.ndarray, t: datetime) -> None:
        t_ms = dt_to_ms(t)
        for d in dets:
            st = self.active.get(d.track_id)
            if st is None:
                gen = self._generation[d.track_id]
                st = TrackState(d.track_id + gen * 1_000_000, first_seen=t)
                self.active[d.track_id] = st
                self.stats["tracks_started"] += 1
            st.path.append([t_ms, round(d.box[0], 4), round(d.box[1], 4), round(d.box[2], 4), round(d.box[3], 4),
                            round(d.conf, 3)])
            st.votes[d.cls] += 1
            st.max_conf = max(st.max_conf, d.conf)
            st.last_seen = t
            st.dirty = True
            st.crops.offer(blurred, d.box, d.conf, t_ms)

    def step(self, t: datetime, force_upsert: bool = False) -> None:
        """Finalize stale tracks; periodically upsert active ones."""
        stale = [k for k, st in self.active.items() if (t - st.last_seen).total_seconds() >= self.track_end_s]
        for k in stale:
            self._generation[k] += 1
            self._finalize(self.active.pop(k))
        if force_upsert or self._last_upsert is None or (t - self._last_upsert).total_seconds() >= self.upsert_every_s:
            self._upsert_active()
            self._last_upsert = t
        self._retry_pending()

    def finalize_all(self) -> None:
        for k in list(self.active):
            self._finalize(self.active.pop(k))
        self._q.join()
        self._retry_pending(force=True)
        self._q.put(None)

    def _write_loop(self) -> None:
        while True:
            st = self._q.get()
            try:
                if st is None:
                    return
                if not self._write_final(st):
                    with self._lock:
                        self.pending_final.append((time.monotonic(), st))
            except Exception as e:
                log.error("track writer error: %s", e)
            finally:
                self._q.task_done()

    # ---- DB --------------------------------------------------------------------------
    def _row(self, st: TrackState, active: bool) -> tuple:
        return (self.camera_id, self.run_id, st.local_id, st.cls, ms_to_dt(st.path[0][0]), ms_to_dt(st.path[-1][0]),
                active, json.dumps(st.path, separators=(",", ":")), round(st.max_conf, 3), self.job_id)

    def _upsert_active(self) -> None:
        rows = [st for st in self.active.values() if st.dirty and len(st.path) >= MIN_OBS]
        if not rows:
            return
        try:
            with db.conn() as c:
                for st in rows:
                    st.db_id = c.execute(UPSERT, self._row(st, True)).fetchone()["id"]
                    st.dirty = False
            self.stats["upserts"] += len(rows)
        except Exception as e:
            log.warning("active upsert failed (will retry): %s", e)

    def _finalize(self, st: TrackState) -> None:
        if len(st.path) < MIN_OBS:
            self.stats["noise_dropped"] += 1
            if st.db_id is not None:
                try:
                    db.execute("DELETE FROM tracks WHERE id=%s", (st.db_id,))
                except Exception:
                    pass
            return
        self._q.put(st)

    def _write_final(self, st: TrackState) -> bool:
        try:
            with db.conn() as c:
                tid = c.execute(UPSERT, self._row(st, True)).fetchone()["id"]
            st.db_id = tid
            keys: list[str] = []
            app = None
            chosen = st.crops.choose()
            for n, cand in enumerate(chosen):
                img = finish(cand.img)
                ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
                if not ok:
                    continue
                key = f"crops/{self.camera_id}/{tid}_{n}.jpg"
                storage.put_bytes(buf.tobytes(), key)
                keys.append(key)
                if n == 0:
                    app = fingerprint(cand.img, st.cls)
            db.execute(
                "UPDATE tracks SET active=false, crop_keys=%s, appearance=%s, updated_at=now() WHERE id=%s",
                (keys, Vector(app.tolist()) if app is not None and np.any(app) else None, tid),
            )
            self.stats["tracks_final"] += 1
            return True
        except Exception as e:
            log.warning("finalize failed for local %d (buffering): %s", st.local_id, e)
            return False

    def _retry_pending(self, force: bool = False) -> None:
        with self._lock:
            if not self.pending_final:
                return
            items, self.pending_final = self.pending_final, []
        keep = []
        now = time.monotonic()
        for queued, st in items:
            if self._write_final(st):
                continue
            if now - queued > DB_BUFFER_S and not force:
                log.warning("dropping track local %d after %.0fs without DB", st.local_id, DB_BUFFER_S)
                self.stats["dropped_db_down"] += 1
                continue
            keep.append((queued, st))
        if not force:
            with self._lock:
                self.pending_final.extend(keep)
