"""Agent v2 tools (W6.1): visual search + verification, journey, describe clip, look now, compare periods, heatmap,
security events. Facts come from SQL / the local index; levels from server code only."""
from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import cv2
import numpy as np
from pydantic import BaseModel

from ..core import db, storage
from ..core.config import get_settings
from ..core.geometry import anchor_point
from ..core.timeutil import to_local
from . import agent_tools, visual
from .agent_tools import _t

log = logging.getLogger("nazar.agent_tools2")


# ---- visual search ------------------------------------------------------------------------------------------
def visual_search_tool(p: dict, ref: str) -> dict:
    text = (p.get("text") or "").strip()
    t_from, t_to = _t(p["time_from"]), _t(p["time_to"])
    vec = visual.query_vector(text=text)
    hits = visual.search(vec, t_from=t_from, t_to=t_to, camera_ids=p.get("camera_ids"), cls=p.get("cls"),
                         limit=max(4, min(int(p.get("limit") or 8), 12)))
    if hits and p.get("verify", True):
        try:
            visual.verify(p.get("verify_question") or text, hits, user_waiting=True, ref=ref, k=6)
        except Exception as e:
            log.warning("verify failed: %s", e)
    return {"hits": hits, "matched": len(hits),
            "probable": sum(1 for h in hits if h["level"] == "probable"),
            "note": None if hits else "nothing similar in the visual index for that time"}


def journey_tool(p: dict) -> dict:
    return visual.journey(int(p["track_id"]), hours=float(p.get("hours") or 24))


# ---- describe a clip ----------------------------------------------------------------------------------------
class ClipDescription(BaseModel):
    description: str
    activity: str


DESCRIBE_SYSTEM = """You describe short CCTV moments for a shop/home owner from a few face-blurred frames in time
order. 2-3 plain sentences, English: who does what (by clothing/objects only), where, what changes. Never identify
people, never describe faces, ethnicity, religion, caste or age beyond child/adult. If unclear, say so."""


def _frames_for(camera_id: str, t0: datetime, t1: datetime, k: int = 6) -> list[str]:
    rows = db.fetch_all("SELECT key FROM keyframes WHERE camera_id=%s AND t BETWEEN %s AND %s ORDER BY t",
                        (camera_id, t0, t1))
    if len(rows) > k:
        idx = np.linspace(0, len(rows) - 1, k).round().astype(int)
        rows = [rows[i] for i in idx]
    return [r["key"] for r in rows if storage.local_path(r["key"]).exists()]


def describe_clip(p: dict, ref: str) -> dict:
    from ..core.openai_client import _jpeg_data_url, get_ai

    if p.get("track_id"):
        tr = db.fetch_one("SELECT camera_id, t_start, t_end, crop_keys FROM tracks WHERE id=%s", (int(p["track_id"]),))
        if not tr:
            return {"error": "track not found"}
        cam, t0, t1 = tr["camera_id"], tr["t_start"] - timedelta(seconds=2), tr["t_end"] + timedelta(seconds=2)
        extra = [k for k in (tr["crop_keys"] or [])[:2]]
    else:
        cam = p["camera_id"]
        t = _t(p["time"])
        t0, t1 = t - timedelta(seconds=15), t + timedelta(seconds=15)
        extra = []
    keys = _frames_for(cam, t0, t1) or extra
    if not keys:
        return {"error": "no stored frames for that moment"}
    content: list[dict] = [{"type": "input_text", "text": f"{len(keys)} frames, {to_local(t0):%H:%M:%S} to {to_local(t1):%H:%M:%S}."}]
    for k in keys:
        content.append({"type": "input_image", "image_url": _jpeg_data_url(storage.local_path(k).read_bytes()), "detail": "low"})
    s = get_settings()
    res, _ = get_ai().parse(s.OPENAI_VISION_MODEL, [{"role": "user", "content": content}], ClipDescription,
                            kind="describe", instructions=DESCRIBE_SYSTEM, camera_id=cam, ref=ref, images=len(keys),
                            max_output_tokens=600, reasoning=s.VISION_REASONING_EFFORT or None)
    return {"camera_id": cam, "from": to_local(t0).isoformat(), "to": to_local(t1).isoformat(),
            "description": res.description, "activity": res.activity, "frames": len(keys), "ai_generated": True,
            "level": "candidate"}


# ---- look now --------------------------------------------------------------------------------------------------
class LookAnswer(BaseModel):
    answer: str
    yes: bool | None


def look_now(p: dict, ref: str) -> dict:
    """Current state of a camera: tracker counts (facts) + optionally a vision answer on the latest blurred frame."""
    from ..core.openai_client import _jpeg_data_url, get_ai

    cam = p["camera_id"]
    snap = storage.local_path(f"live/{cam}.jpg")
    age = time.time() - snap.stat().st_mtime if snap.exists() else None
    live = age is not None and age < 30
    counts = db.fetch_all("SELECT cls, count(*) n FROM tracks WHERE camera_id=%s AND active AND updated_at > now() - "
                          "interval '6 seconds' GROUP BY cls", (cam,)) if live else []
    out: dict[str, Any] = {"camera_id": cam, "live": live,
                           "now_counts": {r["cls"]: int(r["n"]) for r in counts}, "level": "confirmed"}
    if not live:
        kf = db.fetch_one("SELECT key, t FROM keyframes WHERE camera_id=%s ORDER BY t DESC LIMIT 1", (cam,))
        out["note"] = "camera is not live right now" + (f"; latest stored frame {to_local(kf['t']):%d %b %H:%M}" if kf else "")
        img_path = storage.local_path(kf["key"]) if kf else None
        out["frame_time"] = to_local(kf["t"]).isoformat() if kf else None
    else:
        img_path = snap
    q = (p.get("question") or "").strip()
    if q and p.get("needs_vision") and img_path is not None and img_path.exists():
        s = get_settings()
        res, _ = get_ai().parse(s.OPENAI_VISION_MODEL, [{"role": "user", "content": [
            {"type": "input_text", "text": f"Question about this face-blurred CCTV frame: {q}"},
            {"type": "input_image", "image_url": _jpeg_data_url(img_path.read_bytes()), "detail": "low"}]}],
            LookAnswer, kind="look", instructions="Answer from the image only, 1 short English sentence. Never "
            "count people (the tracker does that) and never identify anyone.", camera_id=cam, ref=ref, images=1,
            max_output_tokens=300, reasoning=s.VISION_REASONING_EFFORT or None)
        out["vision_answer"] = res.answer
        out["vision_yes"] = res.yes
        out["vision_level"] = "candidate"
        out["ai_generated"] = True
    out["image_key"] = None
    if img_path is not None and img_path.exists():
        key = f"look/{cam}_{int(time.time())}.jpg"
        storage.put_bytes(img_path.read_bytes(), key)
        out["image_key"] = key
    return out


# ---- compare periods -------------------------------------------------------------------------------------------
def compare_periods(p: dict) -> dict:
    base = {k: p.get(k) for k in ("camera_id", "zone", "cls", "event")}
    a = agent_tools.count_events({**base, "time_from": p["a_from"], "time_to": p["a_to"]})
    b = agent_tools.count_events({**base, "time_from": p["b_from"], "time_to": p["b_to"]})
    change = None if b["value"] == 0 else round((a["value"] - b["value"]) * 100.0 / b["value"], 1)
    return {"a": {"value": a["value"], "from": a["time_from"], "to": a["time_to"], "label": p.get("a_label") or "A"},
            "b": {"value": b["value"], "from": b["time_from"], "to": b["time_to"], "label": p.get("b_label") or "B"},
            "change_pct": change, "label": a["label"], "level": "confirmed"}


# ---- heatmap -------------------------------------------------------------------------------------------------------
def heatmap(p: dict) -> dict:
    cam = p["camera_id"]
    cls = p.get("cls") or "person"
    t_from, t_to = _t(p["time_from"]), _t(p["time_to"])
    rows = db.fetch_all("SELECT path, cls FROM tracks WHERE camera_id=%s AND cls=%s AND t_end >= %s AND t_start <= %s "
                        "AND merged_into IS NULL", (cam, cls, t_from, t_to))
    kf = db.fetch_one("SELECT key FROM keyframes WHERE camera_id=%s AND t BETWEEN %s AND %s ORDER BY persons ASC, t "
                      "LIMIT 1", (cam, t_from, t_to)) or db.fetch_one(
        "SELECT key FROM keyframes WHERE camera_id=%s ORDER BY t DESC LIMIT 1", (cam,))
    base = cv2.imread(str(storage.local_path(kf["key"]))) if kf else None
    if base is None:
        base = np.full((288, 512, 3), 40, np.uint8)
    h, w = base.shape[:2]
    gw, gh = 128, max(1, int(128 * h / w))
    grid = np.zeros((gh, gw), np.float32)
    n_pts = 0
    lo, hi = t_from.timestamp() * 1000, t_to.timestamp() * 1000
    for r in rows:
        for pt in r["path"] or []:
            if lo <= pt[0] <= hi:
                x, y = anchor_point(cls, pt[1:5])
                grid[min(gh - 1, max(0, int(y * gh))), min(gw - 1, max(0, int(x * gw)))] += 1.0  # 5 Hz -> 0.2 s each
                n_pts += 1
    if n_pts == 0:
        return {"camera_id": cam, "note": "no movement recorded in that window", "tracks": len(rows)}
    grid = cv2.GaussianBlur(grid, (0, 0), 2.2)
    norm = (255 * grid / max(grid.max(), 1e-6)).astype(np.uint8)
    heat = cv2.applyColorMap(cv2.resize(norm, (w, h), interpolation=cv2.INTER_CUBIC), cv2.COLORMAP_JET)
    mask = cv2.resize(norm, (w, h))[..., None].astype(np.float32) / 255.0
    out = (base * (1 - 0.6 * mask) + heat * (0.6 * mask)).astype(np.uint8)
    ok, buf = cv2.imencode(".png", out)
    key = f"heatmaps/{cam}_{hashlib.sha1(f'{cam}{cls}{lo}{hi}'.encode()).hexdigest()[:12]}.png"
    storage.put_bytes(buf.tobytes(), key)
    return {"camera_id": cam, "cls": cls, "tracks": len(rows), "seconds": round(n_pts / 5.0), "image_key": key,
            "from": to_local(t_from).isoformat(), "to": to_local(t_to).isoformat(), "level": "confirmed"}


# ---- security events --------------------------------------------------------------------------------------------
def list_events(p: dict) -> dict:
    t_from, t_to = _t(p["time_from"]), _t(p["time_to"])
    where, params = ["t_start <= %s", "t_end >= %s"], [t_to, t_from]
    if p.get("camera_id"):
        where.append("camera_id=%s")
        params.append(p["camera_id"])
    if p.get("types"):
        where.append("type = ANY(%s)")
        params.append(list(p["types"]))
    rows = db.fetch_all(f"SELECT id, camera_id, type, t_start, t_end, track_ids, level, reason FROM sec_events "
                        f"WHERE {' AND '.join(where)} ORDER BY t_start LIMIT 50", params)
    events = [{"id": r["id"], "camera_id": r["camera_id"], "type": r["type"], "t": to_local(r["t_start"]).isoformat(),
               "track_ids": list(r["track_ids"] or []), "level": r["level"], "reason": r["reason"]} for r in rows]
    anomalies = []
    try:
        from ..worker.security import anomalies_between

        anomalies = anomalies_between(p.get("camera_id"), t_from, t_to)
    except Exception as e:
        log.debug("anomalies unavailable: %s", e)
    return {"events": events, "anomalies": anomalies, "count": len(events)}
