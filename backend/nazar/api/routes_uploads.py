"""Resumable chunked uploads (W9.1): init -> PUT parts (any order, retry any part) -> complete.

The original is kept as-is (no re-encode; odd containers are remuxed) and processed by the fast file pipeline;
the upload page shows the live analysis view (data/live/<camera>.jpg/.json) while it runs.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ..core import db, storage
from ..core.config import get_settings
from ..core.media import probe, run_ffmpeg
from ..core.timeutil import now_local, parse_local, to_local
from .auth import require_token
from .deps import http_error
from .edge_manager import get_manager
from .routes_cameras import camera_rows, slug, unique_id

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])
CHUNK = 8 * 1024 * 1024
MAX_HOURS = 3
OK_EXT = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".ts", ".dav", ".webm", ".3gp", ".mpg", ".mpeg", ".flv"}


def _dir(upload_id: str):
    if not re.fullmatch(r"[a-f0-9]{32}", upload_id):
        raise http_error(400, "bad upload id")
    return get_settings().data_dir / "uploads" / "parts" / upload_id


class InitIn(BaseModel):
    filename: str = Field(min_length=1, max_length=200)
    size: int = Field(gt=0)
    name: str | None = Field(None, max_length=60)
    recorded_at: str | None = None
    camera_id: str | None = None  # add footage to an existing file camera


@router.post("/uploads/init")
def init(body: InitIn):
    s = get_settings()
    if body.size > s.UPLOAD_MAX_MB * 1024 * 1024:
        raise http_error(413, f"file is larger than {s.UPLOAD_MAX_MB} MB")
    ext = os.path.splitext(body.filename)[1].lower()
    if ext not in OK_EXT:
        raise http_error(400, f"{ext or 'this file type'} is not a supported video file")
    if body.recorded_at:
        try:
            parse_local(body.recorded_at)
        except Exception:
            raise http_error(400, "bad 'recorded at' time")
    uid = uuid.uuid4().hex
    d = _dir(uid)
    d.mkdir(parents=True, exist_ok=True)
    parts = (body.size + CHUNK - 1) // CHUNK
    (d / "meta.json").write_text(json.dumps({**body.model_dump(), "ext": ext, "parts": parts}))
    return {"upload_id": uid, "chunk_size": CHUNK, "parts": parts, "received": []}


@router.get("/uploads/{upload_id}")
def status(upload_id: str):
    d = _dir(upload_id)
    if not (d / "meta.json").exists():
        raise http_error(404, "upload not found")
    meta = json.loads((d / "meta.json").read_text())
    got = sorted(int(p.stem) for p in d.glob("*.part"))
    return {"upload_id": upload_id, "chunk_size": CHUNK, "parts": meta["parts"], "received": got}


@router.put("/uploads/{upload_id}/part/{index}")
async def part(upload_id: str, index: int, request: Request):
    d = _dir(upload_id)
    if not (d / "meta.json").exists():
        raise http_error(404, "upload not found")
    meta = json.loads((d / "meta.json").read_text())
    if not 0 <= index < meta["parts"]:
        raise http_error(400, "bad part index")
    data = await request.body()
    if len(data) > CHUNK or (index < meta["parts"] - 1 and len(data) != CHUNK):
        raise http_error(400, "wrong part size")
    tmp = d / f"{index}.tmp"
    tmp.write_bytes(data)
    os.replace(tmp, d / f"{index}.part")
    return {"index": index, "bytes": len(data)}


def _validate(info: dict) -> str | None:
    if not info.get("has_video"):
        return "this file has no video stream (audio only or not a video)"
    if not info.get("duration") or info["duration"] < 1:
        return "this video is empty or unreadable"
    if info["duration"] > MAX_HOURS * 3600:
        return f"video is longer than {MAX_HOURS} hours"
    if not info.get("width") or not info.get("height"):
        return "could not read the video size"
    return None


def _prepare(path: str, ext: str) -> str:
    """Keep the original; remux containers ffmpeg seeks poorly in (.dav/.avi/.ts/.flv/.mpg) to mp4 (no re-encode)."""
    if ext in (".mp4", ".mov", ".mkv", ".m4v", ".webm", ".3gp"):
        return path
    out = os.path.splitext(path)[0] + ".mp4"
    try:
        run_ffmpeg(["-y", "-i", path, "-map", "0:v:0", "-c", "copy", "-movflags", "+faststart", out], timeout=1800)
    except Exception:
        run_ffmpeg(["-y", "-i", path, "-map", "0:v:0", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", out], timeout=7200)
    os.unlink(path)
    return out


@router.post("/uploads/{upload_id}/complete")
def complete(upload_id: str):
    d = _dir(upload_id)
    if not (d / "meta.json").exists():
        raise http_error(404, "upload not found")
    meta = json.loads((d / "meta.json").read_text())
    missing = [i for i in range(meta["parts"]) if not (d / f"{i}.part").exists()]
    if missing:
        raise http_error(409, f"{len(missing)} part(s) missing", )
    up = get_settings().data_dir / "uploads"
    raw = up / f"{upload_id}{meta['ext']}"
    with open(raw, "wb") as f:
        for i in range(meta["parts"]):
            with open(d / f"{i}.part", "rb") as p:
                shutil.copyfileobj(p, f, 1 << 20)
    shutil.rmtree(d, ignore_errors=True)
    try:
        info = probe(raw)
    except Exception:
        raw.unlink(missing_ok=True)
        raise http_error(400, "not a video file")
    err = _validate(info)
    if err:
        raw.unlink(missing_ok=True)
        raise http_error(400, err)
    start = parse_local(meta["recorded_at"]) if meta.get("recorded_at") else now_local() - timedelta(seconds=info["duration"])
    if meta.get("camera_id") and db.fetch_one("SELECT 1 FROM cameras WHERE id=%s AND kind='file'", (meta["camera_id"],)):
        cid = meta["camera_id"]
    else:
        name = (meta.get("name") or os.path.splitext(meta["filename"])[0]).strip()[:60] or "Uploaded video"
        cid = unique_id(slug(name))
        db.execute("INSERT INTO cameras(id, name, source_url, kind) VALUES (%s,%s,%s,'file')", (cid, name, str(raw)))
    job = db.fetch_one("INSERT INTO jobs(camera_id, kind, source, start_time, duration_s, state) VALUES "
                       "(%s,'upload',%s,%s,%s,'queued') RETURNING id", (cid, str(raw), start, info["duration"]))["id"]

    def go():
        try:
            final = _prepare(str(raw), meta["ext"])
            db.execute("UPDATE jobs SET source=%s WHERE id=%s", (final, job))
            db.execute("UPDATE cameras SET source_url=%s WHERE id=%s AND kind='file'", (final, cid))
            get_manager().start(cid, args=["--source", final, "--start-time", to_local(start).isoformat()],
                                live=False, job_id=job)
        except Exception as e:
            db.execute("UPDATE jobs SET state='error', error=%s, updated_at=now() WHERE id=%s", (str(e)[:400], job))

    threading.Thread(target=go, daemon=True).start()
    w, h = info["width"], info["height"]
    if abs(int(info.get("rotation") or 0)) in (90, 270):
        w, h = h, w
    return {"camera": camera_rows(cid)[0], "job_id": job, "duration_s": round(info["duration"], 1), "width": w,
            "height": h, "portrait": h > w}


@router.get("/analysis/{camera_id}/live")
def analysis_live(camera_id: str, token: str = Depends(require_token)):
    """Live analysis view stats while a file is processed (the annotated frame is /api/cameras/<id>/live.mjpg)."""
    p = storage.local_path(f"live/{camera_id}.json")
    job = db.fetch_one("SELECT id, state, processed_s, duration_s, error FROM jobs WHERE camera_id=%s ORDER BY id DESC "
                       "LIMIT 1", (camera_id,))
    st = {}
    if p.exists():
        try:
            st = json.loads(p.read_text())
        except Exception:
            st = {}
    st.pop("dets", None)
    return {"camera_id": camera_id, "job": job and {k: (float(v) if isinstance(v, (int, float)) else v) for k, v in job.items()},
            "stats": st, "frame_url": storage.url(f"live/{camera_id}.jpg", token)}
