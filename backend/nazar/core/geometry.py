"""Normalized-coordinate geometry helpers (0..1 frame space)."""
from __future__ import annotations

import math
from typing import Sequence

Box = Sequence[float]  # x1, y1, x2, y2
Poly = Sequence[Sequence[float]]

FEET_CLASSES = {"person", "bicycle", "car", "motorcycle", "bus", "truck"}
OBJECT_CLASSES = {"backpack", "handbag", "suitcase", "laptop", "cell phone", "bottle"}
FULL_FRAME: list[list[float]] = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]


def point_in_polygon(x: float, y: float, poly: Poly) -> bool:
    """Ray casting. Points exactly on an edge may go either way; hysteresis absorbs that."""
    n = len(poly)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i][0], poly[i][1]
        xj, yj = poly[j][0], poly[j][1]
        if (yi > y) != (yj > y):
            x_cross = (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi
            if x < x_cross:
                inside = not inside
        j = i
    return inside


def anchor_point(cls: str, box: Box) -> tuple[float, float]:
    x1, y1, x2, y2 = box[0], box[1], box[2], box[3]
    if cls in FEET_CLASSES:
        return ((x1 + x2) / 2.0, y2)
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def center(box: Box) -> tuple[float, float]:
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


def iou(a: Box, b: Box) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def box_distance(a: Box, b: Box) -> float:
    ca, cb = center(a), center(b)
    return math.hypot(ca[0] - cb[0], ca[1] - cb[1])


def box_gap(a: Box, b: Box) -> float:
    """Shortest distance between two boxes (0 when they overlap)."""
    dx = max(0.0, max(a[0], b[0]) - min(a[2], b[2]))
    dy = max(0.0, max(a[1], b[1]) - min(a[3], b[3]))
    return math.hypot(dx, dy)


def polygon_for(zone_name: str, zones: list[dict]) -> list[list[float]] | None:
    if zone_name == "anywhere":
        return FULL_FRAME
    for z in zones:
        if z.get("name") == zone_name:
            return z.get("polygon")
    return None
