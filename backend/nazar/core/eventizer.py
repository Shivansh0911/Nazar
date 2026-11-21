"""The single source of zone truth: track paths -> enter/exit/dwell events.

Used by the worker eventize loop, rule replay, live rule evaluation and zone re-computation.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .geometry import anchor_point, point_in_polygon

DWELL_MIN_S = 10.0


@dataclass
class ZoneEvent:
    type: str  # enter | exit | dwell | cross_in | cross_out
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


def _side(a, b, p) -> float:
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


def line_crossings(path: list, cls: str, line, zone: str, direction: str = "right",
                   hysteresis: int = 2) -> list[ZoneEvent]:
    """Count-line crossings. `line` = [[x,y],[x,y]] (A->B). The "in" side is to the right of A->B (image coords,
    y down) when direction == "right", else to the left. A flip needs `hysteresis` agreeing points and the move must
    pass through the segment itself (not its extension)."""
    if not path or not line or len(line) < 2:
        return []
    a, b = line[0], line[1]
    seg_len2 = (b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2
    if seg_len2 <= 1e-9:
        return []
    in_sign = 1.0 if direction != "left" else -1.0
    out: list[ZoneEvent] = []
    state = 0.0  # confirmed side (+1/-1), 0 = unknown yet
    state_pt = None
    streak = 0
    streak_start = 0
    hyst = max(1, hysteresis)
    for i, pt in enumerate(path):
        p = anchor_point(cls, pt[1:5])
        sd = _side(a, b, p)
        if abs(sd) < 1e-6:
            continue
        side = 1.0 if sd > 0 else -1.0
        if state == 0.0:
            state, state_pt = side, p
            continue
        if side == state:
            streak = 0
            state_pt = p
            continue
        if streak == 0:
            streak_start = i
        streak += 1
        if streak < hyst:
            continue
        # confirmed flip: did the move from the last same-side point to the first new-side point cross the segment?
        q = anchor_point(cls, path[streak_start][1:5])
        d1, d2 = _side(a, b, state_pt), _side(a, b, q)
        crossed = False
        if d1 != d2:
            r = d1 / (d1 - d2)
            ix, iy = state_pt[0] + r * (q[0] - state_pt[0]), state_pt[1] + r * (q[1] - state_pt[1])
            u = ((ix - a[0]) * (b[0] - a[0]) + (iy - a[1]) * (b[1] - a[1])) / seg_len2
            crossed = -0.05 <= u <= 1.05
        if crossed:
            typ = "cross_in" if side == in_sign else "cross_out"
            out.append(ZoneEvent(typ, zone, int(path[streak_start][0])))
        state, state_pt, streak = side, p, 0
    return out


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
        if z.get("type") == "line":
            events.extend(line_crossings(track_path, cls, poly, name, z.get("direction") or "right", hysteresis))
            continue
        for run in zone_runs(track_path, cls, poly, name, hysteresis):
            events.append(ZoneEvent("enter", name, run.start_ms))
            if run.closed:
                events.append(ZoneEvent("exit", name, run.end_ms))
            secs = (run.end_ms - run.start_ms) / 1000.0
            if secs >= min_dwell:
                events.append(ZoneEvent("dwell", name, run.start_ms, {"seconds": round(secs, 1), "ongoing": not run.closed}))
    order = {"enter": 0, "cross_in": 0, "cross_out": 0, "dwell": 1, "exit": 2}
    events.sort(key=lambda e: (e.t_ms, order[e.type]))
    zone_path: list[str] = []
    for e in events:
        if e.type in ("enter", "cross_in", "cross_out") and e.zone not in zone_path:
            zone_path.append(e.zone)
    return events, zone_path
