"""Face blur before anything is saved or served. No recognition - detection only, to blur.

YuNet (OpenCV FaceDetectorYN) at width 640 on every detection frame; boxes are reused for in-between frames.
Fallback when the model is missing or finds no face inside a person box: blur the top 18 % of that person box.
"""
from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger("nazar.edge.faceblur")
YUNET = Path(__file__).resolve().parents[2] / "models" / "face_detection_yunet_2023mar.onnx"
DETECT_WIDTH = 512  # ~3x faster than 640 on CPU; person-box fallback covers missed small faces


class FaceBlurrer:
    def __init__(self, model_path: Path = YUNET, score: float = 0.6):
        self.det = None
        self._size = None
        if model_path.exists():
            try:
                self.det = cv2.FaceDetectorYN.create(str(model_path), "", (320, 320), score, 0.3, 500)
            except Exception as e:
                log.warning("YuNet unavailable (%s); using top-of-person fallback blur only", e)
        else:
            log.warning("YuNet model missing (%s); using top-of-person fallback blur only", model_path)
        self.faces: list[tuple[float, float, float, float]] = []  # normalized boxes
        self.persons: list[tuple[float, float, float, float]] = []

    def detect(self, frame: np.ndarray) -> list[tuple[float, float, float, float]]:
        h, w = frame.shape[:2]
        faces: list[tuple[float, float, float, float]] = []
        if self.det is not None:
            scale = min(1.0, DETECT_WIDTH / w)
            sw, sh = int(w * scale), int(h * scale)
            small = cv2.resize(frame, (sw, sh)) if scale < 1 else frame
            if self._size != (sw, sh):
                self.det.setInputSize((sw, sh))
                self._size = (sw, sh)
            try:
                _, res = self.det.detect(small)
            except Exception:
                res = None
            if res is not None:
                for r in res:
                    x, y, fw, fh = r[:4]
                    faces.append((x / sw, y / sh, (x + fw) / sw, (y + fh) / sh))
        self.faces = faces
        return faces

    def set_persons(self, boxes: list[tuple[float, float, float, float]]) -> None:
        self.persons = list(boxes)

    @staticmethod
    def _blur_region(img: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> None:
        h, w = img.shape[:2]
        x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
        if x2 - x1 < 2 or y2 - y1 < 2:
            return
        roi = img[y1:y2, x1:x2]
        k = max(15, (max(x2 - x1, y2 - y1) // 2) | 1)
        small = cv2.resize(roi, (max(1, (x2 - x1) // 8), max(1, (y2 - y1) // 8)), interpolation=cv2.INTER_LINEAR)
        roi[:] = cv2.GaussianBlur(cv2.resize(small, (x2 - x1, y2 - y1), interpolation=cv2.INTER_LINEAR), (k, k), 0)

    def egress(self, frame: np.ndarray, heads: list[tuple[float, float, float, float]], detect: bool = True,
               inplace: bool = False, reuse: bool = False) -> np.ndarray:
        """Blur at egress (v2): every known head box (from tracked persons) + YuNet faces on this very image.
        reuse=True: when not detecting on this frame, blur the previous frame's faces (padded more)."""
        img = frame if inplace else frame.copy()
        h, w = img.shape[:2]
        if detect and max(h, w) < 400:
            # small crops: faces are tiny - detect on a 2x upscale with a lower threshold (privacy errs on blurring)
            big = cv2.resize(img, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)
            faces = self.detect(big)
            if self.det is not None:
                try:
                    self.det.setScoreThreshold(0.45)
                    faces = self.detect(big)
                finally:
                    self.det.setScoreThreshold(0.6)
        else:
            faces = self.detect(img) if detect else (self.faces if reuse else [])
        pad = 0.3 if detect else 0.5
        for fx1, fy1, fx2, fy2 in faces:
            pw, ph = (fx2 - fx1) * pad, (fy2 - fy1) * pad
            self._blur_region(img, int((fx1 - pw) * w), int((fy1 - ph) * h), int((fx2 + pw) * w), int((fy2 + ph) * h))
        for hx1, hy1, hx2, hy2 in heads:
            self._blur_region(img, int(hx1 * w), int(hy1 * h), int(np.ceil(hx2 * w)), int(np.ceil(hy2 * h)) + 1)
        return img

    def apply(self, frame: np.ndarray, inplace: bool = False) -> np.ndarray:
        """Blur the latest faces (padded 30 %) and the head area of persons without a detected face."""
        img = frame if inplace else frame.copy()
        h, w = img.shape[:2]
        for fx1, fy1, fx2, fy2 in self.faces:
            pw, ph = (fx2 - fx1) * 0.3, (fy2 - fy1) * 0.3
            self._blur_region(img, int((fx1 - pw) * w), int((fy1 - ph) * h), int((fx2 + pw) * w), int((fy2 + ph) * h))
        for px1, py1, px2, py2 in self.persons:
            has_face = any(px1 <= (f[0] + f[2]) / 2 <= px2 and py1 <= (f[1] + f[3]) / 2 <= py2 for f in self.faces)
            if has_face:
                continue
            bh = py2 - py1
            self._blur_region(img, int(px1 * w), int(py1 * h), int(px2 * w), int((py1 + bh * 0.18) * h) + 1)
        return img
