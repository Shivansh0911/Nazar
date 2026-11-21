"""Fast file pipeline (v2, W1): ffmpeg samples frames at DETECT_FPS -> batched GPU detection -> ordered tracking.

No re-encode: the original file stays where it is (registered in `originals`); clips are cut and face-blurred
from it on demand. Every 2 s a face-blurred 512 px keyframe is written for the local visual index. While running,
an annotated, blurred analysis frame + JSON stats are published to data/live/ for the live analysis view.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np

from ..core import db, storage
from ..core.config import ffmpeg_bin
from ..core.media import probe
from ..core.timeutil import dt_to_ms, to_local
from .detector import Det, Detector
from .faceblur import FaceBlurrer
from .tracker_state import TrackManager

log = logging.getLogger("nazar.edge.filerun")
KEYFRAME_EVERY_S = 2.0
KEYFRAME_WIDTH = 512
ANALYSIS_EVERY_S = 0.4  # wall-clock interval for the live analysis view
COLORS = {"person": (60, 220, 60)}


class FFmpegReader:
    """Decoded, sampled frames from ffmpeg (CPU decode is ~25x real time for 720p; optional CUDA decode)."""

    def __init__(self, path: str, fps: float, max_width: int = 1280, hwaccel: bool = False):
        self.path = path
        self.fps = fps
        info = probe(path)
        if not info.get("has_video"):
            raise ValueError("file has no video stream")
        w, h = int(info["width"] or 0), int(info["height"] or 0)
        if abs(int(info.get("rotation") or 0)) in (90, 270):
            w, h = h, w  # ffmpeg autorotates
        self.src_w, self.src_h = w, h
        scale = min(1.0, max_width / max(1, w))
        self.w = max(2, int(round(w * scale / 2)) * 2)
        self.h = max(2, int(round(h * scale / 2)) * 2)
        self.duration = float(info.get("duration") or 0.0)
        self.src_fps = info.get("fps")
        self.hwaccel = hwaccel
        self._q: "queue.Queue[np.ndarray | None]" = queue.Queue(maxsize=48)
        self._proc: subprocess.Popen | None = None
        self.error: str | None = None

    def _cmd(self) -> list[str]:
        cmd = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-nostdin"]
        if self.hwaccel:
            cmd += ["-hwaccel", "cuda"]
        cmd += ["-i", self.path, "-an", "-sn", "-vf", f"fps={self.fps:g},scale={self.w}:{self.h}:flags=area",
                "-pix_fmt", "bgr24", "-f", "rawvideo", "-"]
        return cmd

    def _pump(self) -> None:
        n = self.w * self.h * 3
        try:
            self._proc = subprocess.Popen(self._cmd(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=n * 4)
            assert self._proc.stdout is not None
            while True:
                buf = self._proc.stdout.read(n)
                if not buf or len(buf) < n:
                    break
                self._q.put(np.frombuffer(buf, np.uint8).reshape(self.h, self.w, 3))
            self._proc.wait(timeout=30)
            if self._proc.returncode not in (0, None):
                self.error = (self._proc.stderr.read().decode(errors="ignore") if self._proc.stderr else "")[:300]
        except Exception as e:
            self.error = str(e)
        finally:
            self._q.put(None)

    def frames(self):
        th = threading.Thread(target=self._pump, name="ffmpeg-reader", daemon=True)
        th.start()
        i = 0
        while True:
            img = self._q.get()
            if img is None:
                break
            yield i, img
            i += 1

    def close(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.kill()


class KeyframeWriter:
    def __init__(self, camera_id: str):
        self.camera_id = camera_id
        self.last_t: datetime | None = None
        self.count = 0

    def due(self, t: datetime) -> bool:
        return self.last_t is None or (t - self.last_t).total_seconds() >= KEYFRAME_EVERY_S - 1e-6

    def write(self, blurred: np.ndarray, t: datetime, persons: int) -> None:
        h, w = blurred.shape[:2]
        img = cv2.resize(blurred, (KEYFRAME_WIDTH, int(round(h * KEYFRAME_WIDTH / w / 2)) * 2), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            return
        key = f"keyframes/{self.camera_id}/{to_local(t):%Y%m%d}/{dt_to_ms(t)}.jpg"
        storage.put_bytes(buf.tobytes(), key)
        try:
            db.execute("INSERT INTO keyframes(camera_id, t, key, persons) VALUES (%s,%s,%s,%s)",
                       (self.camera_id, t, key, persons))
            self.count += 1
        except Exception as e:
            log.warning("keyframe insert failed: %s", e)


class AnalysisView:
    """Annotated, face-blurred frame + stats for the upload page's live analysis view (data/live/<camera>.*)."""

    def __init__(self, camera_id: str, zones: list[dict]):
        self.jpg = storage.local_path(f"live/{camera_id}.jpg")
        self.js = storage.local_path(f"live/{camera_id}.json")
        self.jpg.parent.mkdir(parents=True, exist_ok=True)
        self.zones = zones
        self.last = 0.0
        self.seen: set[int] = set()

    def note(self, dets: list[Det]) -> None:
        for d in dets:
            if d.cls == "person":
                self.seen.add(d.track_id)

    def due(self) -> bool:
        return time.monotonic() - self.last >= ANALYSIS_EVERY_S

    def write(self, blurred: np.ndarray, dets: list[Det], stats: dict) -> None:
        img = blurred
        h, w = img.shape[:2]
        if w > 960:
            img = cv2.resize(img, (960, int(h * 960 / w)), interpolation=cv2.INTER_AREA)
            h, w = img.shape[:2]
        for z in self.zones:
            pts = np.array([[int(x * w), int(y * h)] for x, y in z.get("polygon", [])], np.int32)
            if len(pts) >= 2:
                cv2.polylines(img, [pts], z.get("type") != "line", (0, 200, 255), 2)
        for d in dets:
            x1, y1, x2, y2 = int(d.box[0] * w), int(d.box[1] * h), int(d.box[2] * w), int(d.box[3] * h)
            c = COLORS.get(d.cls, (255, 140, 0))
            cv2.rectangle(img, (x1, y1), (x2, y2), c, 2)
            cv2.putText(img, f"{d.cls} {d.track_id}", (x1, max(12, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, c, 1,
                        cv2.LINE_AA)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 72])
        if ok:
            _atomic(self.jpg, buf.tobytes())
        stats = {**stats, "people_so_far": len(self.seen), "in_view": sum(1 for d in dets if d.cls == "person"),
                 "objects_in_view": len(dets), "dets": [[d.cls, d.track_id, *[round(v, 3) for v in d.box]] for d in dets]}
        _atomic(self.js, json.dumps(stats).encode())


def _atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_bytes(data)
    for _ in range(5):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.01)


class SideWriter:
    """Keyframes + live analysis view off the hot path (blur, encode, file + DB writes in one background thread)."""

    def __init__(self, kf: KeyframeWriter, view: AnalysisView):
        self.kf, self.view = kf, view
        self.q: "queue.Queue[tuple | None]" = queue.Queue(maxsize=64)
        self.blur = FaceBlurrer()
        self.th = threading.Thread(target=self._run, name="side-writer", daemon=True)
        self.th.start()

    def put(self, item: tuple) -> None:
        try:
            self.q.put_nowait(item)
        except queue.Full:
            if item[0] == "kf":  # keyframes matter for the index; views can be dropped
                self.q.put(item)

    def _run(self) -> None:
        while True:
            item = self.q.get()
            if item is None:
                return
            try:
                kind, img, dets, t, stats = item
                heads = [d.head for d in dets if d.cls == "person"]
                blurred = self.blur.egress(img, heads, detect=True)
                if kind in ("kf", "both"):
                    self.kf.write(blurred, t, sum(1 for d in dets if d.cls == "person"))
                if kind in ("view", "both"):
                    self.view.write(blurred, dets, stats)
            except Exception as e:
                log.warning("side writer: %s", e)

    def close(self) -> None:
        self.q.put(None)
        self.th.join(timeout=60)


def run_file(*, camera_id: str, source: str, start_time: datetime | None, detector: Detector, tracks: TrackManager,
             hb, zones: list[dict], fps: float, batch: int = 16, max_seconds: float | None = None,
             job_id: int | None = None, stop=lambda: False, max_width: int = 1280) -> dict:
    reader = FFmpegReader(source, fps, max_width=max_width, hwaccel=os.environ.get("NAZAR_HWDECODE") == "1")
    if start_time is None:
        mtime = datetime.fromtimestamp(Path(source).stat().st_mtime, tz=timezone.utc)
        start_time = mtime - timedelta(seconds=reader.duration or 0)
    db.execute("UPDATE cameras SET width=%s, height=%s WHERE id=%s", (reader.w, reader.h, camera_id))
    t_end = start_time + timedelta(seconds=reader.duration or 0)
    src_path = str(Path(source).resolve())
    db.execute("DELETE FROM originals WHERE camera_id=%s AND path=%s AND t_start=%s", (camera_id, src_path, start_time))
    db.execute("INSERT INTO originals(camera_id, path, t_start, t_end, width, height, fps, job_id) "
               "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
               (camera_id, src_path, start_time, t_end, reader.src_w, reader.src_h, reader.src_fps, job_id))
    kf = KeyframeWriter(camera_id)
    view = AnalysisView(camera_id, zones)
    side = SideWriter(kf, view)
    prof = {"predict": 0.0, "tracker": 0.0, "track_mgr": 0.0, "wait_pred": 0.0}
    pred_q: "queue.Queue[tuple | None]" = queue.Queue(maxsize=3)

    def producer() -> None:
        pending: list[tuple[int, np.ndarray]] = []

        def push() -> None:
            t0 = time.perf_counter()
            preds = detector._predict([im for _, im in pending])
            prof["predict"] += time.perf_counter() - t0
            pred_q.put((list(pending), preds))
            pending.clear()

        try:
            for i, img in reader.frames():
                if stop() or (max_seconds and i / fps >= max_seconds):
                    break
                pending.append((i, img))
                if len(pending) >= batch:
                    push()
            if pending:
                push()
        except Exception as e:
            log.exception("detector thread failed: %s", e)
            reader.error = reader.error or str(e)
        finally:
            pred_q.put(None)

    wall0 = time.monotonic()
    th = threading.Thread(target=producer, name="detector", daemon=True)
    th.start()
    n = 0
    pos = 0.0
    try:
        while True:
            tw = time.perf_counter()
            item = pred_q.get()
            prof["wait_pred"] += time.perf_counter() - tw
            if item is None:
                break
            frames, preds = item
            for (i, img), (xy, conf, cls) in zip(frames, preds):
                p0 = time.perf_counter()
                dets = detector._update(xy, conf, cls, img)
                p1 = time.perf_counter()
                pos = i / fps
                t = start_time + timedelta(seconds=pos)
                tracks.update(dets, img, t)
                tracks.step(t)
                prof["tracker"] += p1 - p0
                prof["track_mgr"] += time.perf_counter() - p1
                view.note(dets)
                kf_due, view_due = kf.due(t), view.due()
                if kf_due:
                    kf.last_t = t
                if view_due:
                    view.last = time.monotonic()
                if kf_due or view_due:
                    wall = time.monotonic() - wall0
                    stats = {"t": t.isoformat(), "processed_s": round(pos, 1), "duration_s": round(reader.duration, 1),
                             "speed_x": round(pos / wall, 1) if wall > 0 else None, "state": "processing",
                             "job_id": job_id}
                    side.put(("both" if kf_due and view_due else "kf" if kf_due else "view", img, dets, t, stats))
                hb.count(frames=1, dets=1)
                hb.tick(t, True, len(tracks.active), processed_s=pos, duration_s=reader.duration)
                n += 1
    finally:
        th.join(timeout=30)
        reader.close()
        side.close()
    if reader.error and n == 0:
        raise RuntimeError(f"decode failed: {reader.error}")
    wall = time.monotonic() - wall0
    if view.js.exists():
        try:
            st = json.loads(view.js.read_text())
            st.update(state="done", processed_s=round(pos, 1), speed_x=round(pos / wall, 1) if wall else None)
            _atomic(view.js, json.dumps(st).encode())
        except Exception:
            pass
    return {"frames": n, "pos": pos, "wall": wall, "det_time": prof["predict"] + prof["tracker"], "keyframes": kf.count,
            "duration": reader.duration, "width": reader.w, "height": reader.h,
            "prof": {k: round(v, 2) for k, v in prof.items()}}
