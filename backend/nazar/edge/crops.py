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
    first: Candidate | None = None
    best: Candidate | None = None
    middle: Candidate | None = None
    n: int = 0
    _next_mid: int = 2
    _all: list = field(default_factory=list)

    def offer(self, blurred_frame: np.ndarray, box, conf: float, t_ms: int) -> None:
        self.n += 1
        is_first = self.first is None
        take_mid = self.n == self._next_mid
        need = is_first or take_mid
        # quality needs the crop; compute cheaply only when it could matter
        crop = cut(blurred_frame, box)
        if crop.size == 0:
            return
        q = quality(crop, box, conf)
        cand = Candidate(crop, tuple(box), conf, q, t_ms)
        if is_first:
            self.first = cand
        if take_mid:
            self.middle = cand  # index doubles each time -> ends between n/4 and n/2
            self._next_mid *= 2
        if self.best is None or q > self.best.q:
            self.best = cand
        _ = need

    def choose(self) -> list[Candidate]:
        """Up to 3 distinct crops, best first."""
        out: list[Candidate] = []
        for c in (self.best, self.middle, self.first):
            if c is not None and all(c is not o for o in out):
                out.append(c)
        return out[:3]
