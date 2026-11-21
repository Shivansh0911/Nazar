"""YOLO + ByteTrack wrapper (one model per process)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

log = logging.getLogger("nazar.edge.detector")

MODELS_DIR = Path(__file__).resolve().parents[2] / "models"
TRACKER_YAML = str(Path(__file__).resolve().parent / "bytetrack_nazar.yaml")
CLASS_IDS = [0, 1, 2, 3, 5, 7, 24, 26, 28, 39, 63, 67]
COCO_NAMES = {0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck", 24: "backpack",
              26: "handbag", 28: "suitcase", 39: "bottle", 63: "laptop", 67: "cell phone"}


@dataclass
class Det:
    track_id: int
    cls: str
    box: tuple[float, float, float, float]  # normalized x1,y1,x2,y2
    conf: float


def resolve_device(device: str = "auto") -> tuple[str | int, bool]:
    import torch

    if device in ("auto", None, ""):
        return (0, True) if torch.cuda.is_available() else ("cpu", False)
    if device == "cpu":
        return "cpu", False
    return int(device), torch.cuda.is_available()


class Detector:
    def __init__(self, device: str = "auto", imgsz: int = 640, conf: float = 0.30, weights: str | None = None):
        from ultralytics import YOLO

        self.device, self.half = resolve_device(device)
        self.imgsz = imgsz
        self.conf = conf
        w = Path(weights) if weights else MODELS_DIR / "yolo11n.pt"
        if self.device == "cpu":
            ov = MODELS_DIR / f"{w.stem}_openvino_model"
            onnx = MODELS_DIR / f"{w.stem}.onnx"
            if ov.exists():
                w = ov
            elif onnx.exists():
                w = onnx
        if not Path(w).exists():
            raise FileNotFoundError(f"{w} missing - run: python scripts/download_models.py")
        self.weights = str(w)
        self.model = YOLO(self.weights, task="detect")
        log.info("detector %s on %s (half=%s, imgsz=%d)", Path(self.weights).name, self.device, self.half, imgsz)
        try:  # warm-up so the first real frame (and fps numbers) don't include CUDA init
            warm = dict(imgsz=imgsz, device=self.device, verbose=False)
            if self.half and not self.weights.endswith(("openvino_model", ".onnx")):
                warm["quantize"] = 16
            self.model.predict(np.zeros((imgsz, imgsz, 3), np.uint8), **warm)
        except Exception as e:
            log.warning("warm-up failed: %s", e)

    def track(self, frame: np.ndarray) -> list[Det]:
        h, w = frame.shape[:2]
        kwargs = dict(persist=True, tracker=TRACKER_YAML, classes=CLASS_IDS, conf=self.conf, imgsz=self.imgsz,
                      device=self.device, verbose=False)
        if self.half and not self.weights.endswith(("openvino_model", ".onnx")):
            kwargs["quantize"] = 16  # fp16 on CUDA (replaces the deprecated `half` arg)
        res = self.model.track(frame, **kwargs)
        out: list[Det] = []
        if not res:
            return out
        boxes = res[0].boxes
        if boxes is None or boxes.id is None:
            return out
        xyxy = boxes.xyxy.cpu().numpy()
        ids = boxes.id.int().cpu().numpy()
        cls = boxes.cls.int().cpu().numpy()
        confs = boxes.conf.cpu().numpy()
        for b, i, c, cf in zip(xyxy, ids, cls, confs):
            name = COCO_NAMES.get(int(c))
            if name is None:
                continue
            x1, y1, x2, y2 = (float(np.clip(b[0] / w, 0, 1)), float(np.clip(b[1] / h, 0, 1)),
                              float(np.clip(b[2] / w, 0, 1)), float(np.clip(b[3] / h, 0, 1)))
            if x2 <= x1 or y2 <= y1:
                continue
            out.append(Det(int(i), name, (x1, y1, x2, y2), float(cf)))
        return out
