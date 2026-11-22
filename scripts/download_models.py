"""Download the detector + face model into backend/models/.

    python scripts/download_models.py               # YuNet, yolo11s/yolo11n, YOLOE + text encoder, SigLIP 2
    python scripts/download_models.py --export-cpu  # also export OpenVINO (fallback ONNX) for CPU servers
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "backend" / "models"
YUNET_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
YUNET = MODELS / "face_detection_yunet_2023mar.onnx"
YOLO_NAME = os.environ.get("NAZAR_YOLO", "yolo11n.pt")


def fetch(url: str, dest: Path) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "nazar-setup"})
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    os.replace(tmp, dest)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--export-cpu", action="store_true")
    args = ap.parse_args()
    MODELS.mkdir(parents=True, exist_ok=True)

    if not YUNET.exists():
        print(f"downloading YuNet -> {YUNET}")
        fetch(YUNET_URL, YUNET)
    print(f"ok  {YUNET.name} ({YUNET.stat().st_size // 1024} KB)")

    from ultralytics import YOLO

    # detector (yolo11s, default), its small fallback, and YOLOE for "teach it anything" (+ its text encoder)
    for name in dict.fromkeys(["yolo11s.pt", YOLO_NAME, "yolo11n.pt", "yoloe-26s-seg.pt"]):
        d = MODELS / name
        if not d.exists():
            cwd = os.getcwd()
            os.chdir(MODELS)
            try:
                m = YOLO(name)  # ultralytics downloads into the cwd
                if name.startswith("yoloe"):
                    m.set_classes(["chair"])  # fetches the MobileCLIP text encoder once
            finally:
                os.chdir(cwd)
        print(f"ok  {name} ({d.stat().st_size // 1024} KB)" if d.exists() else f"WARN {name} not downloaded")
    dest = MODELS / YOLO_NAME
    # SigLIP 2 for the local visual index (cached by Hugging Face transformers)
    try:
        from transformers import AutoModel, AutoProcessor

        mid = os.environ.get("NAZAR_SIGLIP", "google/siglip2-base-patch16-224")
        AutoProcessor.from_pretrained(mid)
        AutoModel.from_pretrained(mid)
        print(f"ok  {mid}")
    except Exception as e:
        print(f"WARN SigLIP 2 not cached yet ({e}); the vision service downloads it on first start")

    if args.export_cpu:
        from ultralytics import YOLO

        stem = dest.stem
        ov = MODELS / f"{stem}_openvino_model"
        if not ov.exists():
            try:
                YOLO(str(dest)).export(format="openvino", imgsz=640, half=False, dynamic=False)
            except Exception as e:
                print(f"OpenVINO export failed ({e}); exporting ONNX instead")
                YOLO(str(dest)).export(format="onnx", imgsz=640, simplify=True)
        print("ok  CPU export:", ", ".join(p.name for p in MODELS.iterdir() if p.name.startswith(stem)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
