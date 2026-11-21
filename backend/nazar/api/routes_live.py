"""Live view: latest face-blurred snapshot and an MJPEG stream (works in every browser, no HLS)."""
from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response, StreamingResponse

from ..core import db, storage
from ..core.media import first_frame_jpeg
from .auth import require_token
from .deps import camera_or_404, http_error

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])
BOUNDARY = "nazarframe"


def snapshot_bytes(camera_id: str) -> bytes | None:
    live = storage.local_path(f"live/{camera_id}.jpg")
    for _ in range(3):
        try:
            if live.exists():
                return live.read_bytes()
            break
        except PermissionError:
            time.sleep(0.02)
    seg = db.fetch_one("SELECT key FROM segments WHERE camera_id=%s ORDER BY t_end DESC LIMIT 1", (camera_id,))
    if not seg or not storage.local_path(seg["key"]).exists():
        kf = db.fetch_one("SELECT key FROM keyframes WHERE camera_id=%s ORDER BY persons ASC, t DESC LIMIT 1", (camera_id,))
        if kf and storage.local_path(kf["key"]).exists():
            return storage.local_path(kf["key"]).read_bytes()  # face-blurred keyframe (files are not re-encoded)
        return None
    cache = storage.local_path(f"live/{camera_id}_seg.jpg")
    cache.parent.mkdir(parents=True, exist_ok=True)
    try:
        if not cache.exists() or cache.stat().st_mtime < storage.local_path(seg["key"]).stat().st_mtime:
            first_frame_jpeg(storage.local_path(seg["key"]), cache)
        return cache.read_bytes()
    except Exception:
        return None


@router.get("/cameras/{camera_id}/snapshot.jpg")
def snapshot(camera_id: str):
    camera_or_404(camera_id)
    data = snapshot_bytes(camera_id)
    if data is None:
        raise http_error(404, "no snapshot yet")
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.get("/cameras/{camera_id}/live.mjpg")
async def mjpeg(camera_id: str, request: Request, fps: float = 5.0, overlay: bool = False):
    camera_or_404(camera_id)
    path = storage.local_path(f"live/{camera_id}.jpg")
    if overlay:  # face-blurred frame with tracker boxes/ids/counts (written by live edges)
        ov = storage.local_path(f"live/{camera_id}_view.jpg")
        if ov.exists() and time.time() - ov.stat().st_mtime < 30:
            path = ov
    interval = 1.0 / max(1.0, min(fps, 10.0))

    async def gen():
        last_mtime = 0.0
        last_data: bytes | None = None
        idle = 0
        while not await request.is_disconnected():
            data = None
            try:
                m = path.stat().st_mtime
                if m != last_mtime:
                    data = path.read_bytes()
                    last_mtime = m
            except (OSError, PermissionError):
                data = None
            if data is None and last_data is None:
                data = snapshot_bytes(camera_id)
            if data:
                last_data = data
                idle = 0
            else:
                idle += 1
            if last_data and (data or idle % int(1 / interval) == 0):
                yield (f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(last_data)}\r\n\r\n").encode() \
                    + last_data + b"\r\n"
            await asyncio.sleep(interval)

    return StreamingResponse(gen(), media_type=f"multipart/x-mixed-replace; boundary={BOUNDARY}",
                             headers={"Cache-Control": "no-store"})
