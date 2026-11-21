"""Pipeline speed benchmark (W1): builds a >= 30 min test file from the demo clips, runs the v2 fast file path
(and a 60 s sample of the v1 OpenCV loop for comparison) and prints a table + writes data/eval/bench.json.

    python scripts/bench_pipeline.py [--minutes 30] [--skip-v1]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from nazar.core import db  # noqa: E402
from nazar.core.config import ffmpeg_bin, get_settings  # noqa: E402
from nazar.core.media import probe  # noqa: E402

CLIPS = ["clip1.mp4", "clip3.mp4", "clip2.mp4", "clip4.mp4", "clip5.mp4"]


def build_test_file(minutes: float) -> Path:
    out = get_settings().data_dir / "eval" / f"bench_{int(minutes)}min.mp4"
    if out.exists() and probe(out)["duration"] >= minutes * 60 - 5:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    base = out.with_name("bench_base.mp4")
    if not base.exists():
        # normalize the stock clips to one 1280x720 30 fps H.264 stream (one-time)
        inputs, filt = [], []
        for i, c in enumerate(CLIPS):
            inputs += ["-i", str(ROOT / "samples" / c)]
            filt.append(f"[{i}:v]scale=1280:720,fps=30,setsar=1[v{i}]")
        filt.append("".join(f"[v{i}]" for i in range(len(CLIPS))) + f"concat=n={len(CLIPS)}:v=1:a=0[out]")
        subprocess.run([ffmpeg_bin(), "-v", "error", "-y", *inputs, "-filter_complex", ";".join(filt), "-map", "[out]",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", str(base)], check=True)
    reps = int(minutes * 60 // probe(base)["duration"]) + 1
    lst = out.with_name("bench_list.txt")
    lst.write_text("".join(f"file '{base.as_posix()}'\n" for _ in range(reps)))
    subprocess.run([ffmpeg_bin(), "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
                    "-t", str(minutes * 60), str(out)], check=True)
    return out


def run_edge(src: Path, camera: str, extra: list[str]) -> dict:
    cmd = [sys.executable, "-m", "nazar.edge.run", "--camera", camera, "--source", str(src),
           "--start-time", "2026-11-01T09:00:00", *extra]
    t0 = time.monotonic()
    p = subprocess.run(cmd, cwd=ROOT / "backend", capture_output=True, text=True)
    wall = time.monotonic() - t0
    line = next((ln for ln in p.stdout.splitlines() if ln.startswith("EDGE_SUMMARY ")), None)
    if not line:
        raise SystemExit(f"edge failed:\n{p.stdout[-2000:]}\n{p.stderr[-2000:]}")
    r = json.loads(line[len("EDGE_SUMMARY "):])
    r["process_wall_s"] = round(wall, 1)
    return r


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=30)
    ap.add_argument("--skip-v1", action="store_true")
    a = ap.parse_args()
    src = build_test_file(a.minutes)
    dur = probe(src)["duration"]
    print(f"test file: {src.name} ({dur / 60:.1f} min, 1280x720)")
    rows = []
    if not a.skip_v1:
        r1 = run_edge(src, "bench-v1", ["--legacy", "--fast", "--max-seconds", "60"])
        rows.append(("v1 OpenCV loop (60 s sample)", r1["source_s"], r1["wall_s"], r1["speed_x"], r1.get("detect_fps")))
    r2 = run_edge(src, "bench-v2", ["--batch", "32"])
    rows.append(("v2 ffmpeg + batched GPU", r2["source_s"], r2["process_wall_s"], round(r2["source_s"] / r2["process_wall_s"], 1),
                 r2.get("detect_fps")))
    drift = abs((r2["source_s"] + 1 / get_settings().DETECT_FPS) - dur)
    print(f"\n| pipeline | footage s | wall s | x real time | detector fps |\n|---|---|---|---|---|")
    for name, s, w, x, f in rows:
        print(f"| {name} | {s:.0f} | {w:.0f} | {x} | {f} |")
    print(f"\ntimestamp drift at end: {drift:.2f} s (last frame time vs ffprobe duration)")
    print(f"tracks: {r2['tracks_final']}, keyframes: {r2['keyframes']}, model {r2['weights']} imgsz {r2['imgsz']}, "
          f"stage seconds {r2.get('prof')}")
    out = get_settings().data_dir / "eval" / "bench.json"
    out.write_text(json.dumps({"at": datetime.now().isoformat(timespec="seconds"), "file_s": dur, "rows": rows,
                               "drift_s": drift, "v2": r2}, indent=2))
    # benchmark cameras are scratch data
    for cam in ("bench-v1", "bench-v2"):
        db.execute("DELETE FROM cameras WHERE id=%s", (cam,))
    return 0 if drift < 0.5 else 1


if __name__ == "__main__":
    sys.exit(main())
