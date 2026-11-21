"""Security analytics (W5): heuristics over stored paths -> sec_events (Candidates), an optional short AI check of
blurred keyframes upgrades them to Probable. Plus the hour-of-week anomaly baseline and the morning digest.

Detectors are pure functions (unit-tested). Tracker facts (after-hours presence, crowding counts) are Confirmed.
"""
from __future__ import annotations

import logging
import math
import statistics
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from psycopg.types.json import Jsonb

from ..core import db
from ..core.geometry import FULL_FRAME, box_gap, center
from ..core.rules import RuleSpec, object_removed_hits
from ..core.timeutil import ms_to_dt, to_local, tz

log = logging.getLogger("nazar.security")
BAGS = ("backpack", "handbag", "suitcase")
LOITER_S = 90.0
LOITER_RADIUS = 0.12
RUN_BH_PER_S = 2.8  # body heights per second
RUN_MIN_S = 1.0
FALL_ASPECT = 1.2  # w/h of a lying person
FALL_MIN_S = 2.0
ABANDON_STATIONARY_S = 30.0
ABANDON_ALONE_S = 20.0
ABANDON_RADIUS = 0.10
CROWD_N = 8
SNATCH_CONTACT_S = 3.0
AFTER_HOURS = ("23:00", "06:00")
VERIFY_TYPES = {"possible_snatch", "abandoned_object", "fall", "running", "loitering", "object_removed"}
VERIFY_DAILY = 30

DESCRIBE = {
    "loitering": "someone lingering or waiting around in one place for a long time",
    "abandoned_object": "a bag or object left behind with nobody near it",
    "object_removed": "someone picking up or taking away a bag/object",
    "running": "a person running",
    "fall": "a person who has fallen down or is lying on the ground",
    "possible_snatch": "a snatching or theft: someone grabbing something from another person and leaving fast",
    "crowding": "a crowd",
    "after_hours": "a person present at night",
    "wrong_way": "someone going the wrong way",
}


# ---- pure detectors (paths are lists of [t_ms, x1, y1, x2, y2, conf, ...]) ------------------------------------------
def _speeds(path: list) -> list[tuple[int, float]]:
    """(t_ms, speed in body-heights per second) between consecutive points."""
    out = []
    for a, b in zip(path, path[1:]):
        dt = (b[0] - a[0]) / 1000.0
        if dt <= 0 or dt > 1.0:
            continue
        ca, cb = center(a[1:5]), center(b[1:5])
        bh = max(1e-3, ((a[4] - a[2]) + (b[4] - b[2])) / 2)
        out.append((b[0], math.hypot(cb[0] - ca[0], cb[1] - ca[1]) / bh / dt))
    return out


def detect_running(path: list, cls: str = "person") -> int | None:
    """t_ms when a person moved faster than RUN_BH_PER_S body heights/s for >= RUN_MIN_S (not vehicles)."""
    if cls != "person" or len(path) < 4:
        return None
    sp = _speeds(path)
    start = None
    for t, v in sp:
        tall = True
        if v >= RUN_BH_PER_S and tall:
            start = start or t
            if (t - start) / 1000.0 >= RUN_MIN_S:
                return start
        else:
            start = None
    return None


def detect_fall(path: list, cls: str = "person") -> int | None:
    """Upright (h/w > 1.6) then lying (w/h > FALL_ASPECT) for >= FALL_MIN_S within 5 s."""
    if cls != "person" or len(path) < 6:
        return None
    upright_t = None
    lying_start = None
    for p in path:
        w, h = p[3] - p[1], p[4] - p[2]
        if h <= 0 or w <= 0:
            continue
        if h / w > 1.6:
            upright_t = p[0]
            lying_start = None
        elif w / h > FALL_ASPECT and upright_t is not None and p[0] - upright_t <= 5000:
            lying_start = lying_start or p[0]
            if (p[0] - lying_start) / 1000.0 >= FALL_MIN_S:
                return lying_start
        elif w / h > FALL_ASPECT and lying_start is not None:
            if (p[0] - lying_start) / 1000.0 >= FALL_MIN_S:
                return lying_start
        else:
            lying_start = None
    return None


def detect_loitering(path: list, cls: str = "person", min_s: float = LOITER_S) -> int | None:
    """A person staying within LOITER_RADIUS of where they stood for >= min_s."""
    if cls != "person" or not path or (path[-1][0] - path[0][0]) / 1000.0 < min_s:
        return None
    i0 = 0
    for j in range(len(path)):
        c0, cj = center(path[i0][1:5]), center(path[j][1:5])
        if math.hypot(cj[0] - c0[0], cj[1] - c0[1]) > LOITER_RADIUS:
            i0 = j
            continue
        if (path[j][0] - path[i0][0]) / 1000.0 >= min_s:
            return int(path[i0][0])
    return None


def _box_at(path: list, t_ms: int, tol: int = 600):
    best, bd = None, tol + 1
    for p in path:
        d = abs(p[0] - t_ms)
        if d < bd:
            best, bd = p, d
    return best[1:5] if best else None


def detect_abandoned(obj: dict, persons: list[dict]) -> int | None:
    """Bag stationary >= ABANDON_STATIONARY_S and no person within ABANDON_RADIUS for >= ABANDON_ALONE_S."""
    path = obj.get("path") or []
    if obj.get("cls") not in BAGS or len(path) < 5:
        return None
    i0 = 0
    alone_since = None
    for j, p in enumerate(path):
        c0, cj = center(path[i0][1:5]), center(p[1:5])
        if math.hypot(cj[0] - c0[0], cj[1] - c0[1]) > 0.03:
            i0, alone_since = j, None
            continue
        if (p[0] - path[i0][0]) / 1000.0 < ABANDON_STATIONARY_S - ABANDON_ALONE_S:
            continue
        near = False
        for per in persons:
            b = _box_at(per.get("path") or [], int(p[0]))
            if b is not None and box_gap(p[1:5], b) <= ABANDON_RADIUS:
                near = True
                break
        if near:
            alone_since = None
            continue
        alone_since = alone_since or p[0]
        if (p[0] - path[i0][0]) / 1000.0 >= ABANDON_STATIONARY_S and (p[0] - alone_since) / 1000.0 >= ABANDON_ALONE_S:
            return int(alone_since)
    return None


def detect_snatch(a: dict, b: dict) -> int | None:
    """Two persons in brief close contact (<= SNATCH_CONTACT_S), then one of them speeds away (>2x own median, >1.5
    body heights/s) within 3 s. Returns contact time."""
    pa, pb = a.get("path") or [], b.get("path") or []
    if len(pa) < 5 or len(pb) < 5:
        return None
    contact = []
    for p in pa:
        q = _box_at(pb, int(p[0]), 300)
        if q is not None and box_gap(p[1:5], q) <= 0.015:
            contact.append(int(p[0]))
    if not contact:
        return None
    t0, t1 = contact[0], contact[-1]
    if (t1 - t0) / 1000.0 > SNATCH_CONTACT_S:
        return None  # a long conversation / walking together, not a grab
    for path in (pa, pb):
        sp = _speeds(path)
        if len(sp) < 4:
            continue
        med = statistics.median(v for _, v in sp)
        after = [v for t, v in sp if t1 < t <= t1 + 3000]
        if after and max(after) > max(1.5, 2.0 * med):
            return t0
    return None


def in_window(t_local: datetime, window=AFTER_HOURS) -> bool:
    hm = t_local.strftime("%H:%M")
    a, b = window
    return (a <= hm or hm < b) if a > b else (a <= hm < b)


# ---- event building -----------------------------------------------------------------------------------------------
def _record(camera_id: str, typ: str, t: datetime, t_end: datetime, track_ids: list[int], level: str, reason: str,
            meta: dict | None = None) -> int | None:
    row = db.fetch_one(
        "INSERT INTO sec_events(camera_id, type, t_start, t_end, track_ids, level, reason, meta) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (camera_id, type, t_start, track_ids) DO NOTHING RETURNING id",
        (camera_id, typ, t, t_end, sorted(track_ids), level, reason, Jsonb(meta or {})))
    return row["id"] if row else None


def analyze(camera_id: str, tracks: list[dict], neighbours: list[dict]) -> list[int]:
    """Run every detector over finished tracks of one camera; neighbours = other tracks overlapping in time."""
    created: list[int] = []
    persons = [t for t in neighbours if t["cls"] == "person"]
    for tr in tracks:
        path = tr["path"] or []
        if not path:
            continue
        cls = tr["cls"]
        end = ms_to_dt(path[-1][0])
        if (t := detect_running(path, cls)) is not None:
            created.append(_record(camera_id, "running", ms_to_dt(t), end, [tr["id"]], "candidate", "moved faster than a walk"))
        if (t := detect_fall(path, cls)) is not None:
            created.append(_record(camera_id, "fall", ms_to_dt(t), end, [tr["id"]], "candidate", "upright, then lying for 2 s+"))
        if (t := detect_loitering(path, cls)) is not None:
            created.append(_record(camera_id, "loitering", ms_to_dt(t), end, [tr["id"]], "candidate",
                                   f"stayed in one spot {int((path[-1][0] - t) / 1000)} s"))
        if cls in BAGS:
            if (t := detect_abandoned(tr, persons)) is not None:
                created.append(_record(camera_id, "abandoned_object", ms_to_dt(t), end, [tr["id"]], "candidate",
                                       "bag left still with nobody near"))
            spec = RuleSpec(camera_id=camera_id, trigger="object_removed", cls="any_bag", zone="anywhere")
            for h in object_removed_hits(spec, tr, [{"name": "anywhere", "polygon": FULL_FRAME}], persons):
                if h.actor_track_id:
                    created.append(_record(camera_id, "object_removed", ms_to_dt(h.t_ms), ms_to_dt(h.t_ms),
                                           [h.actor_track_id, tr["id"]], "candidate", "a person took a bag that was lying still"))
        if cls == "person" and in_window(to_local(ms_to_dt(path[0][0]))) and (path[-1][0] - path[0][0]) >= 1500:
            created.append(_record(camera_id, "after_hours", ms_to_dt(path[0][0]), end, [tr["id"]], "confirmed",
                                   f"person on camera after {AFTER_HOURS[0]}"))
    # pairwise: possible snatch (only persons overlapping in time)
    pers = [t for t in tracks if t["cls"] == "person"]
    for i, a in enumerate(pers):
        for b in persons:
            if b["id"] == a["id"] or (b in pers and pers.index(b) < i):
                continue
            if b["t_start"] > a["t_end"] or b["t_end"] < a["t_start"]:
                continue
            if (t := detect_snatch(a, b)) is not None:
                created.append(_record(camera_id, "possible_snatch", ms_to_dt(t), ms_to_dt(t + 3000), [a["id"], b["id"]],
                                       "candidate", "brief contact, then one person sped away"))
    return [c for c in created if c]


def crowding(camera_id: str, tracks: list[dict], n: int = CROWD_N) -> int | None:
    per: dict[int, int] = {}
    for tr in tracks:
        if tr["cls"] != "person":
            continue
        secs = {int(p[0] // 1000) for p in tr["path"] or []}
        for s in secs:
            per[s] = per.get(s, 0) + 1
    if not per:
        return None
    s_max = max(per, key=lambda s: (per[s], -s))
    if per[s_max] <= n:
        return None
    t = datetime.fromtimestamp(s_max, tz=timezone.utc)
    return _record(camera_id, "crowding", t, t, [], "confirmed", f"{per[s_max]} people at the same time (> {n})",
                   {"count": per[s_max]})


# ---- AI check (Flex, capped) ---------------------------------------------------------------------------------------
def verify_event(ev_id: int) -> str | None:
    from pydantic import BaseModel

    from ..core import storage, usage
    from ..core.config import get_settings
    from ..core.openai_client import _jpeg_data_url, get_ai

    class Check(BaseModel):
        match: str
        reason: str

    ev = db.fetch_one("SELECT * FROM sec_events WHERE id=%s", (ev_id,))
    if not ev or ev["type"] not in VERIFY_TYPES or ev["verified_by"]:
        return None
    ai = get_ai()
    if not ai.available():
        return None
    n_today = int(db.fetch_val("SELECT count(*) FROM usage WHERE kind='sec_check' AND at > now() - interval '1 day'") or 0)
    if n_today >= VERIFY_DAILY:
        return None
    t0, t1 = ev["t_start"] - timedelta(seconds=4), ev["t_end"] + timedelta(seconds=4)
    keys = [r["key"] for r in db.fetch_all("SELECT key FROM keyframes WHERE camera_id=%s AND t BETWEEN %s AND %s ORDER BY t",
                                          (ev["camera_id"], t0, t1))]
    if len(keys) > 6:
        keys = [keys[round(i * (len(keys) - 1) / 5)] for i in range(6)]
    keys = [k for k in keys if storage.local_path(k).exists()]
    if not keys:
        return None
    content: list[dict] = [{"type": "input_text", "text": f"Frames in time order. Does this show {DESCRIBE[ev['type']]}? "
                                                         "match: yes / no / unclear. reason <= 12 words."}]
    for k in keys:
        content.append({"type": "input_image", "image_url": _jpeg_data_url(storage.local_path(k).read_bytes()), "detail": "low"})
    s = get_settings()
    try:
        res, _ = ai.parse(s.OPENAI_VISION_MODEL, [{"role": "user", "content": content}], Check, kind="sec_check",
                          instructions="You check CCTV security events from face-blurred frames. Judge actions and objects "
                                       "only; never identify people.", camera_id=ev["camera_id"], ref=f"sec:{ev_id}",
                          images=len(keys), max_output_tokens=200, reasoning=s.VISION_REASONING_EFFORT or None, tier="flex")
    except Exception as e:
        log.warning("sec check failed: %s", e)
        return None
    m = res.match.strip().lower()
    m = m if m in ("yes", "no", "unclear") else "unclear"
    level = "probable" if m == "yes" else ev["level"]
    db.execute("UPDATE sec_events SET level=%s, verified_by=%s, reason=%s WHERE id=%s",
               (level, f"ai:{m}", f"{ev['reason']} · AI: {res.reason[:120]}", ev_id))
    db.execute("INSERT INTO verifications(question, kind, ref_id, match, reason, usage_ref) VALUES (%s,'sec_event',%s,%s,%s,%s)",
               (DESCRIBE[ev["type"]], ev_id, m, res.reason[:200], f"sec:{ev_id}"))
    _ = usage
    return m


# ---- anomaly baseline -------------------------------------------------------------------------------------------
def anomalies_between(camera_id: str | None, t_from: datetime, t_to: datetime) -> list[dict]:
    """Hours whose people count is far above the usual for that hour-of-week (z > 2.5), or busy hours that are
    usually empty. Falls back to a same-day baseline (marked low confidence) when history is short."""
    rows = db.fetch_all(
        "SELECT camera_id, date_trunc('hour', t_start AT TIME ZONE 'Asia/Kolkata') AS h, count(*) n FROM root_tracks "
        "WHERE cls='person' AND t_end - t_start >= interval '1.5 seconds' AND COALESCE(max_conf,1) >= 0.6 "
        + ("AND camera_id=%s " if camera_id else "") + "GROUP BY 1, 2", (camera_id,) if camera_id else None)
    by_cam: dict[str, dict[datetime, int]] = {}
    for r in rows:
        by_cam.setdefault(r["camera_id"], {})[r["h"]] = int(r["n"])
    lo, hi = to_local(t_from).replace(tzinfo=None), to_local(t_to).replace(tzinfo=None)
    out = []
    for cam, hours in by_cam.items():
        for h, n in hours.items():
            if not (lo <= h < hi) or n < 3:
                continue
            same = [v for k, v in hours.items() if k != h and k.weekday() == h.weekday() and k.hour == h.hour]
            note = None
            if len(same) >= 3:
                mu, sd = statistics.mean(same), statistics.pstdev(same) or 1.0
            else:
                others = [v for k, v in hours.items() if k != h and k.date() == h.date()]
                if len(others) < 2:
                    continue
                mu, sd = statistics.mean(others), statistics.pstdev(others) or 1.0
                note = "low confidence: short history"
            z = (n - mu) / sd
            if z > 2.5 or (mu < 0.5 and n >= 3):
                out.append({"camera_id": cam, "hour": h.replace(tzinfo=tz()).isoformat(), "count": n, "normal": round(mu, 1),
                            "z": round(z, 1), "note": note})
    return sorted(out, key=lambda a: -a["z"])


# ---- loop ----------------------------------------------------------------------------------------------------------
def run_once(since_id: int) -> tuple[int, int]:
    """Analyze finished tracks with id > since_id. Returns (new events, max track id seen)."""
    rows = db.fetch_all("SELECT id, camera_id, cls, t_start, t_end, path, active FROM tracks WHERE id > %s AND NOT active "
                        "AND merged_into IS NULL ORDER BY id LIMIT 400", (since_id,))
    if not rows:
        return 0, since_id
    created = []
    by_cam: dict[str, list[dict]] = {}
    for r in rows:
        by_cam.setdefault(r["camera_id"], []).append(r)
    for cam, trs in by_cam.items():
        t0 = min(t["t_start"] for t in trs) - timedelta(seconds=10)
        t1 = max(t["t_end"] for t in trs) + timedelta(seconds=10)
        neigh = db.fetch_all("SELECT id, cls, t_start, t_end, path FROM tracks WHERE camera_id=%s AND t_end >= %s AND "
                             "t_start <= %s AND merged_into IS NULL", (cam, t0, t1))
        created += analyze(cam, trs, neigh)
        c = crowding(cam, neigh)
        if c:
            created.append(c)
    for ev_id in created:
        try:
            verify_event(ev_id)
        except Exception as e:
            log.warning("verify %s: %s", ev_id, e)
    if created:
        log.info("security: %d new event(s)", len(created))
    return len(created), max(r["id"] for r in rows)


def loop(stop: threading.Event, interval: float = 15.0) -> None:
    row = db.fetch_one("SELECT v FROM kv WHERE k='security_cursor'")
    cursor = int((row or {}).get("v") or 0) if row else 0
    while not stop.is_set():
        try:
            n, new_cursor = run_once(cursor)
            if new_cursor != cursor:
                cursor = new_cursor
                db.execute("INSERT INTO kv(k, v) VALUES ('security_cursor', %s) ON CONFLICT (k) DO UPDATE SET v=EXCLUDED.v, "
                           "updated_at=now()", (Jsonb(cursor),))
                continue
        except Exception as e:
            log.exception("security loop: %s", e)
        stop.wait(interval)


# ---- digest ---------------------------------------------------------------------------------------------------------
def digest(now: datetime | None = None, language: str = "hinglish") -> dict[str, Any]:
    """Overnight summary (20:00 -> 08:00, or the last 12 h of footage when the cameras are recordings)."""
    from ..core.timeutil import now_local

    now = now or now_local()
    t_to = now
    last = db.fetch_val("SELECT max(t_end) FROM coverage")
    if last is not None and last < now - timedelta(hours=12):
        t_to = last
    t_from = t_to - timedelta(hours=12)
    cams = db.fetch_all("SELECT id, name FROM cameras ORDER BY name")
    totals = []
    for c in cams:
        n = int(db.fetch_val("SELECT count(*) FROM root_tracks WHERE camera_id=%s AND cls='person' AND t_end >= %s AND "
                             "t_start <= %s AND t_end - t_start >= interval '1.5 seconds' AND COALESCE(max_conf,1) >= 0.6",
                             (c["id"], t_from, t_to)) or 0)
        prev = int(db.fetch_val("SELECT count(*) FROM root_tracks WHERE camera_id=%s AND cls='person' AND t_end >= %s AND "
                                "t_start <= %s AND t_end - t_start >= interval '1.5 seconds' AND COALESCE(max_conf,1) >= 0.6",
                                (c["id"], t_from - timedelta(days=1), t_to - timedelta(days=1))) or 0)
        totals.append({"camera_id": c["id"], "name": c["name"], "people": n, "normal": prev if prev else None})
    events = db.fetch_all("SELECT id, camera_id, type, t_start, track_ids, level, reason FROM sec_events WHERE t_start BETWEEN "
                          "%s AND %s ORDER BY CASE level WHEN 'probable' THEN 0 WHEN 'confirmed' THEN 1 ELSE 2 END, t_start "
                          "LIMIT 20", (t_from, t_to))
    anomalies = anomalies_between(None, t_from, t_to)
    busiest = max(totals, key=lambda x: x["people"], default=None)
    hi = language in ("hi", "hinglish")
    parts = []
    if busiest and busiest["people"]:
        parts.append((f"Pichhle 12 ghante mein sabse zyada log {busiest['name']} pe dikhe ({busiest['people']})." if hi
                      else f"In the last 12 hours the busiest camera was {busiest['name']} ({busiest['people']} people)."))
    else:
        parts.append("Pichhle 12 ghante mein koi activity record nahi hui." if hi else "No activity was recorded in the last 12 hours.")
    prob = [e for e in events if e["level"] == "probable"]
    if prob:
        kinds = ", ".join(sorted({e["type"].replace("_", " ") for e in prob}))
        parts.append(f"{len(prob)} security event AI ne check kiye: {kinds}." if hi else f"{len(prob)} security events were AI-checked: {kinds}.")
    elif events:
        parts.append(f"{len(events)} cheezein dekhne layak hain (check karein)." if hi else f"{len(events)} things are worth a look (unverified).")
    if anomalies:
        a = anomalies[0]
        parts.append((f"{a['camera_id']} pe {to_local(datetime.fromisoformat(a['hour'])):%H:%M} baje normal se zyada log the ({a['count']} vs {a['normal']})."
                      if hi else f"{a['camera_id']} was unusually busy at {to_local(datetime.fromisoformat(a['hour'])):%H:%M} ({a['count']} vs usual {a['normal']})."))
    items = [{"id": e["id"], "camera_id": e["camera_id"], "type": e["type"], "t": to_local(e["t_start"]).isoformat(),
              "track_ids": list(e["track_ids"] or []), "level": e["level"], "reason": e["reason"]} for e in events]
    return {"text": " ".join(parts), "items": items, "anomalies": anomalies[:5], "totals": totals,
            "window": {"from": to_local(t_from).isoformat(), "to": to_local(t_to).isoformat()},
            "generated_at": to_local(datetime.now(timezone.utc)).isoformat()}
