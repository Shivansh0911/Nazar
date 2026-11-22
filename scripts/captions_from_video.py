"""Recover the chapter-caption timeline of a demo recording from the video itself (when the caption box text changes),
matched in order to the captions in scripts/demo_full.mjs. Writes a log in demo_full.log format for film_build.py.

    python scripts/captions_from_video.py demo/nazar_full.webm demo/captions.log
"""
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
src, out = sys.argv[1], sys.argv[2]
FPS = 4
W, H = 360, 30   # the caption text band (bottom centre of the 1440x900 recording), downscaled
raw = subprocess.run(["ffmpeg", "-v", "error", "-i", src, "-vf", f"fps={FPS},crop=900:46:270:800,scale={W}:{H},format=gray",
                      "-f", "rawvideo", "-"], capture_output=True).stdout
frames = np.frombuffer(raw, np.uint8).reshape(-1, H, W).astype(np.float32)
diff = np.abs(np.diff(frames, axis=0)).mean(axis=(1, 2))
changes, last = [], -10.0
for i, d in enumerate(diff):
    t = (i + 1) / FPS
    if d > 6.0 and t - last > 2.5:
        changes.append(t)
        last = t
caps = re.findall(r'caption\("(.+?)", "(.+?)"\)', (ROOT / "scripts" / "demo_full.mjs").read_text(encoding="utf-8"))
# the first change after the opening title card is the LOGIN caption
start = next((k for k, t in enumerate(changes) if t > 9.0), 0)
changes = changes[start:]
lines = [f"[{t:4.0f}s] {chap} | {text}" for t, (text, chap) in zip(changes, caps)]
Path(out).write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"{len(changes)} caption changes found, {len(caps)} captions in the script, wrote {len(lines)} lines")
for line in lines:
    print(line[:90])
