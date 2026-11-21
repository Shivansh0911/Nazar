"""Stitcher: merge broken tracks (ByteTrack ID switches inflate counts).

B is merged into root(A) when: same camera and class, both finished, B starts <= 1.5 s after A ends (and not before
A ends by more than 0.2 s), A's last box and B's first box are within 0.08 normalized distance, and appearance cosine
similarity >= 0.85.
"""
from __future__ import annotations

import logging
import time
from datetime import timedelta

from ..core import db
from ..core.appearance import cosine
from ..core.geometry import box_distance

log = logging.getLogger("nazar.stitcher")

MAX_GAP_MS = 1500
MAX_OVERLAP_MS = 200
MAX_DIST = 0.08
MIN_SIM = 0.85


def find_merges(tracks: list[dict]) -> list[tuple[int, int]]:
    """Pure: tracks = [{id, cls, path, appearance, merged_into}] with path [[t_ms,x1,y1,x2,y2,conf],...].

    Returns [(child_id, root_id)] in time order. Each track is the child of at most one merge and each
    track continues into at most one successor.
    """
    roots: dict[int, int] = {}
    for t in tracks:
        roots[t["id"]] = t.get("merged_into") or t["id"]

    def root(i: int) -> int:
        seen = set()
        while roots.get(i, i) != i and i not in seen:
            seen.add(i)
            i = roots[i]
        return i

    valid = [t for t in tracks if t.get("path") and t.get("appearance") is not None]
    valid.sort(key=lambda t: t["path"][0][0])
    has_successor: set[int] = set()
    merges: list[tuple[int, int]] = []
    for b in valid:
        if b.get("merged_into"):
            continue
        b_start = b["path"][0][0]
        best = None
        for a in valid:
            if a["id"] == b["id"] or a["cls"] != b["cls"] or a["id"] in has_successor:
                continue
            a_end = a["path"][-1][0]
            gap = b_start - a_end
            if gap > MAX_GAP_MS or gap < -MAX_OVERLAP_MS:
                continue
            if a["path"][0][0] >= b_start:
                continue
            d = box_distance(a["path"][-1][1:5], b["path"][0][1:5])
            if d > MAX_DIST:
                continue
            sim = cosine(a["appearance"], b["appearance"])
            if sim < MIN_SIM:
                continue
            if root(a["id"]) == b["id"]:
                continue
            score = sim - d
            if best is None or score > best[0]:
                best = (score, a)
        if best is not None:
            a = best[1]
            r = root(a["id"])
            roots[b["id"]] = r
            has_successor.add(a["id"])
            merges.append((b["id"], r))
    return merges


def run_once(lookback_minutes: int = 30) -> int:
    rows = db.fetch_all(
        """SELECT id, camera_id, cls, path, appearance, merged_into, t_start, t_end
             FROM tracks
            WHERE active = false AND appearance IS NOT NULL
              AND t_end >= (SELECT COALESCE(max(t_end), now()) FROM tracks) - %s::interval
            ORDER BY camera_id, t_start""",
        (timedelta(minutes=lookback_minutes),),
    )
    by_cam: dict[str, list[dict]] = {}
    for r in rows:
        r["appearance"] = list(r["appearance"]) if r["appearance"] is not None else None
        by_cam.setdefault(r["camera_id"], []).append(r)
    n = 0
    for cam, ts in by_cam.items():
        for child, root_id in find_merges(ts):
            db.execute("UPDATE tracks SET merged_into=%s, updated_at=now() WHERE id=%s AND merged_into IS NULL",
                       (root_id, child))
            # children of the child now point to the root too (keep one level)
            db.execute("UPDATE tracks SET merged_into=%s WHERE merged_into=%s", (root_id, child))
            n += 1
    if n:
        log.info("stitched %d track(s)", n)
    return n


def loop(stop, interval: float = 5.0) -> None:
    while not stop.is_set():
        try:
            run_once()
        except Exception as e:
            log.exception("stitcher error: %s", e)
        stop.wait(interval)
