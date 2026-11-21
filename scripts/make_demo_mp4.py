"""demo/nazar_v2.webm + demo/nazar_v2_fast.json -> demo/nazar_v2.mp4 with waiting intervals sped up 8x (H.264).
    python scripts/make_demo_mp4.py [--speed 8]"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from nazar.core.config import ffmpeg_bin  # noqa: E402
from nazar.core.media import probe  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--src", default=str(ROOT / "demo" / "nazar_v2.webm"))
ap.add_argument("--fast", default=str(ROOT / "demo" / "nazar_v2_fast.json"))
ap.add_argument("--out", default=str(ROOT / "demo" / "nazar_v2.mp4"))
ap.add_argument("--speed", type=float, default=8.0)
a = ap.parse_args()
dur = float(probe(a.src)["duration"] or 0)
fast = sorted((max(0.0, s), min(dur, e)) for s, e in json.loads(Path(a.fast).read_text()) if e - s > 1.5)
# merge overlaps -> list of (start, end, speed)
parts, cur = [], 0.0
for s, e in fast:
    if s < cur:
        s = cur
    if e <= s:
        continue
    if s > cur:
        parts.append((cur, s, 1.0))
    parts.append((s, e, a.speed))
    cur = e
if cur < dur:
    parts.append((cur, dur, 1.0))
filt, labels = [], []
for i, (s, e, sp) in enumerate(parts):
    filt.append(f"[0:v]trim=start={s:.3f}:end={e:.3f},setpts=(PTS-STARTPTS)/{sp:g}[v{i}]")
    labels.append(f"[v{i}]")
filt.append("".join(labels) + f"concat=n={len(parts)}:v=1:a=0,fps=25,format=yuv420p[out]")
cmd = [ffmpeg_bin(), "-v", "error", "-y", "-i", a.src, "-filter_complex", ";".join(filt), "-map", "[out]", "-c:v", "libx264",
       "-preset", "medium", "-crf", "22", "-movflags", "+faststart", a.out]
subprocess.run(cmd, check=True)
print(f"{a.out}: {probe(a.out)['duration']:.0f} s (from {dur:.0f} s; {len(fast)} waits sped up {a.speed:g}x)")
