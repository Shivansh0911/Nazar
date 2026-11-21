"""Rule replay over stored trajectories - the same pure evaluators as live evaluation."""
from __future__ import annotations

from datetime import datetime, timedelta

from . import db
from .rules import Hit, RuleSpec, evaluate_count, evaluate_track

TRACK_COLS = "id, camera_id, cls, path, active, t_start, t_end, crop_keys"


def camera_zones(camera_id: str) -> list[dict]:
    return (db.fetch_one("SELECT zones FROM cameras WHERE id=%s", (camera_id,)) or {}).get("zones") or []


def persons_near(camera_id: str, t_from: datetime, t_to: datetime, exclude: int | None = None) -> list[dict]:
    return db.fetch_all(
        f"SELECT {TRACK_COLS} FROM tracks WHERE camera_id=%s AND cls='person' AND t_start <= %s AND t_end >= %s "
        "AND (%s::bigint IS NULL OR id <> %s)",
        (camera_id, t_to, t_from, exclude, exclude),
    )


def evaluate_one(spec: RuleSpec, track: dict, zones: list[dict]) -> list[Hit]:
    others = None
    if spec.trigger == "object_removed":
        others = persons_near(track["camera_id"], track["t_start"] - timedelta(seconds=3),
                              track["t_end"] + timedelta(seconds=3), exclude=track["id"])
    return evaluate_track(spec, track, zones, others)


def replay(spec: RuleSpec, window_from: datetime, window_to: datetime, max_hits: int | None = None) -> list[Hit]:
    zones = camera_zones(spec.camera_id)
    classes = list(spec.classes())
    tracks = db.fetch_all(
        f"SELECT {TRACK_COLS} FROM tracks WHERE camera_id=%s AND cls = ANY(%s) AND t_end >= %s AND t_start <= %s "
        "ORDER BY t_start",
        (spec.camera_id, classes, window_from, window_to),
    )
    hits: list[Hit] = []
    if spec.trigger == "count_over":
        hits = evaluate_count(spec, tracks, zones)
    else:
        for tr in tracks:
            hits.extend(evaluate_one(spec, tr, zones))
    lo, hi = window_from.timestamp() * 1000, window_to.timestamp() * 1000
    hits = [h for h in hits if lo <= h.t_ms <= hi]
    # one hit per alert key (rule, track) - the same uniqueness the live engine uses
    seen: set[int] = set()
    uniq: list[Hit] = []
    for h in sorted(hits, key=lambda h: h.t_ms):
        if h.track_id in seen:
            continue
        seen.add(h.track_id)
        uniq.append(h)
    return uniq[:max_hits] if max_hits else uniq
