"""Cameras: list/create/edit, zones, suggest-zones, timeline, gaps, edge start/stop, progress."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from ..core import db, storage
from ..core.config import get_settings
from ..core.security import SourceError, validate_source
from ..core.timeutil import now_local, to_local
from ..core.zones import clean_zones, suggest_zones
from . import agent_tools
from .auth import require_token
from .deps import camera_or_404, http_error, window
from .edge_manager import get_manager
from .routes_live import snapshot_bytes

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])
LIVE_MAX_AGE_S = 15.0


class CameraIn(BaseModel):
    id: str | None = None
    name: str
    source_url: str
    kind: str | None = None
    start: bool = True


class CameraPatch(BaseModel):
    name: str | None = None
    zones: list[dict] | None = None
    settings: dict | None = None
    active: bool | None = None


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "camera"


def unique_id(base: str) -> str:
    cid, n = base, 2
    while db.fetch_one("SELECT 1 FROM cameras WHERE id=%s", (cid,)):
        cid = f"{base}-{n}"
        n += 1
    return cid


def camera_rows(camera_id: str | None = None) -> list[dict]:
    today = now_local().replace(hour=0, minute=0, second=0, microsecond=0)
    rows = db.fetch_all(
        f"""SELECT c.*, hb.t AS hb_t, hb.ok AS hb_ok, hb.note AS hb_note, hb.fps_proc,
                  (SELECT count(*) FROM root_tracks r WHERE r.camera_id=c.id AND r.cls='person' AND r.t_start >= %s) AS today_count,
                  cov.t0, cov.t1
             FROM cameras c
             LEFT JOIN LATERAL (SELECT t, ok, note, fps_proc FROM camera_status s WHERE s.camera_id=c.id
                                ORDER BY t DESC LIMIT 1) hb ON true
             LEFT JOIN LATERAL (SELECT min(t_start) t0, max(t_end) t1 FROM coverage g WHERE g.camera_id=c.id) cov ON true
            {"WHERE c.id=%s" if camera_id else ""} ORDER BY c.created_at""",
        (today, camera_id) if camera_id else (today,))
    mgr = get_manager()
    out = []
    now = datetime.now(timezone.utc)
    for r in rows:
        age = (now - r["hb_t"]).total_seconds() if r["hb_t"] else None
        running = mgr.is_running(r["id"])
        live = bool(r["hb_ok"]) and age is not None and age <= LIVE_MAX_AGE_S
        out.append({
            "id": r["id"], "name": r["name"], "kind": r["kind"], "source_url": _safe(r["source_url"]),
            "zones": r["zones"] or [], "settings": r["settings"] or {}, "width": r["width"], "height": r["height"],
            "active": r["active"], "live": live, "last_heartbeat_age_s": round(age, 1) if age is not None else None,
            "status_note": r["hb_note"], "today_count": int(r["today_count"] or 0),
            "coverage_from": to_local(r["t0"]).isoformat() if r["t0"] else None,
            "coverage_to": to_local(r["t1"]).isoformat() if r["t1"] else None, "edge_running": running,
            "fps_proc": round(r["fps_proc"], 1) if r["fps_proc"] is not None else None,
        })
    return out


def _safe(url: str) -> str:
    return re.sub(r"//([^/@:]+):[^/@]+@", r"//\1:***@", url or "")


@router.get("/cameras")
def list_cameras():
    return camera_rows()


@router.get("/cameras/{camera_id}")
def get_camera(camera_id: str):
    rows = camera_rows(camera_id)
    if not rows:
        raise http_error(404, "camera not found")
    return rows[0]


@router.post("/cameras")
def create_camera(body: CameraIn):
    try:
        url, kind = validate_source(body.source_url, body.kind)
    except SourceError as e:
        raise http_error(400, str(e))
    cid = unique_id(slug(body.id or body.name))
    db.execute("INSERT INTO cameras(id, name, source_url, kind) VALUES (%s,%s,%s,%s)", (cid, body.name.strip()[:60], url, kind))
    status = None
    if body.start and kind != "file":
        status = get_manager().start(cid, live=True)
    return {**camera_rows(cid)[0], "edge_status": status}


@router.patch("/cameras/{camera_id}")
def patch_camera(camera_id: str, body: CameraPatch):
    camera_or_404(camera_id)
    if body.name is not None:
        db.execute("UPDATE cameras SET name=%s WHERE id=%s", (body.name.strip()[:60], camera_id))
    if body.zones is not None:
        try:
            zones = clean_zones(body.zones)
        except Exception as e:
            raise http_error(400, f"invalid zones: {e}")
        db.execute("UPDATE cameras SET zones=%s, zones_updated_at=now() WHERE id=%s", (Jsonb(zones), camera_id))
    if body.settings is not None:
        allowed = {k: v for k, v in body.settings.items() if k in ("detect_imgsz", "upscale", "detect_conf")}
        db.execute("UPDATE cameras SET settings=%s WHERE id=%s", (Jsonb(allowed), camera_id))
    if body.active is not None:
        db.execute("UPDATE cameras SET active=%s WHERE id=%s", (body.active, camera_id))
    return camera_rows(camera_id)[0]


@router.delete("/cameras/{camera_id}")
def delete_camera(camera_id: str):
    camera_or_404(camera_id)
    get_manager().stop(camera_id)
    db.execute("DELETE FROM cameras WHERE id=%s", (camera_id,))
    return {"ok": True}


@router.post("/cameras/{camera_id}/suggest-zones")
def suggest(camera_id: str):
    camera_or_404(camera_id)
    jpg = snapshot_bytes(camera_id)
    if jpg is None:
        raise http_error(404, "no snapshot yet - start the camera or process a video first")
    return {"zones": suggest_zones(jpg, camera_id), "note": "suggestions only - edit and save"}


@router.get("/cameras/{camera_id}/timeline")
def timeline(camera_id: str, from_: str | None = Query(None, alias="from"), to: str | None = None,
             bucket: str = "hour", cls: str = "person", zone: str | None = None):
    camera_or_404(camera_id)
    t0, t1 = window(from_, to, 24)
    return agent_tools.count_events({"camera_id": camera_id, "zone": zone, "cls": cls,
                                     "event": "enter" if zone else "present", "time_from": t0, "time_to": t1,
                                     "bucket": bucket})


@router.get("/cameras/{camera_id}/gaps")
def gaps(camera_id: str, from_: str | None = Query(None, alias="from"), to: str | None = None):
    camera_or_404(camera_id)
    t0, t1 = window(from_, to, 24)
    return agent_tools.camera_gaps({"camera_id": camera_id, "time_from": t0, "time_to": t1})


@router.get("/cameras/{camera_id}/tracks")
def recent_tracks(camera_id: str, request_token: str = Depends(require_token), limit: int = 24,
                  from_: str | None = Query(None, alias="from"), to: str | None = None):
    camera_or_404(camera_id)
    t0, t1 = window(from_, to, 24 * 7)
    rows = db.fetch_all("SELECT id, cls, t_start, t_end, zone_path, caption, crop_keys FROM root_tracks "
                        "WHERE camera_id=%s AND t_start BETWEEN %s AND %s ORDER BY t_start DESC LIMIT %s",
                        (camera_id, t0, t1, min(limit, 100)))
    return [{"track_id": r["id"], "cls": r["cls"], "t_start": to_local(r["t_start"]).isoformat(),
             "t_end": to_local(r["t_end"]).isoformat(), "zones": r["zone_path"], "caption": r["caption"],
             "thumb_url": storage.url(r["crop_keys"][0], request_token) if r["crop_keys"] else None} for r in rows]


@router.post("/cameras/{camera_id}/start")
def start_edge(camera_id: str):
    cam = camera_or_404(camera_id)
    if cam["kind"] == "file":
        args = ["--simulate-live", "--loop"]
        status = get_manager().start(camera_id, args=args, live=True)
    else:
        status = get_manager().start(camera_id, live=True)
    return {"status": status, **get_manager().status(camera_id)}


@router.post("/cameras/{camera_id}/stop")
def stop_edge(camera_id: str):
    camera_or_404(camera_id)
    return {"stopped": get_manager().stop(camera_id)}


@router.get("/cameras/{camera_id}/edge")
def edge_status(camera_id: str):
    camera_or_404(camera_id)
    return get_manager().status(camera_id)


@router.get("/cameras/{camera_id}/progress")
def progress(camera_id: str):
    camera_or_404(camera_id)
    job = db.fetch_one("SELECT * FROM jobs WHERE camera_id=%s ORDER BY id DESC LIMIT 1", (camera_id,))
    tracks = db.fetch_val("SELECT count(*) FROM root_tracks WHERE camera_id=%s", (camera_id,))
    enriched = db.fetch_val("SELECT count(*) FROM root_tracks WHERE camera_id=%s AND enriched", (camera_id,))
    if not job:
        return {"state": "ready", "processed_seconds": 0, "duration_seconds": 0, "tracks": tracks, "enriched": enriched,
                "error": None, "note": None}
    return {"state": job["state"], "processed_seconds": round(job["processed_s"] or 0, 1),
            "duration_seconds": round(job["duration_s"] or 0, 1), "tracks": tracks, "enriched": enriched,
            "error": job["error"], "note": job.get("note"), "job_id": job["id"]}


def lan_ip() -> str | None:
    """The laptop's LAN address (a phone on the same Wi-Fi can't reach 'localhost'). No packet is sent."""
    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sk:
            sk.connect(("10.255.255.255", 1))
            ip = sk.getsockname()[0]
        return None if ip.startswith("127.") else ip
    except OSError:
        return None


@router.get("/phone-setup/{camera_id}")
def phone_setup(camera_id: str):
    """Connection URLs for Larix Broadcaster and the RTSP source the edge reads."""
    s = get_settings()
    host = s.PUBLIC_HOST or s.API_BASE_URL.split("//")[-1].split(":")[0].split("/")[0]
    if host in ("localhost", "127.0.0.1", "0.0.0.0", ""):
        host = lan_ip() or host
    return {"srt": f"srt://{host}:8890?streamid=publish:{camera_id}", "rtmp": f"rtmp://{host}/{camera_id}",
            "source_url": f"rtsp://{s.MEDIAMTX_HOST}:8554/{camera_id}", "host": host}
