"""The single source of zone truth: track paths -> enter/exit/dwell events.

Used by the worker eventize loop, rule replay, live rule evaluation and zone re-computation.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .geometry import anchor_point, point_in_polygon

DWELL_MIN_S = 10.0


@dataclass
class ZoneEvent:
    type: str  # enter | exit | dwell
    zone: str
    t_ms: int
    meta: dict = field(default_factory=dict)


@dataclass
class InsideRun:
    zone: str
    start_ms: int
    end_ms: int  # last point time inside (or exit time when closed)
    closed: bool  # True when a confirmed exit ended the run
    start_idx: int
    end_idx: int  # index of last inside point


def zone_runs(path: list, cls: str, polygon, zone: str, hysteresis: int = 2) -> list[InsideRun]:
    """Confirmed inside runs for one zone with hysteresis (state flips only after N agreeing points)."""
    runs: list[InsideRun] = []
    if not path or not polygon:
        return runs
    hyst = max(1, hysteresis)
    state = False
    streak = 0
    streak_start = 0
    cur: InsideRun | None = None
    last_inside_idx = -1
    for i, p in enumerate(path):
        x, y = anchor_point(cls, p[1:5])
        inside = point_in_polygon(x, y, polygon)
        if inside:
            last_inside_idx = i
        if inside != state:
            if streak == 0:
                streak_start = i
            streak += 1
            if streak >= hyst:
                state = inside
                streak = 0
                if inside:
                    cur = InsideRun(zone, int(path[streak_start][0]), int(path[i][0]), False, streak_start, i)
                else:
                    if cur is not None:
                        cur.closed = True
                        cur.end_ms = int(path[streak_start][0])
                        runs.append(cur)
                        cur = None
        else:
            streak = 0
            if state and cur is not None:
                cur.end_ms = int(p[0])
                cur.end_idx = i
    if cur is not None:
        if last_inside_idx >= cur.start_idx:
            cur.end_ms = int(path[last_inside_idx][0])
            cur.end_idx = last_inside_idx
        runs.append(cur)
    return runs


def eventize(track_path: list, cls: str, zones: list[dict], hysteresis: int = 2, dwell_thresholds=None):
    """Return (events sorted by time, ordered distinct zone_path).

    - enter at the first point of a confirmed inside run
    - exit at the first point of a confirmed outside run (none if the track ends inside)
    - one dwell per run with meta.seconds when the run lasts >= 10 s (ongoing runs included)
    """
    min_dwell = DWELL_MIN_S
    if dwell_thresholds:
        try:
            min_dwell = min(float(v) for v in dict(dwell_thresholds).values())
        except Exception:
            pass
    events: list[ZoneEvent] = []
    for z in zones or []:
        name = z.get("name")
        poly = z.get("polygon")
        if not name or not poly:
            continue
        for run in zone_runs(track_path, cls, poly, name, hysteresis):
            events.append(ZoneEvent("enter", name, run.start_ms))
            if run.closed:
                events.append(ZoneEvent("exit", name, run.end_ms))
            secs = (run.end_ms - run.start_ms) / 1000.0
            if secs >= min_dwell:
                events.append(ZoneEvent("dwell", name, run.start_ms, {"seconds": round(secs, 1), "ongoing": not run.closed}))
    order = {"enter": 0, "dwell": 1, "exit": 2}
    events.sort(key=lambda e: (e.t_ms, order[e.type]))
    zone_path: list[str] = []
    for e in events:
        if e.type == "enter" and e.zone not in zone_path:
            zone_path.append(e.zone)
    return events, zone_path
