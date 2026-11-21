"""Edge process (one per camera):  python -m nazar.edge.run --camera <id> [--source ...]

decode -> sample -> motion gate -> YOLO + ByteTrack -> 5 Hz paths -> face-blurred crops/segments/snapshot -> Postgres
"""
from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading
import time
import uuid
from pathlib import Path
from datetime import datetime, timezone

import cv2
import numpy as np

from ..core import db
from ..core.config import get_settings
from ..core.logging import setup_logging
from ..core.timeutil import parse_local
from .detector import Detector
from .faceblur import FaceBlurrer
from .heartbeat import Heartbeat
from .segments import SegmentWriter
from .snapshot import Snapshot
from .source import FrameSource, infer_kind
from .tracker_state import TrackManager

log = logging.getLogger("nazar.edge")


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="Nazar edge: watch one camera")
    ap.add_argument("--camera", required=True)
    ap.add_argument("--source")
    ap.add_argument("--start-time", help="files only: ISO local time of the first frame")
    ap.add_argument("--simulate-live", action="store_true", help="pace a file in real time, stamped with now")
    ap.add_argument("--loop", action="store_true", help="with --simulate-live: loop the file forever")
    ap.add_argument("--fast", action="store_true", help="files: process as fast as possible")
    ap.add_argument("--max-seconds", type=float)
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--job", type=int)
    ap.add_argument("--legacy", action="store_true", help="files: v1 OpenCV loop with re-encoded segments")
    ap.add_argument("--batch", type=int, default=16)
    return ap.parse_args(argv)


def ensure_camera(camera_id: str, source: str | None) -> dict:
    row = db.fetch_one("SELECT * FROM cameras WHERE id=%s", (camera_id,))
    if row is None:
        if not source:
            raise SystemExit(f"camera {camera_id!r} not found and no --source given")
        kind = infer_kind(source)
        db.execute("INSERT INTO cameras(id, name, source_url, kind) VALUES (%s,%s,%s,%s)",
                   (camera_id, camera_id, source, kind))
        row = db.fetch_one("SELECT * FROM cameras WHERE id=%s", (camera_id,))
    return row


class MotionGate:
    def __init__(self, thresh: float):
        self.thresh = thresh
        self.prev: np.ndarray | None = None

    def moving(self, frame: np.ndarray) -> bool:
        h, w = frame.shape[:2]
        small = cv2.cvtColor(cv2.resize(frame, (160, max(1, int(h * 160 / w)))), cv2.COLOR_BGR2GRAY)
        small = cv2.GaussianBlur(small, (3, 3), 0)
        if self.prev is None or self.prev.shape != small.shape:
            self.prev = small
            return True
        frac = float(np.count_nonzero(cv2.absdiff(small, self.prev) > 25)) / small.size
        return frac >= self.thresh

    def accept(self, frame: np.ndarray) -> None:
        h, w = frame.shape[:2]
        small = cv2.cvtColor(cv2.resize(frame, (160, max(1, int(h * 160 / w)))), cv2.COLOR_BGR2GRAY)
        self.prev = cv2.GaussianBlur(small, (3, 3), 0)


class Preview:
    def __init__(self, path: str, zones: list[dict]):
        self.path = path
        self.zones = zones
        self.w: cv2.VideoWriter | None = None

    def write(self, img: np.ndarray, dets, fps: float) -> None:
        h, w = img.shape[:2]
        if self.w is None:
            self.w = cv2.VideoWriter(self.path, cv2.VideoWriter_fourcc(*"mp4v"), 5.0, (w, h))
        out = img.copy()
        for z in self.zones:
            pts = np.array([[int(x * w), int(y * h)] for x, y in z.get("polygon", [])], np.int32)
            if len(pts) >= 3:
                cv2.polylines(out, [pts], True, (0, 200, 255), 2)
                cv2.putText(out, z.get("name", ""), tuple(pts[0]), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2)
        for d in dets:
            x1, y1, x2, y2 = int(d.box[0] * w), int(d.box[1] * h), int(d.box[2] * w), int(d.box[3] * h)
            color = (60, 220, 60) if d.cls == "person" else (255, 140, 0)
            cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
            cv2.putText(out, f"{d.cls}#{d.track_id}", (x1, max(12, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
        cv2.putText(out, f"det fps {fps:.1f}", (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        self.w.write(out)

    def close(self) -> None:
        if self.w is not None:
            self.w.release()


def main(argv=None) -> int:
    args = parse_args(argv)
    s = get_settings()
    logs_dir = s.data_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    setup_logging("nazar.edge")
    stop_ev = threading.Event()

    def _stop(*_):
        stop_ev.set()

    signal.signal(signal.SIGINT, _stop)
    try:
        signal.signal(signal.SIGTERM, _stop)
    except Exception:
        pass
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _stop)

    cam = ensure_camera(args.camera, args.source)
    source = args.source or cam["source_url"]
    if not args.source:
        from ..core.secrets import source_url_for

        source = source_url_for(db, args.camera, source)  # credentials decrypted in memory only
    kind = infer_kind(source) if args.source else cam["kind"]
    if kind == "phone":
        kind = "rtsp"
    settings = cam.get("settings") or {}
    zones = cam.get("zones") or []
    start_time = parse_local(args.start_time) if args.start_time else None

    # Low-res sources get upscaled x2 before detection so small bags are found.
    probe = cv2.VideoCapture(source, cv2.CAP_FFMPEG) if kind == "file" else None
    src_h = int(probe.get(cv2.CAP_PROP_FRAME_HEIGHT)) if probe is not None else 0
    if probe is not None:
        probe.release()
    upscale = float(settings.get("upscale") or (2.0 if 0 < src_h < 720 else 1.0))
    imgsz = int(settings.get("detect_imgsz") or (960 if upscale > 1 else s.DETECT_IMGSZ))
    conf = float(settings.get("detect_conf") or s.DETECT_CONF)

    run_id = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
    det_interval = 1.0 / s.DETECT_FPS
    seg_interval = 1.0 / s.SEGMENT_FPS
    hb = Heartbeat(args.camera, args.job)

    def on_status(ok: bool, note: str) -> None:
        hb.tick(datetime.now(timezone.utc), ok, 0, note, force=True)

    if kind == "file" and not args.simulate_live and not args.legacy and not args.preview:
        return run_fast(args, s, source, settings, zones, start_time, run_id, hb)

    src = FrameSource(source, kind, start_time=start_time, simulate_live=args.simulate_live, loop=args.loop,
                      pace=(kind == "file" and not args.fast and not args.simulate_live), min_interval=seg_interval,
                      on_status=on_status, upscale=upscale, stop=stop_ev.is_set)
    detector = Detector(args.device, imgsz=imgsz, conf=conf, fps=s.DETECT_FPS)
    blur = FaceBlurrer()
    tracks = TrackManager(args.camera, run_id, track_end_s=s.TRACK_END_S, upsert_every_s=s.ACTIVE_UPSERT_S,
                          job_id=args.job)
    segs = SegmentWriter(args.camera, s.SEGMENT_FPS, s.SEGMENT_SECONDS, s.SEGMENT_WIDTH)
    snap = Snapshot(args.camera)
    gate = MotionGate(s.MOTION_THRESH)
    preview = Preview(str(s.data_dir / f"preview_{args.camera}.mp4"), zones) if args.preview else None
    if args.job:
        db.execute("UPDATE jobs SET state='processing', updated_at=now() WHERE id=%s", (args.job,))

    log.info("edge %s run=%s source=%s kind=%s upscale=%.1f imgsz=%d", args.camera, run_id,
             src._safe_url(), kind, upscale, imgsz)
    n_frames = n_det = n_skipped = 0
    det_time = 0.0
    last_det_pos = -1e9
    first = True
    t = datetime.now(timezone.utc)
    wall0 = time.monotonic()
    pos = 0.0
    last_dets = []
    last_snap = 0.0
    exit_code = 0
    try:
        for fr in src.frames():
            if stop_ev.is_set():
                break
            t, pos = fr.t, fr.pos_s
            if args.max_seconds and pos >= args.max_seconds:
                break
            img = fr.image
            n_frames += 1
            hb.count(frames=1)
            if first:
                h, w = img.shape[:2]
                db.execute("UPDATE cameras SET width=%s, height=%s WHERE id=%s", (w, h, args.camera))
                first = False
            if pos - last_det_pos >= det_interval - 1e-6:
                last_det_pos = pos
                blur.detect(img)
                if gate.moving(img) or tracks.active:
                    t0 = time.perf_counter()
                    dets = detector.track(img)
                    det_time += time.perf_counter() - t0
                    n_det += 1
                    hb.count(dets=1)
                    gate.accept(img)
                    last_dets = dets
                else:
                    dets = []
                    last_dets = []
                    n_skipped += 1
                blur.set_persons([d.box for d in dets if d.cls == "person"])
                blurred = blur.apply(img)
                tracks.update(dets, img, t)
                tracks.step(t)
                if src.live or args.simulate_live or (time.monotonic() - last_snap) >= 2.0:
                    snap.write(blurred)
                    last_snap = time.monotonic()
                if preview:
                    preview.write(blurred, dets, n_det / max(det_time, 1e-6))
            else:
                blurred = blur.apply(img)
            segs.write(blurred, t)
            hb.tick(t, True, len(tracks.active), processed_s=pos, duration_s=src.duration_s)
    except Exception as e:
        log.exception("edge crashed: %s", e)
        exit_code = 1
        if args.job:
            db.execute("UPDATE jobs SET state='error', error=%s, updated_at=now() WHERE id=%s", (str(e)[:500], args.job))
    finally:
        tracks.finalize_all()
        segs.close()
        if preview:
            preview.close()
        hb.tick(t, False, 0, "stopped", force=True, processed_s=pos, duration_s=src.duration_s)
        if args.job and exit_code == 0:
            db.execute("UPDATE jobs SET state='enriching', processed_s=GREATEST(processed_s, %s), updated_at=now() "
                       "WHERE id=%s AND state IN ('queued','processing')", (pos, args.job))
    wall = time.monotonic() - wall0
    summary = {
        "camera": args.camera, "run_id": run_id, "frames": n_frames, "detections_run": n_det,
        "motion_skipped": n_skipped, "detect_fps": round(n_det / det_time, 1) if det_time else None,
        "wall_s": round(wall, 1), "source_s": round(pos, 1), "speed_x": round(pos / wall, 2) if wall else None,
        "tracks_final": tracks.stats["tracks_final"], "noise_dropped": tracks.stats["noise_dropped"],
        "segments": segs.closed_count, "device": str(detector.device), "imgsz": imgsz, "upscale": upscale,
    }
    log.info("summary %s", json.dumps(summary))
    print("EDGE_SUMMARY " + json.dumps(summary), flush=True)
    db.close_pool()
    return exit_code


def run_fast(args, s, source: str, settings: dict, zones: list, start_time, run_id: str, hb) -> int:
    """v2 file path: ffmpeg sampling + batched detection; no re-encode (clips are cut from the original)."""
    from .filerun import FFmpegReader, run_file

    src_h = FFmpegReader(source, s.DETECT_FPS).src_h
    upscale = float(settings.get("upscale") or (2.0 if 0 < src_h < 720 else 1.0))
    imgsz = int(settings.get("detect_imgsz") or (960 if upscale > 1 else s.DETECT_IMGSZ))
    conf = float(settings.get("detect_conf") or s.DETECT_CONF)
    detector = Detector(args.device, imgsz=imgsz, conf=conf, fps=s.DETECT_FPS)
    tracks = TrackManager(args.camera, run_id, track_end_s=s.TRACK_END_S, upsert_every_s=s.ACTIVE_UPSERT_S,
                          job_id=args.job)
    tracks.wall_upsert = True
    stop_ev = threading.Event()
    for sig in ("SIGINT", "SIGTERM", "SIGBREAK"):
        if hasattr(signal, sig):
            try:
                signal.signal(getattr(signal, sig), lambda *_: stop_ev.set())
            except Exception:
                pass
    if args.job:
        db.execute("UPDATE jobs SET state='processing', updated_at=now() WHERE id=%s", (args.job,))
    log.info("edge(fast) %s run=%s imgsz=%d batch=%d", args.camera, run_id, imgsz, args.batch)
    t = datetime.now(timezone.utc)
    exit_code = 0
    r: dict = {}
    try:
        r = run_file(camera_id=args.camera, source=source, start_time=start_time, detector=detector, tracks=tracks,
                     hb=hb, zones=zones, fps=s.DETECT_FPS, batch=args.batch, max_seconds=args.max_seconds,
                     job_id=args.job, stop=stop_ev.is_set)
    except Exception as e:
        log.exception("edge crashed: %s", e)
        exit_code = 1
        if args.job:
            db.execute("UPDATE jobs SET state='error', error=%s, updated_at=now() WHERE id=%s", (str(e)[:500], args.job))
    finally:
        tracks.finalize_all()
        hb.tick(t, False, 0, "stopped", force=True, processed_s=r.get("pos"), duration_s=r.get("duration"))
        if args.job and exit_code == 0:
            db.execute("UPDATE jobs SET state='enriching', processed_s=GREATEST(processed_s, %s), updated_at=now() "
                       "WHERE id=%s AND state IN ('queued','processing')", (r.get("pos", 0), args.job))
    wall = r.get("wall") or 1e-9
    summary = {
        "camera": args.camera, "run_id": run_id, "mode": "fast", "frames": r.get("frames"),
        "detect_fps": round(r["frames"] / r["det_time"], 1) if r.get("det_time") else None,
        "wall_s": round(wall, 1), "source_s": round(r.get("pos", 0), 1),
        "speed_x": round(r.get("pos", 0) / wall, 2) if r else None, "keyframes": r.get("keyframes"),
        "tracks_final": tracks.stats["tracks_final"], "noise_dropped": tracks.stats["noise_dropped"],
        "device": str(detector.device), "imgsz": imgsz, "weights": Path(detector.weights).name,
        "tracker": detector.tracker_kind, "size": f'{r.get("width")}x{r.get("height")}',
        "det_s": round(r.get("det_time", 0), 2), "prof": r.get("prof"),
    }
    log.info("summary %s", json.dumps(summary))
    print("EDGE_SUMMARY " + json.dumps(summary), flush=True)
    db.close_pool()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
