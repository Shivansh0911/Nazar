"""Clips that always play (W2.5): cut from the original file (uploads/demo) or from recorded segments (live),
face-blurred at egress (stored head boxes of every tracked person + a YuNet pass on every frame), encoded as
H.264 Main / yuv420p / faststart / even dimensions, with a poster JPEG. Cached by (camera, from, to).
Also builds "proof reels": several counted moments, 2-3 s each, captioned "3/17 · 22:14", in one clip.
"""
from __future__ import annotations

import bisect
import hashlib
import logging
import os
import subprocess
import threading
from datetime import datetime, timedelta

import cv2
import numpy as np

from ..core import db, storage
from ..core.config import ffmpeg_bin
from ..core.timeutil import dt_to_ms, to_local

log = logging.getLogger("nazar.clips")
CLIP_FPS = 10
CLIP_WIDTH = 854
_locks: dict[str, threading.Lock] = {}
_glock = threading.Lock()
_blur_tls = threading.local()


class NoFootage(Exception):
    pass


def _lock_for(key: str) -> threading.Lock:
    with _glock:
        return _locks.setdefault(key, threading.Lock())


def _blurrer():
    from ..edge.faceblur import FaceBlurrer

    b = getattr(_blur_tls, "b", None)
    if b is None:
        b = _blur_tls.b = FaceBlurrer()
    return b


# ---- sources ------------------------------------------------------------------------------------
def _sources(camera_id: str, t0: datetime, t1: datetime) -> list[dict]:
    """Pieces covering [t0, t1]: [{kind, path, offset, start, end}] in time order (originals win over segments)."""
    out: list[dict] = []
    orig = db.fetch_all("SELECT path, t_start, t_end FROM originals WHERE camera_id=%s AND t_end > %s AND t_start < %s "
                        "ORDER BY t_start", (camera_id, t0, t1))
    for o in orig:
        if not os.path.exists(o["path"]):
            continue
        s, e = max(t0, o["t_start"]), min(t1, o["t_end"])
        if e > s:
            out.append({"kind": "original", "path": o["path"], "offset": (s - o["t_start"]).total_seconds(),
                        "start": s, "end": e})
    if out:
        return out
    segs = db.fetch_all("SELECT key, t_start, t_end FROM segments WHERE camera_id=%s AND t_end > %s AND t_start < %s "
                        "ORDER BY t_start", (camera_id, t0, t1))
    for sg in segs:
        p = storage.local_path(sg["key"])
        if not p.exists():
            continue
        s, e = max(t0, sg["t_start"]), min(t1, sg["t_end"])
        if e > s:
            out.append({"kind": "segment", "path": str(p), "offset": (s - sg["t_start"]).total_seconds(),
                        "start": s, "end": e})
    # keep one contiguous run (never glue across offline gaps)
    if not out:
        return out
    runs, cur = [], [out[0]]
    for piece in out[1:]:
        if (piece["start"] - cur[-1]["end"]).total_seconds() > 1.0:
            runs.append(cur)
            cur = [piece]
        else:
            cur.append(piece)
    runs.append(cur)
    mid = t0 + (t1 - t0) / 2
    return max(runs, key=lambda r: (r[0]["start"] <= mid <= r[-1]["end"], (r[-1]["end"] - r[0]["start"])))


class HeadIndex:
    """Head boxes of every tracked person on a camera around a time window (from stored paths)."""

    def __init__(self, camera_id: str, t0: datetime, t1: datetime):
        rows = db.fetch_all("SELECT path FROM tracks WHERE camera_id=%s AND cls='person' AND t_end >= %s AND t_start <= %s",
                            (camera_id, t0 - timedelta(seconds=2), t1 + timedelta(seconds=2)))
        self.tracks: list[tuple[list[int], list]] = []
        for r in rows:
            pts = sorted(r["path"] or [], key=lambda p: p[0])
            if pts:
                self.tracks.append(([p[0] for p in pts], pts))

    @staticmethod
    def _head(p: list) -> tuple[float, float, float, float]:
        if len(p) >= 10:
            return (p[6], p[7], p[8], p[9])
        x1, y1, x2, y2 = p[1:5]
        h = y2 - y1
        pw = (x2 - x1) * 0.05
        return (x1 - pw, y1 - 0.02 * h, x2 + pw, y1 + 0.3 * h)

    def at(self, t_ms: int, tol_ms: int = 450) -> list[tuple[float, float, float, float]]:
        out = []
        for ts, pts in self.tracks:
            if t_ms < ts[0] - tol_ms or t_ms > ts[-1] + tol_ms:
                continue
            i = bisect.bisect_left(ts, t_ms)
            cands = [j for j in (i - 1, i) if 0 <= j < len(ts) and abs(ts[j] - t_ms) <= tol_ms]
            if not cands:
                # inside the track's lifetime but between sparse points: interpolate neighbours
                if 0 < i < len(ts):
                    a, b = self._head(pts[i - 1]), self._head(pts[i])
                    out.append(tuple(min(a[k], b[k]) if k < 2 else max(a[k], b[k]) for k in range(4)))
                continue
            for j in cands:
                out.append(self._head(pts[j]))
        return out


def _frames(piece: dict, width: int = CLIP_WIDTH, fps: int = CLIP_FPS):
    """Decoded frames of one piece at `fps`, scaled to `width` (even). Yields (t, image)."""
    dur = (piece["end"] - piece["start"]).total_seconds()
    cmd = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-nostdin", "-ss", f"{piece['offset']:.3f}",
           "-i", piece["path"], "-t", f"{dur:.3f}", "-an", "-vf", f"fps={fps},scale={width}:-2",
           "-pix_fmt", "bgr24", "-f", "rawvideo", "-"]
    # the output height is unknown until ffprobe; scale=-2 keeps aspect: probe once
    from ..core.media import probe

    info = probe(piece["path"])
    w0, h0 = int(info["width"] or width), int(info["height"] or width * 9 // 16)
    if abs(int(info.get("rotation") or 0)) in (90, 270):
        w0, h0 = h0, w0
    h = int(round(h0 * width / w0 / 2)) * 2
    n = width * h * 3
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    k = 0
    try:
        while True:
            buf = p.stdout.read(n)  # type: ignore[union-attr]
            if len(buf) < n:
                break
            yield piece["start"] + timedelta(seconds=k / fps), np.frombuffer(buf, np.uint8).reshape(h, width, 3).copy()
            k += 1
    finally:
        p.kill()


class _Encoder:
    def __init__(self, path: str, w: int, h: int, fps: int = CLIP_FPS):
        self.p = subprocess.Popen(
            [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
             "-s", f"{w}x{h}", "-r", str(fps), "-i", "-", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "25",
             "-profile:v", "main", "-level", "3.1", "-pix_fmt", "yuv420p", "-movflags", "+faststart", path],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.size = (w, h)
        self.n = 0

    def write(self, img: np.ndarray) -> None:
        if (img.shape[1], img.shape[0]) != self.size:
            img = cv2.resize(img, self.size)
        self.p.stdin.write(img.tobytes())  # type: ignore[union-attr]
        self.n += 1

    def close(self) -> None:
        self.p.stdin.close()  # type: ignore[union-attr]
        self.p.wait(timeout=120)
        if self.p.returncode != 0:
            raise RuntimeError("clip encode failed: " + (self.p.stderr.read().decode(errors="ignore")[:300] if self.p.stderr else ""))


def _blurred_frames(camera_id: str, pieces: list[dict]):
    heads = HeadIndex(camera_id, pieces[0]["start"], pieces[-1]["end"])
    blur = _blurrer()
    k = 0
    for piece in pieces:
        for t, img in _frames(piece):
            hb = heads.at(dt_to_ms(t)) if piece["kind"] == "original" else []
            # YuNet on every 3rd frame (10 fps clips); in between the last faces are reused, padded by egress()
            yield t, blur.egress(img, hb, detect=(k % 3 == 0), inplace=True, reuse=True)
            k += 1


def _write_atomic(key: str, produce) -> None:
    out = storage.local_path(key)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.stem + ".part.mp4")
    try:
        produce(str(tmp))
        os.replace(tmp, out)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    storage.put(out, key)


def cut(camera_id: str, t0: datetime, t1: datetime) -> dict:
    """Returns {key, poster_key, t0_ms, t1_ms} for the covered part of [t0, t1] (clamped to stored footage)."""
    pieces = _sources(camera_id, t0, t1)
    if not pieces:
        raise NoFootage("no footage stored for that time")
    start, end = pieces[0]["start"], pieces[-1]["end"]
    if (end - start).total_seconds() < 0.2:
        raise NoFootage("no footage stored for that time")
    h = hashlib.sha1(f"v2|{camera_id}|{dt_to_ms(start)}|{dt_to_ms(end)}".encode()).hexdigest()[:20]
    key = f"clips/{camera_id}/{h}.mp4"
    poster = f"clips/{camera_id}/{h}.jpg"
    with _lock_for(key):
        if not storage.exists(key):
            def produce(path: str) -> None:
                enc = None
                first = None
                for _, img in _blurred_frames(camera_id, pieces):
                    if enc is None:
                        enc = _Encoder(path, img.shape[1], img.shape[0])
                        first = img.copy()
                    enc.write(img)
                if enc is None:
                    raise NoFootage("footage could not be decoded for that time")
                enc.close()
                ok, buf = cv2.imencode(".jpg", first, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if ok:
                    storage.put_bytes(buf.tobytes(), poster)

            _write_atomic(key, produce)
    return {"key": key, "poster_key": poster if storage.exists(poster) else None, "t0_ms": dt_to_ms(start),
            "t1_ms": dt_to_ms(end)}


def reel(items: list[dict], total: int | None = None, max_s: float = 60.0, each_s: float = 2.5) -> dict:
    """Proof reel: items = [{camera_id, t (datetime), track_id?}] -> one captioned clip ('3/17 · 22:14')."""
    total = total or len(items)
    n_max = max(1, int(max_s // each_s))
    items = items[:n_max]
    sig = "|".join(f"{i['camera_id']}:{dt_to_ms(i['t'])}" for i in items)
    h = hashlib.sha1(f"reel|{total}|{sig}".encode()).hexdigest()[:20]
    key = f"clips/reels/{h}.mp4"
    poster = f"clips/reels/{h}.jpg"
    used = 0
    with _lock_for(key):
        if not storage.exists(key):
            def prep(it: dict) -> list | None:
                # decode + blur one moment (thread-local blurrer: safe to run several moments at once)
                t0 = it["t"] - timedelta(seconds=0.5)
                pieces = _sources(it["camera_id"], t0, t0 + timedelta(seconds=each_s))
                return [img for _, img in _blurred_frames(it["camera_id"], pieces)] if pieces else None

            def moments():
                # v3: 3 workers, at most 4 moments in flight (bounded memory), yielded in order
                from collections import deque
                from concurrent.futures import ThreadPoolExecutor

                with ThreadPoolExecutor(max_workers=3) as pool:
                    q: deque = deque()
                    it_iter = iter(items)
                    for it in it_iter:
                        q.append((it, pool.submit(prep, it)))
                        if len(q) >= 4:
                            break
                    while q:
                        it, fut = q.popleft()
                        nxt = next(it_iter, None)
                        if nxt is not None:
                            q.append((nxt, pool.submit(prep, nxt)))
                        yield it, fut.result()

            def produce(path: str) -> None:
                nonlocal used
                enc = None
                first = None
                for k, (it, frames) in enumerate(moments(), 1):
                    if not frames:
                        continue
                    used += 1
                    label = f"{k}/{total} - {to_local(it["t"]):%H:%M}"
                    for img in frames:
                        if enc is None:
                            enc = _Encoder(path, img.shape[1], img.shape[0])
                        if (img.shape[1], img.shape[0]) != enc.size:
                            img = cv2.resize(img, enc.size)
                        cv2.rectangle(img, (8, 8), (16 + 13 * len(label), 44), (15, 23, 42), -1)
                        cv2.putText(img, label, (16, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2, cv2.LINE_AA)
                        if first is None:
                            first = img.copy()
                        enc.write(img)
                if enc is None:
                    raise NoFootage("no stored footage for these moments")
                enc.close()
                ok, buf = cv2.imencode(".jpg", first, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if ok:
                    storage.put_bytes(buf.tobytes(), poster)

            _write_atomic(key, produce)
    return {"key": key, "poster_key": poster if storage.exists(poster) else None, "moments": len(items)}


def track_window(track: dict, at: datetime | None = None, first_event: datetime | None = None,
                 max_s: float = 30.0) -> tuple[datetime, datetime]:
    t0 = track["t_start"] - timedelta(seconds=2)
    t1 = track["t_end"] + timedelta(seconds=2)
    if (t1 - t0).total_seconds() > max_s:
        c = at or first_event or (track["t_start"] + (track["t_end"] - track["t_start"]) / 2)
        t0 = max(t0, c - timedelta(seconds=max_s / 2))
        t1 = t0 + timedelta(seconds=max_s)
    return t0, t1
