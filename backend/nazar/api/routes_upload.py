"""Upload any video (owner's or a judge's) -> file camera -> processed by an edge with --fast."""
from __future__ import annotations

import os
import shutil
import threading
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, File, Form, UploadFile

from ..core import db
from ..core.config import get_settings
from ..core.media import probe, run_ffmpeg
from ..core.timeutil import now_local, parse_local, to_local
from .auth import require_token
from .deps import http_error
from .edge_manager import get_manager
from .routes_cameras import camera_rows, slug, unique_id

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])
MAX_MINUTES = 60
MAX_WIDTH = 1280


def _normalize(src: str, dst: str, info: dict) -> None:
    """Downscale anything wider than 1280 px; ffmpeg applies rotation metadata (portrait phone videos)."""
    w, h = info.get("width") or 0, info.get("height") or 0
    if abs(info.get("rotation") or 0) in (90, 270):
        w, h = h, w
    vf = f"scale='min({MAX_WIDTH},iw)':-2" if w > MAX_WIDTH else "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    run_ffmpeg(["-y", "-i", src, "-an", "-vf", vf, "-fpsmax", "30", "-c:v", "libx264", "-preset", "veryfast",
                "-crf", "22", "-pix_fmt", "yuv420p", "-movflags", "+faststart", dst], timeout=3600)


def _process(camera_id: str, job_id: int, raw: str, final: str, info: dict, start_iso: str) -> None:
    try:
        db.execute("UPDATE jobs SET state='processing', updated_at=now() WHERE id=%s", (job_id,))
        _normalize(raw, final, info)
        os.unlink(raw)
        get_manager().start(camera_id, args=["--source", final, "--start-time", start_iso, "--fast"], live=False,
                            job_id=job_id)
    except Exception as e:
        db.execute("UPDATE jobs SET state='error', error=%s, updated_at=now() WHERE id=%s", (str(e)[:400], job_id))


@router.post("/cameras/upload")
def upload(file: UploadFile = File(...), name: str = Form(...), start: str | None = Form(None)):
    s = get_settings()
    up = s.data_dir / "uploads"
    up.mkdir(parents=True, exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1].lower()[:6] or ".mp4"
    raw = up / f"{uuid.uuid4().hex}{ext}"
    limit = s.UPLOAD_MAX_MB * 1024 * 1024
    size = 0
    with open(raw, "wb") as f:
        while chunk := file.file.read(1 << 20):
            size += len(chunk)
            if size > limit:
                f.close()
                raw.unlink(missing_ok=True)
                raise http_error(413, f"file is larger than {s.UPLOAD_MAX_MB} MB")
            f.write(chunk)
    try:
        info = probe(raw)
    except Exception:
        raw.unlink(missing_ok=True)
        raise http_error(400, "not a video file")
    if not info.get("has_video") or not info.get("duration"):
        raw.unlink(missing_ok=True)
        raise http_error(400, "not a video file (no video stream)")
    if info["duration"] > MAX_MINUTES * 60:
        raw.unlink(missing_ok=True)
        raise http_error(400, f"video is longer than {MAX_MINUTES} minutes")
    try:
        st = parse_local(start) if start else now_local() - timedelta(seconds=info["duration"])
    except Exception:
        raw.unlink(missing_ok=True)
        raise http_error(400, "bad 'start' time")
    cid = unique_id(slug(name))
    final = str(up / f"{cid}.mp4")
    db.execute("INSERT INTO cameras(id, name, source_url, kind) VALUES (%s,%s,%s,'file')", (cid, name.strip()[:60], final))
    job = db.fetch_one("INSERT INTO jobs(camera_id, kind, source, start_time, duration_s, state) VALUES "
                       "(%s,'upload',%s,%s,%s,'queued') RETURNING id", (cid, final, st, info["duration"]))["id"]
    threading.Thread(target=_process, args=(cid, job, str(raw), final, info, to_local(st).isoformat()),
                     daemon=True).start()
    return {"camera": camera_rows(cid)[0], "job_id": job, "duration_s": round(info["duration"], 1),
            "width": info.get("width"), "height": info.get("height"), "rotation": info.get("rotation")}
