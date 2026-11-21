"""YOLO detector + tracker (one model per process).

v2: frames are letterboxed on the GPU (torch) and detected in batches; the tracker (ByteTrack or BoT-SORT) is
driven frame by frame in order, so batching never changes tracking. Falls back to CPU (OpenVINO/ONNX/torch).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

log = logging.getLogger("nazar.edge.detector")

MODELS_DIR = Path(__file__).resolve().parents[2] / "models"
TRACKER_DIR = Path(__file__).resolve().parent
CLASS_IDS = [0, 1, 2, 3, 5, 7, 24, 26, 28, 39, 63, 67]
COCO_NAMES = {0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck", 24: "backpack",
              26: "handbag", 28: "suitcase", 39: "bottle", 63: "laptop", 67: "cell phone"}
DEFAULT_WEIGHTS = os.environ.get("NAZAR_DETECTOR", "yolo11s.pt")
HEAD_FRAC = 0.3  # head box = top 30 % of a person box (generous: seated or bending people) (pose models missed most small, far people in tests)


@dataclass
class Det:
    track_id: int
    cls: str
    box: tuple[float, float, float, float]  # normalized x1,y1,x2,y2
    conf: float

    @property
    def head(self) -> tuple[float, float, float, float] | None:
        if self.cls != "person":
            return None
        x1, y1, x2, y2 = self.box
        h = y2 - y1
        pw = (x2 - x1) * 0.05
        return (max(0.0, x1 - pw), max(0.0, y1 - h * 0.02), min(1.0, x2 + pw), min(1.0, y1 + h * HEAD_FRAC))


def resolve_device(device: str = "auto") -> tuple[str | int, bool]:
    import torch

    if device in ("auto", None, ""):
        return (0, True) if torch.cuda.is_available() else ("cpu", False)
    if device == "cpu":
        return "cpu", False
    return int(device), torch.cuda.is_available()


def load_tracker_cfg(kind: str = "bytetrack"):
    from ultralytics.utils import YAML, IterableSimpleNamespace

    f = TRACKER_DIR / f"{kind}_nazar.yaml"
    return IterableSimpleNamespace(**YAML.load(str(f)))


def make_tracker(kind: str, fps: float):
    from ultralytics.trackers.bot_sort import BOTSORT
    from ultralytics.trackers.byte_tracker import BYTETracker

    cfg = load_tracker_cfg(kind)
    cls = BOTSORT if cfg.tracker_type == "botsort" else BYTETracker
    cfg.track_buffer = max(10, int(round(fps * 6)))  # keep lost tracks ~6 s (trackers count frames, not seconds)
    return cls(args=cfg)


class Detector:
    def __init__(self, device: str = "auto", imgsz: int = 640, conf: float = 0.30, weights: str | None = None,
                 tracker: str | None = None, fps: float = 5.0):
        from ultralytics import YOLO

        self.device, self.half = resolve_device(device)
        self.imgsz = imgsz
        self.conf = conf
        w = Path(weights) if weights else MODELS_DIR / DEFAULT_WEIGHTS
        if not w.exists():
            w = MODELS_DIR / "yolo11n.pt"
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
        self.torch_model = not self.weights.endswith(("openvino_model", ".onnx"))
        self.gpu = self.device != "cpu" and self.torch_model
        self.model = YOLO(self.weights, task="detect")
        self.tracker_kind = tracker or os.environ.get("NAZAR_TRACKER", "bytetrack")
        self.fps = fps
        self.tracker = make_tracker(self.tracker_kind, fps)
        log.info("detector %s on %s (gpu tensors=%s, imgsz=%d, tracker=%s)", Path(self.weights).name, self.device,
                 self.gpu, imgsz, self.tracker_kind)
        try:  # warm-up so the first real frame (and fps numbers) don't include CUDA init
            self._predict([np.zeros((360, 640, 3), np.uint8)])
        except Exception as e:
            log.warning("warm-up failed: %s", e)

    def reset(self) -> None:
        self.tracker = make_tracker(self.tracker_kind, self.fps)

    # ---- inference ----------------------------------------------------------------------
    def _tensor(self, frames: list[np.ndarray]):
        import torch
        import torch.nn.functional as F

        h, w = frames[0].shape[:2]
        x = torch.from_numpy(np.stack(frames)).to(self.device, non_blocking=True)
        x = x[..., [2, 1, 0]].permute(0, 3, 1, 2).half() / 255.0
        scale = self.imgsz / max(h, w)
        th, tw = max(32, int(round(h * scale))), max(32, int(round(w * scale)))
        ph, pw = (th + 31) // 32 * 32, (tw + 31) // 32 * 32
        x = F.interpolate(x, size=(th, tw), mode="bilinear", align_corners=False)
        if ph != th or pw != tw:
            x = F.pad(x, (0, pw - tw, 0, ph - th), value=114 / 255)
        return x, (tw, th)

    def _net(self):
        """The raw fused torch network in fp16 (bypasses the ultralytics predictor: ~3x less Python per batch)."""
        if getattr(self, "_raw", None) is None:
            import torch

            self.model.predict(np.zeros((64, 64, 3), np.uint8), device=self.device, half=True, verbose=False)
            net = self.model.predictor.model  # AutoBackend, already fused, on device
            self._raw = net
            self._end2end = bool(getattr(net, "end2end", False))
            self._cls_t = torch.tensor(CLASS_IDS, device=self.device)
        return self._raw

    def _predict(self, frames: list[np.ndarray]):
        """Returns per frame (xyxy normalized Nx4, conf N, cls N) as numpy arrays."""
        kw = dict(classes=CLASS_IDS, conf=self.conf, device=self.device, verbose=False)
        out = []
        if self.gpu and os.environ.get("NAZAR_RAW_NET", "0") == "1":
            import torch
            from ultralytics.utils import nms

            net = self._net()
            x, (tw, th) = self._tensor(frames)
            with torch.inference_mode():
                preds = net(x)
                res = nms.non_max_suppression(preds, self.conf, 0.7, CLASS_IDS, False, max_det=300,
                                              end2end=self._end2end)
                arrs = [r[:, :6].float().cpu().numpy() for r in res]
            scale = np.array([tw, th, tw, th], np.float32)
            for a in arrs:
                out.append((np.clip(a[:, :4] / scale, 0, 1), a[:, 4], a[:, 5]))
            return out
        if self.gpu:
            x, (tw, th) = self._tensor(frames)
            res = self.model.predict(x, half=True, **kw)
            for r in res:
                b = r.boxes
                xy = b.xyxy.cpu().numpy() / np.array([tw, th, tw, th], np.float32)
                out.append((np.clip(xy, 0, 1), b.conf.cpu().numpy(), b.cls.cpu().numpy()))
        else:
            res = self.model.predict(list(frames), imgsz=self.imgsz, **kw)
            for r, f in zip(res, frames):
                h, w = f.shape[:2]
                b = r.boxes
                xy = b.xyxy.cpu().numpy() / np.array([w, h, w, h], np.float32)
                out.append((np.clip(xy, 0, 1), b.conf.cpu().numpy(), b.cls.cpu().numpy()))
        return out

    def track_batch(self, frames: list[np.ndarray]) -> list[list[Det]]:
        """Detect a batch of consecutive frames, then update the tracker in order."""
        if not frames:
            return []
        results = []
        for (xy, conf, cls), f in zip(self._predict(frames), frames):
            results.append(self._update(xy, conf, cls, f))
        return results

    def track(self, frame: np.ndarray) -> list[Det]:
        return self.track_batch([frame])[0]

    def _update(self, xy: np.ndarray, conf: np.ndarray, cls: np.ndarray, frame: np.ndarray) -> list[Det]:
        h, w = frame.shape[:2]
        boxes = _NpBoxes(xy * np.array([w, h, w, h], np.float32), conf, cls)
        tracks = self.tracker.update(boxes, frame)
        out: list[Det] = []
        for t in tracks:  # x1,y1,x2,y2,id,score,cls,idx
            name = COCO_NAMES.get(int(t[6]))
            if name is None:
                continue
            x1, y1, x2, y2 = (float(np.clip(t[0] / w, 0, 1)), float(np.clip(t[1] / h, 0, 1)),
                              float(np.clip(t[2] / w, 0, 1)), float(np.clip(t[3] / h, 0, 1)))
            if x2 <= x1 or y2 <= y1:
                continue
            out.append(Det(int(t[4]), name, (x1, y1, x2, y2), float(t[5])))
        return out


class _NpBoxes:
    """Minimal stand-in for ultralytics Boxes (numpy) as the trackers expect."""

    def __init__(self, xyxy: np.ndarray, conf: np.ndarray, cls: np.ndarray):
        self.xyxy = xyxy.astype(np.float32).reshape(-1, 4)
        self.conf = conf.astype(np.float32).reshape(-1)
        self.cls = cls.astype(np.float32).reshape(-1)

    @property
    def xywh(self) -> np.ndarray:
        x = self.xyxy
        return np.stack([(x[:, 0] + x[:, 2]) / 2, (x[:, 1] + x[:, 3]) / 2, x[:, 2] - x[:, 0], x[:, 3] - x[:, 1]], 1)

    def __len__(self) -> int:
        return len(self.conf)

    def __getitem__(self, idx):
        return _NpBoxes(self.xyxy[idx], self.conf[idx], self.cls[idx])
