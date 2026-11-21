"""Best-crop selection per track (max 3 kept in memory): first sighting, best quality, near the middle."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np

PAD = 0.10
MIN_SIDE = 96


def cut(frame: np.ndarray, box: tuple[float, float, float, float], pad: float = PAD) -> np.ndarray:
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = box
    pw, ph = (x2 - x1) * pad, (y2 - y1) * pad
    X1, Y1 = max(0, int((x1 - pw) * w)), max(0, int((y1 - ph) * h))
    X2, Y2 = min(w, int(math.ceil((x2 + pw) * w))), min(h, int(math.ceil((y2 + ph) * h)))
    return frame[Y1:Y2, X1:X2].copy()


def quality(crop: np.ndarray, box, conf: float) -> float:
    if crop.size == 0:
        return 0.0
    area = crop.shape[0] * crop.shape[1]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    lap = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    edge = box[0] <= 0.005 or box[1] <= 0.005 or box[2] >= 0.995 or box[3] >= 0.995
    return math.sqrt(area) * min(1.0, lap / 150.0) * conf * (0.5 if edge else 1.0)


def finish(crop: np.ndarray) -> np.ndarray:
    """Upscale small crops x2 and ensure a minimum side of 96 px."""
    h, w = crop.shape[:2]
    if min(h, w) == 0:
        return crop
    if min(h, w) < MIN_SIDE:
        s = max(2.0, MIN_SIDE / min(h, w))
        crop = cv2.resize(crop, (int(w * s), int(h * s)), interpolation=cv2.INTER_CUBIC)
    return crop


@dataclass
class Candidate:
    img: np.ndarray
    box: tuple
    conf: float
    q: float
    t_ms: int


@dataclass
class CropKeeper:
    """Keeps <= 3 candidate crops. Crops are cut from the raw frame and every head box in view is blurred at once,
    so no unblurred face ever leaves this object (a YuNet pass runs again when the crop is written)."""
    first: Candidate | None = None
    best: Candidate | None = None
    middle: Candidate | None = None
    n: int = 0
    _next_mid: int = 2

    def offer(self, frame: np.ndarray, box, conf: float, t_ms: int, heads=()) -> None:
        self.n += 1
        h, w = frame.shape[:2]
        bw, bh = (box[2] - box[0]) * w, (box[3] - box[1]) * h
        edge = box[0] <= 0.005 or box[1] <= 0.005 or box[2] >= 0.995 or box[3] >= 0.995
        q = math.sqrt(max(1.0, bw * bh)) * conf * (0.5 if edge else 1.0)  # cheap proxy, no pixel work
        is_first = self.first is None
        take_mid = self.n == self._next_mid
        better = self.best is None or q > self.best.q * 1.1
        if not (is_first or take_mid or better):
            return
        crop = cut_blurred(frame, box, heads)
        if crop.size == 0:
            return
        cand = Candidate(crop, tuple(box), conf, q, t_ms)
        if is_first:
            self.first = cand
        if take_mid:
            self.middle = cand  # index doubles each time -> ends between n/4 and n/2
            self._next_mid *= 2
        if better:
            self.best = cand

    def choose(self) -> list[Candidate]:
        """Up to 3 distinct crops, best first."""
        out: list[Candidate] = []
        for c in (self.best, self.middle, self.first):
            if c is not None and all(c is not o for o in out):
                out.append(c)
        return out[:3]


def cut_blurred(frame: np.ndarray, box, heads=(), pad: float = PAD) -> np.ndarray:
    """Cut a padded crop and blur every head box that overlaps it (heads in normalized frame coords)."""
    from .faceblur import FaceBlurrer

    h, w = frame.shape[:2]
    x1, y1, x2, y2 = box
    pw, ph = (x2 - x1) * pad, (y2 - y1) * pad
    X1, Y1 = max(0, int((x1 - pw) * w)), max(0, int((y1 - ph) * h))
    X2, Y2 = min(w, int(math.ceil((x2 + pw) * w))), min(h, int(math.ceil((y2 + ph) * h)))
    crop = frame[Y1:Y2, X1:X2].copy()
    for hx1, hy1, hx2, hy2 in heads:
        a1, b1, a2, b2 = int(hx1 * w) - X1, int(hy1 * h) - Y1, int(math.ceil(hx2 * w)) - X1, int(math.ceil(hy2 * h)) - Y1 + 1
        if a2 <= 0 or b2 <= 0 or a1 >= crop.shape[1] or b1 >= crop.shape[0]:
            continue
        FaceBlurrer._blur_region(crop, a1, b1, a2, b2)
    return crop
