"""Server-side tools for the query agent (and the debug/timeline endpoints).

Facts come from SQL; evidence levels come only from nazar.core.levels.assign_level.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from pgvector import Vector

from ..core import db
from ..core.geometry import polygon_for
from ..core.levels import assign_level, sort_key
from ..core.rules import presence_seconds
from ..core.timeutil import parse_local, to_local, tz

BAG_WORDS = {"backpack", "handbag", "suitcase", "bag"}
BOX_WORDS = {"box", "parcel"}
TWO_WHEELERS = {"motorcycle", "scooter"}
MAX_GAP_S = 15.0


def _t(v: Any) -> datetime:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=tz())
    return parse_local(str(v))


def _origin() -> datetime:
    return datetime(2000, 1, 1, tzinfo=tz())


def _bucket_interval(bucket: str | None) -> timedelta:
    return timedelta(minutes=15) if bucket == "15min" else timedelta(hours=1)


def _fill_series(counts: dict[datetime, int], t_from: datetime, t_to: datetime, step: timedelta) -> list[dict]:
    o = _origin()
    start = o + ((t_from - o) // step) * step
    out = []
    t = start
    while t < t_to and len(out) < 500:
        out.append({"t": to_local(t).isoformat(), "n": int(counts.get(t, 0))})
        t += step
    return out


def _zone_labels(camera_id: str | None) -> dict[str, str]:
    rows = db.fetch_all("SELECT zones FROM cameras" + (" WHERE id=%s" if camera_id else ""),
                        (camera_id,) if camera_id else None)
    out: dict[str, str] = {}
    for r in rows:
        for z in r["zones"] or []:
            out[z["name"]] = z.get("label") or z["name"]
    return out


# ---------------------------------------------------------------------------------------------- search
def _attr_match(attrs: dict | None, p: dict) -> tuple[int, int, list[str]]:
    req = 0
    hit = 0
    why: list[str] = []
    a = attrs or {}

    def check(name: str, ok: bool, shown: str):
        nonlocal req, hit
        req += 1
        if ok:
            hit += 1
        why.append(f"{name}={shown} {'✓' if ok else '✗'}")

    for k in ("upper_color", "lower_color", "vehicle_color"):
        if p.get(k):
            check(k.split("_")[0] if k != "vehicle_color" else "vehicle colour", a.get(k) == p[k], p[k])
    if p.get("vehicle_type"):
        want = p["vehicle_type"]
        have = a.get("vehicle_type")
        ok = have == want or (want in TWO_WHEELERS and have in TWO_WHEELERS)
        check("vehicle", ok, want)
    if p.get("action"):
        check("action", a.get("action") == p["action"], p["action"])
    for item in p.get("carrying") or []:
        have = set(a.get("carrying") or [])
        if item in BAG_WORDS:
            ok = bool(have & BAG_WORDS)
        elif item in BOX_WORDS:
            ok = bool(have & BOX_WORDS)
        else:
            ok = item in have
        check("carrying", ok, item)
    return req, hit, why


def search_tracks(p: dict, ai=None, ref: str | None = None) -> dict:
    t_from, t_to = _t(p["time_from"]), _t(p["time_to"])
    limit = max(1, min(int(p.get("limit") or 8), 12))
    where = ["t_end >= %s", "t_start <= %s"]
    params: list[Any] = [t_from, t_to]
    if p.get("camera_ids"):
        where.append("camera_id = ANY(%s)")
        params.append(list(p["camera_ids"]))
    if p.get("cls"):
        cls = set(p["cls"])
        if "any_bag" in cls or "bag" in cls:
            cls |= {"backpack", "handbag", "suitcase"}
        where.append("cls = ANY(%s)")
        params.append(sorted(cls))
    if p.get("zones"):
        where.append("zone_path && %s")
        params.append(list(p["zones"]))
    attr_keys = ("upper_color", "lower_color", "carrying", "vehicle_type", "vehicle_color", "action")
    has_attrs = any(p.get(k) for k in attr_keys)
    text = (p.get("text") or "").strip()
    structural = not has_attrs and not text
    cols = "id, camera_id, cls, t_start, t_end, zone_path, caption, attrs, crop_keys, enriched"
    sql_where = " AND ".join(where)
    if text:
        if ai is None:
            from ..core.openai_client import get_ai

            ai = get_ai()
        q = ai.embed([text], kind="embed", ref=ref or "search")[0]
        rows = db.fetch_all(
            f"SELECT {cols}, CASE WHEN caption_emb IS NULL THEN NULL ELSE 1 - (caption_emb <=> %s) END AS sim "
            f"FROM root_tracks WHERE {sql_where} ORDER BY caption_emb <=> %s NULLS LAST LIMIT 300",
            [Vector(q), *params, Vector(q)])
    else:
        rows = db.fetch_all(f"SELECT {cols}, NULL::float AS sim FROM root_tracks WHERE {sql_where} "
                            f"ORDER BY t_start LIMIT 300", params)
    results = []
    for r in rows:
        sim = float(r["sim"]) if r["sim"] is not None else None
        req, hit, why = _attr_match(r["attrs"], p) if has_attrs else (0, 0, [])
        if has_attrs and not r["enriched"]:
            continue  # no description yet -> can't claim an attribute match
        level = assign_level(structural_only=structural, sim=sim, attr_requested=req, attr_matched=hit)
        if level is None:
            continue
        if sim is not None:
            why.append(f"sim {sim:.2f}")
        if structural:
            why.append("tracker fact: " + (f"in {', '.join(r['zone_path'])}" if r["zone_path"] else "seen on camera"))
        score = (sim or 0.0) + (hit / req if req else 0.0)
        results.append({
            "track_id": r["id"], "camera_id": r["camera_id"], "cls": r["cls"],
            "t_start": to_local(r["t_start"]).isoformat(), "t_end": to_local(r["t_end"]).isoformat(),
            "zones": list(r["zone_path"] or []), "caption": r["caption"], "level": level, "score": round(score, 3),
            "why": ", ".join(why),
        })
    if structural:
        results.sort(key=lambda x: x["t_start"])
    else:
        results.sort(key=lambda x: sort_key(x["level"], x["score"]))
    out: dict[str, Any] = {"results": results[:limit], "matched": len(results)}
    if structural:
        out["total"] = db.fetch_val(f"SELECT count(*) FROM root_tracks WHERE {sql_where}", params)
    if not results:
        out["note"] = "no matching tracks"
    return out


# ---------------------------------------------------------------------------------------------- counts
def count_events(p: dict) -> dict:
    cam = p.get("camera_id") or None
    zone = p.get("zone") or None
    cls = p.get("cls") or "person"
    event = p.get("event") or "enter"
    t_from, t_to = _t(p["time_from"]), _t(p["time_to"])
    step = _bucket_interval(p.get("bucket"))
    classes = ["backpack", "handbag", "suitcase"] if cls in ("any_bag", "bag") else [cls]
    if zone is None and event in ("enter", "exit"):
        event = "present"
    if event == "present":
        where = ["cls = ANY(%s)", "t_end >= %s", "t_start <= %s"]
        params: list[Any] = [classes, t_from, t_to]
        if cam:
            where.append("camera_id=%s")
            params.append(cam)
        if zone:
            where.append("zone_path @> ARRAY[%s]::text[]")
            params.append(zone)
        rows = db.fetch_all(
            f"SELECT date_bin(%s, GREATEST(t_start, %s), %s) AS b, count(*) AS n FROM root_tracks "
            f"WHERE {' AND '.join(where)} GROUP BY 1", [step, t_from, _origin(), *params])
    else:
        where = ["e.type=%s", "t.cls = ANY(%s)", "e.t BETWEEN %s AND %s", "e.zone=%s"]
        params = [event, classes, t_from, t_to, zone]
        if cam:
            where.append("e.camera_id=%s")
            params.append(cam)
        rows = db.fetch_all(
            f"""SELECT date_bin(%s, first_t, %s) AS b, count(*) AS n FROM (
                  SELECT COALESCE(t.merged_into, t.id) AS root, min(e.t) AS first_t
                    FROM events e JOIN tracks t ON t.id = e.track_id
                   WHERE {' AND '.join(where)} GROUP BY 1) x GROUP BY 1""", [step, _origin(), *params])
    counts = {r["b"]: int(r["n"]) for r in rows}
    value = sum(counts.values())
    labels = _zone_labels(cam)
    noun = {"person": "people", "car": "cars", "motorcycle": "motorcycles", "bicycle": "bicycles",
            "truck": "trucks", "bus": "buses"}.get(cls, f"{cls} objects")
    zl = labels.get(zone, zone) if zone else None
    verb = {"present": "seen", "enter": "entered", "exit": "left", "dwell": "stayed 10 s+ at"}[event]
    label = f"{noun} {verb}" + (f" {zl}" if zl and event != "present" else (f" in {zl}" if zl else ""))
    return {"value": value, "label": label, "level": "confirmed", "series": _fill_series(counts, t_from, t_to, step),
            "bucket": "15min" if p.get("bucket") == "15min" else "hour", "camera_id": cam, "zone": zone, "cls": cls,
            "event": event, "time_from": to_local(t_from).isoformat(), "time_to": to_local(t_to).isoformat()}


def peak_occupancy(p: dict) -> dict:
    cam = p["camera_id"]
    zone = p.get("zone") or None
    cls = p.get("cls") or "person"
    t_from, t_to = _t(p["time_from"]), _t(p["time_to"])
    tracks = db.fetch_all("SELECT id, cls, path, t_start, t_end FROM tracks WHERE camera_id=%s AND cls=%s "
                          "AND t_end >= %s AND t_start <= %s", (cam, cls, t_from, t_to))
    zones = (db.fetch_one("SELECT zones FROM cameras WHERE id=%s", (cam,)) or {}).get("zones") or []
    poly = polygon_for(zone, zones) if zone else polygon_for("anywhere", zones)
    lo, hi = int(t_from.timestamp()), int(t_to.timestamp())
    per: dict[int, int] = {}
    for tr in tracks:
        for s in presence_seconds(tr, poly):
            if lo <= s <= hi:
                per[s] = per.get(s, 0) + 1
    if not per:
        return {"max": 0, "at": None, "level": "confirmed", "camera_id": cam, "zone": zone}
    s_max = max(per, key=lambda s: (per[s], -s))
    return {"max": per[s_max], "at": to_local(datetime.fromtimestamp(s_max, tz=timezone.utc)).isoformat(),
            "level": "confirmed", "camera_id": cam, "zone": zone, "cls": cls}


def camera_gaps(p: dict) -> dict:
    """Periods with no stored footage (no segment) inside the window - honest 'camera was offline'."""
    cam = p["camera_id"]
    t_from, t_to = _t(p["time_from"]), _t(p["time_to"])
    segs = db.fetch_all("SELECT t_start, t_end FROM segments WHERE camera_id=%s AND t_end >= %s AND t_start <= %s "
                        "ORDER BY t_start", (cam, t_from, t_to))
    gaps = []
    cur = t_from
    for s in segs:
        if (s["t_start"] - cur).total_seconds() > MAX_GAP_S:
            gaps.append((cur, s["t_start"]))
        cur = max(cur, s["t_end"])
    if (t_to - cur).total_seconds() > MAX_GAP_S:
        gaps.append((cur, min(t_to, datetime.now(timezone.utc))))
    out = [{"from": to_local(a).isoformat(), "to": to_local(b).isoformat(),
            "minutes": round((b - a).total_seconds() / 60, 1)} for a, b in gaps if b > a]
    return {"camera_id": cam, "gaps": out, "offline_minutes": round(sum(g["minutes"] for g in out), 1)}


def coverage(camera_id: str | None = None) -> list[dict]:
    rows = db.fetch_all("SELECT camera_id, min(t_start) AS t0, max(t_end) AS t1 FROM segments "
                        + ("WHERE camera_id=%s " if camera_id else "") + "GROUP BY camera_id",
                        (camera_id,) if camera_id else None)
    return [{"camera_id": r["camera_id"], "from": to_local(r["t0"]).isoformat(), "to": to_local(r["t1"]).isoformat()}
            for r in rows]
