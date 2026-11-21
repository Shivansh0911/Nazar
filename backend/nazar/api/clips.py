"""Cut a clip from stored 10 s segments (ffmpeg concat), cached by (camera, from, to)."""
from __future__ import annotations

import hashlib
import os
import tempfile
import threading
from datetime import datetime, timedelta

from ..core import db, storage
from ..core.media import run_ffmpeg
from ..core.timeutil import dt_to_ms

_locks: dict[str, threading.Lock] = {}
_glock = threading.Lock()


class NoFootage(Exception):
    pass


def _lock_for(key: str) -> threading.Lock:
    with _glock:
        return _locks.setdefault(key, threading.Lock())


def cut(camera_id: str, t0: datetime, t1: datetime) -> dict:
    """Returns {key, t0_ms, t1_ms} where t0/t1 are the real covered times (clamped to stored footage)."""
    segs = db.fetch_all("SELECT key, t_start, t_end FROM segments WHERE camera_id=%s AND t_end > %s AND t_start < %s "
                        "ORDER BY t_start", (camera_id, t0, t1))
    segs = [s for s in segs if storage.local_path(s["key"]).exists()]
    if not segs:
        raise NoFootage("no footage stored for that time")
    # keep only a contiguous run around the requested window (avoid gluing across offline gaps)
    run = [segs[0]]
    for s in segs[1:]:
        if (s["t_start"] - run[-1]["t_end"]).total_seconds() > 1.0:
            if run[-1]["t_end"] >= t0 + (t1 - t0) / 2:
                break
            run = [s]
        else:
            run.append(s)
    start = max(t0, run[0]["t_start"])
    end = min(t1, run[-1]["t_end"])
    if end <= start:
        raise NoFootage("no footage stored for that time")
    h = hashlib.sha1(f"{camera_id}|{dt_to_ms(start)}|{dt_to_ms(end)}".encode()).hexdigest()[:20]
    key = f"clips/{camera_id}/{h}.mp4"
    with _lock_for(key):
        if not storage.exists(key):
            out = storage.local_path(key)
            out.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
                for s in run:
                    f.write("file '" + str(storage.local_path(s["key"])).replace("\\", "/").replace("'", r"'\''") + "'\n")
                listfile = f.name
            tmp = out.with_name(out.stem + ".part.mp4")
            try:
                offset = (start - run[0]["t_start"]).total_seconds()
                dur = (end - start).total_seconds()
                run_ffmpeg(["-y", "-f", "concat", "-safe", "0", "-i", listfile, "-ss", f"{offset:.3f}", "-t", f"{dur:.3f}",
                            "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p",
                            "-movflags", "+faststart", str(tmp)], timeout=60)
                os.replace(tmp, out)
            finally:
                try:
                    os.unlink(listfile)
                except OSError:
                    pass
                if tmp.exists():
                    tmp.unlink(missing_ok=True)
            storage.put(out, key)
    return {"key": key, "t0_ms": dt_to_ms(start), "t1_ms": dt_to_ms(end)}


def track_window(track: dict, at: datetime | None = None, first_event: datetime | None = None,
                 max_s: float = 30.0) -> tuple[datetime, datetime]:
    t0 = track["t_start"] - timedelta(seconds=2)
    t1 = track["t_end"] + timedelta(seconds=2)
    if (t1 - t0).total_seconds() > max_s:
        c = at or first_event or (track["t_start"] + (track["t_end"] - track["t_start"]) / 2)
        t0 = max(t0, c - timedelta(seconds=max_s / 2))
        t1 = t0 + timedelta(seconds=max_s)
    return t0, t1
