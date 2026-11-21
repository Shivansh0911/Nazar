"""Eventize loop: track paths -> zone events (the eventizer is the single source of zone truth)."""
from __future__ import annotations

import hashlib
import json
import logging
import queue
import threading
from datetime import datetime, timedelta, timezone

from psycopg.types.json import Jsonb

from ..core import db
from ..core.eventizer import eventize
from ..core.timeutil import ms_to_dt

log = logging.getLogger("nazar.eventize")
OVERLAP = timedelta(seconds=3)
BATCH = 300


def zones_hash(zones) -> str:
    return hashlib.sha1(json.dumps(zones or [], sort_keys=True).encode()).hexdigest()


def write_events(c, track: dict, zones: list[dict]) -> list[str]:
    events, zone_path = eventize(track["path"] or [], track["cls"], zones)
    c.execute("DELETE FROM events WHERE track_id=%s", (track["id"],))
    if events:
        with c.cursor() as cur:
            cur.executemany(
                "INSERT INTO events(camera_id, track_id, type, zone, t, meta) VALUES (%s,%s,%s,%s,%s,%s)",
                [(track["camera_id"], track["id"], e.type, e.zone, ms_to_dt(e.t_ms), Jsonb(e.meta)) for e in events],
            )
    c.execute("UPDATE tracks SET zone_path=%s WHERE id=%s", (zone_path, track["id"]))
    return zone_path


class Eventizer:
    def __init__(self, out_q: "queue.Queue[dict] | None" = None):
        self.out_q = out_q
        self.cursor: datetime | None = None
        self.seen: dict[int, datetime] = {}
        self.zone_hashes: dict[str, str] = {}
        self.zones: dict[str, list] = {}
        self.processed = 0

    def _refresh_zones(self) -> list[str]:
        changed = []
        for r in db.fetch_all("SELECT id, zones FROM cameras"):
            h = zones_hash(r["zones"])
            if r["id"] in self.zone_hashes and self.zone_hashes[r["id"]] != h:
                changed.append(r["id"])
            self.zone_hashes[r["id"]] = h
            self.zones[r["id"]] = r["zones"] or []
        return changed

    def reeventize_camera(self, camera_id: str, days: int = 7) -> int:
        n = 0
        last_id = 0
        since = datetime.now(timezone.utc) - timedelta(days=days)
        while True:
            rows = db.fetch_all(
                "SELECT id, camera_id, cls, path FROM tracks WHERE camera_id=%s AND t_end >= %s AND id > %s "
                "ORDER BY id LIMIT %s", (camera_id, since, last_id, BATCH))
            if not rows:
                break
            with db.conn() as c:
                for tr in rows:
                    write_events(c, tr, self.zones.get(camera_id, []))
            n += len(rows)
            last_id = rows[-1]["id"]
        log.info("re-eventized %d tracks for %s after a zone change", n, camera_id)
        return n

    def run_once(self) -> int:
        for cam in self._refresh_zones():
            self.reeventize_camera(cam)
        if self.cursor is None:
            now = db.fetch_val("SELECT now()")
            self.cursor = now - timedelta(minutes=10)
        rows = db.fetch_all(
            "SELECT id, camera_id, cls, path, active, t_start, t_end, crop_keys, updated_at FROM tracks "
            "WHERE updated_at > %s ORDER BY updated_at LIMIT %s", (self.cursor - OVERLAP, BATCH))
        fresh = [r for r in rows if self.seen.get(r["id"]) != r["updated_at"]]
        if fresh:
            with db.conn() as c:
                for tr in fresh:
                    tr["zone_path"] = write_events(c, tr, self.zones.get(tr["camera_id"], []))
            for tr in fresh:
                self.seen[tr["id"]] = tr["updated_at"]
                if self.out_q is not None:
                    self.out_q.put(tr)
            self.processed += len(fresh)
        if rows:
            self.cursor = max(self.cursor, rows[-1]["updated_at"])
        if len(self.seen) > 20000:  # forget old entries
            cutoff = self.cursor - timedelta(minutes=5)
            self.seen = {k: v for k, v in self.seen.items() if v >= cutoff}
        return len(fresh)


def loop(stop: threading.Event, ev: Eventizer, interval: float = 1.0) -> None:
    backoff = interval
    while not stop.is_set():
        try:
            n = ev.run_once()
            backoff = interval
            if n >= BATCH:
                continue  # catching up
        except Exception as e:
            log.exception("eventize error: %s", e)
            backoff = min(30.0, backoff * 2)
        stop.wait(backoff)
