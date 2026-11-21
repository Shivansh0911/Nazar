"""Retention: delete media and rows older than RETENTION_DAYS (never usage or queries)."""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone

from ..core import db, storage
from ..core.config import get_settings

log = logging.getLogger("nazar.retention")


def run_once(days: int | None = None) -> dict:
    days = days if days is not None else get_settings().RETENTION_DAYS
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    stats = {"segments": 0, "tracks": 0, "status": 0, "files": 0}
    while True:
        segs = db.fetch_all("SELECT id, key FROM segments WHERE t_end < %s LIMIT 500", (cutoff,))
        if not segs:
            break
        for s in segs:
            storage.delete(s["key"])
        db.execute("DELETE FROM segments WHERE id = ANY(%s)", ([s["id"] for s in segs],))
        stats["segments"] += len(segs)
    while True:
        trs = db.fetch_all("SELECT id, crop_keys FROM tracks WHERE t_end < %s LIMIT 500", (cutoff,))
        if not trs:
            break
        alerts = db.fetch_all("SELECT snapshot_key, audio_key, clip_key FROM alerts WHERE track_id = ANY(%s)",
                              ([t["id"] for t in trs],))
        for t in trs:
            for k in t["crop_keys"] or []:
                storage.delete(k)
        for a in alerts:
            for k in (a["snapshot_key"], a["audio_key"], a["clip_key"]):
                if k:
                    storage.delete(k)
        db.execute("DELETE FROM tracks WHERE id = ANY(%s)", ([t["id"] for t in trs],))  # cascades events, alerts
        stats["tracks"] += len(trs)
    stats["status"] = db.execute("DELETE FROM camera_status WHERE t < %s", (cutoff,))
    # cached clips / tts / snapshots by file age
    limit = time.time() - days * 86400
    for sub in ("clips", "tts", "snap"):
        root = storage.data_dir() / sub
        if not root.exists():
            continue
        for dirpath, _, files in os.walk(root):
            for f in files:
                p = os.path.join(dirpath, f)
                try:
                    if os.path.getmtime(p) < limit:
                        os.remove(p)
                        stats["files"] += 1
                except OSError:
                    pass
    if any(stats.values()):
        log.info("retention removed %s", stats)
    return stats


def loop(stop: threading.Event, interval: float = 3600.0) -> None:
    while not stop.is_set():
        try:
            run_once()
        except Exception as e:
            log.exception("retention error: %s", e)
        stop.wait(interval)
