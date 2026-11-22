"""Privacy spot-check (spec §L): fetch 10+ media files exactly as the API serves them (crops, keyframes, alert
snapshots, clip frames) and look for any face YuNet can still find. Saves a montage for a human look.

    python scripts/privacy_spotcheck.py [--out data/privacy_spotcheck.jpg]
"""
import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np
import psycopg
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
API = os.environ.get("API_BASE_URL", "http://localhost:8000")
YUNET = ROOT / "backend" / "models" / "face_detection_yunet_2023mar.onnx"

ap = argparse.ArgumentParser()
ap.add_argument("--out", default=str(Path(os.environ.get("DATA_DIR", ROOT / "data")) / "privacy_spotcheck.jpg"))
ap.add_argument("--score", type=float, default=0.75)
a = ap.parse_args()

tok = requests.post(f"{API}/api/auth", json={"passcode": os.environ.get("DEMO_PASSCODE", "nazar2026")}, timeout=10).json()["token"]
H = {"X-Nazar-Token": tok}
db = psycopg.connect(os.environ["DATABASE_URL"])


def media(key: str) -> bytes:
    r = requests.get(f"{API}/media/{key}", headers=H, timeout=30)
    r.raise_for_status()
    return r.content


items: list[tuple[str, bytes]] = []
# person crops from the cameras with the closest people (largest boxes first)
for (key, cam) in db.execute("""
    SELECT crop_keys[1], camera_id FROM tracks WHERE cls='person' AND crop_keys <> '{}' AND merged_into IS NULL
    ORDER BY (SELECT max((p->>4)::float) FROM jsonb_array_elements(path) p) DESC NULLS LAST LIMIT 4""").fetchall():
    items.append((f"crop {cam}", media(key)))
for (key, cam) in db.execute("SELECT key, camera_id FROM keyframes WHERE persons > 0 ORDER BY persons DESC, id DESC LIMIT 3").fetchall():
    items.append((f"keyframe {cam}", media(key)))
for (key,) in db.execute("SELECT snapshot_key FROM alerts WHERE snapshot_key IS NOT NULL ORDER BY id DESC LIMIT 2").fetchall():
    items.append(("alert snapshot", media(key)))
for (tid,) in db.execute("""SELECT id FROM tracks WHERE cls='person' AND merged_into IS NULL AND camera_id IN ('builders-venue','office-desk')
                            ORDER BY t_end - t_start DESC LIMIT 2""").fetchall():
    c = requests.get(f"{API}/api/clips/track/{tid}", headers=H, timeout=180).json()
    with tempfile.TemporaryDirectory() as d:
        mp4 = Path(d) / "c.mp4"
        mp4.write_bytes(requests.get(f"{API}{c['url']}" if c["url"].startswith("/") else c["url"], headers=H, timeout=60).content)
        jpg = Path(d) / "f.jpg"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "1.5", "-i", str(mp4), "-frames:v", "1", str(jpg)], check=True)
        items.append((f"clip frame track {tid}", jpg.read_bytes()))

det = cv2.FaceDetectorYN.create(str(YUNET), "", (320, 320), a.score, 0.3, 50)
found, tiles = 0, []
for name, data in items:
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    s = 2.0 if max(img.shape[:2]) < 640 else 1.0
    big = cv2.resize(img, None, fx=s, fy=s) if s != 1 else img
    det.setInputSize((big.shape[1], big.shape[0]))
    _, faces = det.detect(big)
    n = 0 if faces is None else len(faces)
    found += n
    print(f"{'FACE' if n else 'ok  '}  {name}  ({img.shape[1]}x{img.shape[0]}, faces={n})")
    t = cv2.resize(img, (320, int(320 * img.shape[0] / img.shape[1])))
    t = cv2.copyMakeBorder(t[:240], 0, max(0, 240 - t[:240].shape[0]), 0, 0, cv2.BORDER_CONSTANT)
    cv2.putText(t, name[:34], (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255) if not n else (0, 0, 255), 1)
    tiles.append(t)
while len(tiles) % 4:
    tiles.append(np.zeros_like(tiles[0]))
rows = [np.hstack(tiles[i:i + 4]) for i in range(0, len(tiles), 4)]
Path(a.out).parent.mkdir(parents=True, exist_ok=True)
cv2.imwrite(a.out, np.vstack(rows))
print(f"\n{len(items)} served files checked, {found} faces found by YuNet (score >= {a.score}). Montage: {a.out}")
sys.exit(1 if found else 0)
