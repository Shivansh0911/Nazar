"""Narrated agent film: demo/nazar_agent.webm (scripts/demo_agent.mjs) + narration -> demo/nazar_agent_film.mp4

    python scripts/film_agent.py [--offset 3.6] [--realtime-run]
Reuses scripts/film_build.py (speed-ups, TTS narration per chapter caption, loudness-normalised mix) with its own
working folder demo/agent_film/, so the files of the earlier film are not touched.

--offset: the recorder's log clock starts before the video does; log and speed-up times are moved back by this much.
--realtime-run: keep the first investigation at real speed (the agent working is the point of the film). The caption
  recorded during it said the wait was sped up, so that caption is redrawn for those seconds and narrated as redrawn.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import film_build as fb  # noqa: E402

DEMO = ROOT / "demo"
work = DEMO / "agent_film"
work.mkdir(parents=True, exist_ok=True)

ap = argparse.ArgumentParser()
ap.add_argument("--offset", type=float, default=3.6)
ap.add_argument("--realtime-run", action="store_true")
ap.add_argument("--caption-window", default="154.84,187.90", help="video seconds in which the run caption is redrawn")
a = ap.parse_args()

REAL_1 = "It follows the evidence and records a finding for every"
REAL_2 = "step. This is the agent working live, at real speed."
src = DEMO / "nazar_agent.webm"
fast = [[s - a.offset, e - a.offset] for s, e in json.loads((DEMO / "nazar_agent_fast.json").read_text())]
lines = []
for line in (fb.get_settings().data_dir / "logs" / "demo_agent.log").read_text(encoding="utf-8", errors="ignore").splitlines():
    m = re.match(r"\[\s*(\d+)s\] (.+?) \| (.+)$", line)
    if not m:
        continue
    t, chap, text = max(0.0, float(m.group(1)) - a.offset), m.group(2).strip(), m.group(3).strip()
    if a.realtime_run and chap == "FOLLOW THE LEADS":
        chap, text = "REAL TIME", f"{REAL_1} {REAL_2}"
    lines.append(f"[{t:4.0f}s] {chap} | {text}")
if a.realtime_run:
    c0, c1 = (float(x) for x in a.caption_window.split(","))
    fast = [iv for iv in fast if not (iv[0] < c1 and iv[1] > c0)]  # the run itself is not sped up
    en = f"enable='between(t,{c0},{c1})'"
    font = "C\\:/Windows/Fonts/seguisb.ttf"
    mono = "C\\:/Windows/Fonts/consolab.ttf"
    vf = ",".join([
        f"drawbox=x=352:y=758:w=736:h=124:color=0x0B0D0E:t=fill:{en}",
        f"drawbox=x=360:y=766:w=720:h=108:color=0xFFB020:t=1:{en}",
        f"drawtext=fontfile='{mono}':text='R E A L   T I M E':fontsize=13:fontcolor=0xFFB020:x=(w-text_w)/2:y=781:{en}",
        f"drawtext=fontfile='{font}':text='{REAL_1}':fontsize=21:fontcolor=white:x=(w-text_w)/2:y=805:{en}",
        f"drawtext=fontfile='{font}':text='{REAL_2}':fontsize=21:fontcolor=white:x=(w-text_w)/2:y=835:{en}",
    ])
    patched = work / "source_patched.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vf", vf, "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", "17", "-an", str(patched)], check=True)
    src = patched
log = work / "captions.log"
log.write_text("\n".join(lines) + "\n", encoding="utf-8")
fjson = work / "fast.json"
fjson.write_text(json.dumps(fast))
fb.DEMO = work  # intermediates (picture, audio mix, timeline) go here
fb.NARR = work / "narration"
sys.argv = [sys.argv[0], "--src", str(src), "--fast", str(fjson), "--log", str(log), "--out", str(DEMO / "nazar_agent_film.mp4")]
sys.exit(fb.main())
