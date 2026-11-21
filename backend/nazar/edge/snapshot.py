"""Atomic live snapshot: data/live/<camera>.jpg (face-blurred, q=70, width 854)."""
from __future__ import annotations

import os
import time

import cv2
import numpy as np

from ..core import storage


class Snapshot:
    def __init__(self, camera_id: str, width: int = 854, quality: int = 70):
        self.path = storage.local_path(f"live/{camera_id}.jpg")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.tmp = self.path.with_name(f"{camera_id}.{os.getpid()}.tmp.jpg")
        self.width = width
        self.quality = quality

    def write(self, blurred: np.ndarray) -> None:
        h, w = blurred.shape[:2]
        img = blurred if w <= self.width else cv2.resize(blurred, (self.width, int(h * self.width / w)),
                                                          interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, self.quality])
        if not ok:
            return
        self.tmp.write_bytes(buf.tobytes())
        for _ in range(5):  # Windows: a reader may hold the file briefly
            try:
                os.replace(self.tmp, self.path)
                return
            except PermissionError:
                time.sleep(0.01)
