"""ffprobe/ffmpeg helpers (list-arg subprocess only)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .config import ffmpeg_bin, ffprobe_bin

FFMPEG_TIMEOUT = 60


def probe(path: str | Path) -> dict:
    """Returns {duration, width, height, rotation, fps, has_video}."""
    cmd = [ffprobe_bin(), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=FFMPEG_TIMEOUT)
    if r.returncode != 0:
        raise ValueError(f"ffprobe failed: {r.stderr.strip()[:300]}")
    info = json.loads(r.stdout or "{}")
    out = {"duration": None, "width": None, "height": None, "rotation": 0, "fps": None, "has_video": False,
           "has_audio": False}
    fmt = info.get("format", {})
    if fmt.get("duration"):
        out["duration"] = float(fmt["duration"])
    for s in info.get("streams", []):
        if s.get("codec_type") == "audio":
            out["has_audio"] = True
            if out["duration"] is None and s.get("duration"):
                out["duration"] = float(s["duration"])
        if s.get("codec_type") == "video" and not out["has_video"]:
            if s.get("disposition", {}).get("attached_pic"):
                continue
            out["has_video"] = True
            out["width"], out["height"] = s.get("width"), s.get("height")
            rot = 0
            for sd in s.get("side_data_list", []) or []:
                if "rotation" in sd:
                    rot = int(float(sd["rotation"]))
            if "rotate" in (s.get("tags") or {}):
                rot = int(float(s["tags"]["rotate"]))
            out["rotation"] = rot
            fr = s.get("avg_frame_rate") or s.get("r_frame_rate") or "0/1"
            try:
                n, d = fr.split("/")
                out["fps"] = float(n) / float(d) if float(d) else None
            except Exception:
                out["fps"] = None
            if out["duration"] is None and s.get("duration"):
                out["duration"] = float(s["duration"])
    return out


def duration(path: str | Path) -> float:
    return float(probe(path).get("duration") or 0.0)


def run_ffmpeg(args: list[str], timeout: int = FFMPEG_TIMEOUT) -> subprocess.CompletedProcess:
    cmd = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", *args]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {r.stderr.strip()[:500]}")
    return r


def first_frame_jpeg(video: str | Path, out: str | Path, width: int = 854) -> Path:
    run_ffmpeg(["-y", "-i", str(video), "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "4", str(out)])
    return Path(out)
