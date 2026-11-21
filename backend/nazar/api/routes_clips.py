"""Clips cut lazily from segments; the track path is returned so the web app draws the box on a canvas."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from ..core import db, storage
from ..core.timeutil import dt_to_ms, parse_local
from .auth import require_token
from .clips import NoFootage, cut, reel, track_window
from .deps import camera_or_404, http_error

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])


@router.get("/clips/track/{track_id}")
def clip_for_track(track_id: int, at: str | None = None, token: str = Depends(require_token)):
    tr = db.fetch_one("SELECT id, camera_id, cls, t_start, t_end, path, merged_into FROM tracks WHERE id=%s", (track_id,))
    if not tr:
        raise http_error(404, "track not found")
    # include merged children's paths so the box keeps going across a stitched ID switch
    paths = [tr["path"] or []]
    for ch in db.fetch_all("SELECT path, t_start, t_end FROM tracks WHERE merged_into=%s ORDER BY t_start", (track_id,)):
        paths.append(ch["path"] or [])
        tr["t_start"] = min(tr["t_start"], ch["t_start"])
        tr["t_end"] = max(tr["t_end"], ch["t_end"])
    first_ev = db.fetch_one("SELECT min(t) AS t FROM events WHERE track_id=%s", (track_id,))
    at_dt = parse_local(at) if at else None
    t0, t1 = track_window(tr, at_dt, first_ev["t"] if first_ev else None)
    try:
        c = cut(tr["camera_id"], t0, t1)
    except NoFootage as e:
        raise http_error(404, str(e))
    lo, hi = c["t0_ms"], c["t1_ms"]
    path = sorted([p for ps in paths for p in ps if lo <= p[0] <= hi], key=lambda p: p[0])
    return {"url": storage.url(c["key"], token), "poster_url": storage.url(c.get("poster_key"), token), "t0_ms": lo,
            "t1_ms": hi, "path": path, "camera_id": tr["camera_id"], "track_id": track_id, "cls": tr["cls"]}


@router.get("/clips/range")
def clip_range(camera_id: str, from_: str = Query(..., alias="from"), to: str = Query(...),
               token: str = Depends(require_token)):
    camera_or_404(camera_id)
    t0, t1 = parse_local(from_), parse_local(to)
    if t1 <= t0:
        raise http_error(400, "to must be after from")
    if (t1 - t0) > timedelta(seconds=60):
        t1 = t0 + timedelta(seconds=60)
    try:
        c = cut(camera_id, t0, t1)
    except NoFootage as e:
        raise http_error(404, str(e))
    return {"url": storage.url(c["key"], token), "poster_url": storage.url(c.get("poster_key"), token),
            "t0_ms": c["t0_ms"], "t1_ms": c["t1_ms"], "path": [], "camera_id": camera_id, "requested_from_ms": dt_to_ms(t0)}


class ReelIn(BaseModel):
    track_ids: list[int] = Field(min_length=1, max_length=200)
    total: int | None = None


@router.post("/clips/reel")
def proof_reel(body: ReelIn, token: str = Depends(require_token)):
    """Proof reel of counted moments: 2.5 s per track (its first sighting), max 60 s, captioned 'k/N · HH:MM'."""
    rows = db.fetch_all("SELECT id, camera_id, t_start FROM tracks WHERE id = ANY(%s)", (body.track_ids,))
    by = {r["id"]: r for r in rows}
    items = [{"camera_id": by[i]["camera_id"], "t": by[i]["t_start"], "track_id": i} for i in body.track_ids if i in by]
    items.sort(key=lambda x: x["t"])
    try:
        r = reel(items, total=body.total or len(items))
    except NoFootage as e:
        raise http_error(404, str(e))
    return {"url": storage.url(r["key"], token), "poster_url": storage.url(r.get("poster_key"), token),
            "moments": r["moments"], "total": body.total or len(items)}
