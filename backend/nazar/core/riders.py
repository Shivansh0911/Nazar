"""Riders: a person whose box sits on a motorcycle/bicycle for most of the time both are visible is a rider, not a
person on foot. Counting keeps riders out of "people" and reports them separately (spec v3 #5).

Paths are 5 Hz lists of [t_ms, x1, y1, x2, y2, ...] in normalised coordinates.
"""
from __future__ import annotations

VEHICLES = ("motorcycle", "bicycle")
RIDER_SHARE = 0.6        # > 60 % of the shared time on the vehicle
MATCH_MS = 150           # samples closer than this are "the same moment"
MIN_SHARED = 5           # need at least 1 s of shared samples at 5 Hz


def on_vehicle(person: list[float], vehicle: list[float]) -> bool:
    """The person's box overlaps the vehicle box substantially and their horizontal centre is over the vehicle."""
    px1, py1, px2, py2 = person[:4]
    vx1, vy1, vx2, vy2 = vehicle[:4]
    iw = min(px2, vx2) - max(px1, vx1)
    ih = min(py2, vy2) - max(py1, vy1)
    if iw <= 0 or ih <= 0:
        return False
    p_area = max(1e-9, (px2 - px1) * (py2 - py1))
    cx = (px1 + px2) / 2
    return (iw * ih) / p_area >= 0.25 and vx1 <= cx <= vx2


def rider_share(person_path: list, vehicle_path: list) -> tuple[float, int]:
    """Share of the shared moments in which the person is on the vehicle, and the number of shared moments."""
    if not person_path or not vehicle_path:
        return 0.0, 0
    v = sorted(vehicle_path, key=lambda p: p[0])
    j, shared, on = 0, 0, 0
    for p in sorted(person_path, key=lambda p: p[0]):
        t = p[0]
        while j + 1 < len(v) and abs(v[j + 1][0] - t) <= abs(v[j][0] - t):
            j += 1
        if abs(v[j][0] - t) > MATCH_MS:
            continue
        shared += 1
        on += on_vehicle(p[1:5], v[j][1:5])
    return (on / shared if shared else 0.0), shared


def find_vehicle(person_path: list, vehicles: list[dict]) -> int | None:
    """Return the id of the vehicle track this person rode (best share > RIDER_SHARE), else None."""
    best, best_id = 0.0, None
    for veh in vehicles:
        share, shared = rider_share(person_path, veh["path"] or [])
        if shared >= MIN_SHARED and share > RIDER_SHARE and share > best:
            best, best_id = share, veh["id"]
    return best_id
