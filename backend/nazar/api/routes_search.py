"""Debug search/count (same params as the agent tools), track details and 'find this person again'."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from pgvector import Vector

from ..core import db, storage
from ..core.appearance import as_list
from ..core.levels import sort_key
from ..core.timeutil import to_local
from . import agent_tools
from .auth import require_token
from .deps import http_error, window

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])
SIMILAR_MIN = 0.80


@router.get("/search")
def search(from_: str | None = Query(None, alias="from"), to: str | None = None, camera_id: list[str] | None = Query(None),
           cls: list[str] | None = Query(None), zone: list[str] | None = Query(None), upper_color: str | None = None,
           lower_color: str | None = None, carrying: list[str] | None = Query(None), vehicle_type: str | None = None,
           vehicle_color: str | None = None, action: str | None = None, text: str | None = None, limit: int = 8):
    t0, t1 = window(from_, to, 24)
    return agent_tools.search_tracks({
        "camera_ids": camera_id, "time_from": t0, "time_to": t1, "cls": cls, "zones": zone, "upper_color": upper_color,
        "lower_color": lower_color, "carrying": carrying, "vehicle_type": vehicle_type, "vehicle_color": vehicle_color,
        "action": action, "text": text, "limit": limit}, ref="debug-search")


@router.get("/count")
def count(camera_id: str | None = None, zone: str | None = None, cls: str = "person", event: str = "enter",
          from_: str | None = Query(None, alias="from"), to: str | None = None, bucket: str = "hour"):
    t0, t1 = window(from_, to, 24)
    return agent_tools.count_events({"camera_id": camera_id, "zone": zone, "cls": cls, "event": event,
                                     "time_from": t0, "time_to": t1, "bucket": bucket})


def track_out(r: dict, token: str) -> dict:
    return {"track_id": r["id"], "camera_id": r["camera_id"], "cls": r["cls"],
            "t_start": to_local(r["t_start"]).isoformat(), "t_end": to_local(r["t_end"]).isoformat(),
            "zones": list(r.get("zone_path") or []), "caption": r.get("caption"), "attrs": r.get("attrs"),
            "crops": [storage.url(k, token) for k in (r.get("crop_keys") or [])],
            "thumb_url": storage.url(r["crop_keys"][0], token) if r.get("crop_keys") else None}


@router.get("/tracks/{track_id}")
def get_track(track_id: int, token: str = Depends(require_token)):
    r = db.fetch_one("SELECT * FROM tracks WHERE id=%s", (track_id,))
    if not r:
        raise http_error(404, "track not found")
    out = track_out(r, token)
    out["path"] = r["path"]
    out["merged_into"] = r["merged_into"]
    out["events"] = [{"type": e["type"], "zone": e["zone"], "t": to_local(e["t"]).isoformat(), "meta": e["meta"]}
                     for e in db.fetch_all("SELECT type, zone, t, meta FROM events WHERE track_id=%s ORDER BY t", (track_id,))]
    return out


@router.get("/tracks/{track_id}/similar")
def similar(track_id: int, hours: float = 24, all_cameras: bool = False, token: str = Depends(require_token)):
    """Find this person again: appearance-vector search. Probable only if caption colours also agree."""
    r = db.fetch_one("SELECT id, camera_id, cls, t_start, appearance, attrs, merged_into FROM tracks WHERE id=%s", (track_id,))
    if not r:
        raise http_error(404, "track not found")
    if r["appearance"] is None:
        return {"track_id": track_id, "results": [], "note": "this track has no appearance fingerprint"}
    root = r["merged_into"] or r["id"]
    vec = Vector(as_list(r["appearance"]))
    params = [vec, r["cls"], r["t_start"] - timedelta(hours=hours), r["t_start"] + timedelta(hours=hours), root, root]
    cam_sql = ""
    if not all_cameras:
        cam_sql = "AND camera_id=%s"
        params.append(r["camera_id"])
    rows = db.fetch_all(
        f"""SELECT id, camera_id, cls, t_start, t_end, zone_path, caption, attrs, crop_keys,
                   1 - (appearance <=> %s) AS sim
              FROM root_tracks
             WHERE cls=%s AND appearance IS NOT NULL AND t_start BETWEEN %s AND %s AND id <> %s
               AND id NOT IN (SELECT id FROM tracks WHERE merged_into=%s) {cam_sql}
             ORDER BY appearance <=> %s LIMIT 10""", [*params, vec])
    mine = r["attrs"] or {}
    out = []
    for x in rows:
        sim = float(x["sim"])
        if sim < SIMILAR_MIN:
            continue
        a = x["attrs"] or {}
        colours_agree = bool(mine and a and mine.get("upper_color") not in (None, "unknown")
                             and a.get("upper_color") == mine.get("upper_color")
                             and a.get("lower_color") == mine.get("lower_color"))
        level = "probable" if colours_agree else "candidate"
        why = f"appearance {sim:.2f}" + (", colours agree" if colours_agree else "")
        out.append({**track_out(x, token), "level": level, "score": round(sim, 3), "why": why})
    out.sort(key=lambda o: sort_key(o["level"], o["score"]))
    return {"track_id": track_id, "results": out}
