"""Reprocess raw recordings written by MediaMTX (RECORD_RAW=1) through the edge pipeline.

    python scripts/process_recordings.py --camera hall-1 --dir data/recordings/hall-1

File names follow MediaMTX's recordPath `%Y-%m-%d_%H-%M-%S-%f` (local time of the recorder). Files are processed in
time order with --fast and --start-time parsed from the name.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from nazar.core.timeutil import tz  # noqa: E402

NAME_RE = re.compile(r"(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})-(\d{2})-(\d{1,6})")


def parse_start(name: str) -> datetime | None:
    m = NAME_RE.search(name)
    if not m:
        return None
    d, hh, mm, ss, frac = m.groups()
    us = int(frac.ljust(6, "0")[:6])
    return datetime.fromisoformat(f"{d}T{hh}:{mm}:{ss}").replace(microsecond=us, tzinfo=tz())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", required=True)
    ap.add_argument("--dir", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    files = []
    for p in Path(args.dir).iterdir():
        if p.suffix.lower() in (".mp4", ".m4s", ".ts", ".mkv"):
            t = parse_start(p.name)
            if t is None:
                print(f"skip (no time in name): {p.name}")
                continue
            files.append((t, p))
    files.sort()
    if not files:
        print("no recordings found")
        return 1
    for t, p in files:
        cmd = [sys.executable, "-m", "nazar.edge.run", "--camera", args.camera, "--source", str(p.resolve()),
               "--start-time", t.isoformat(), "--fast"]
        print(f"{t:%Y-%m-%d %H:%M:%S}  {p.name}")
        if args.dry_run:
            continue
        r = subprocess.run(cmd, cwd=str(ROOT / "backend"))
        if r.returncode != 0:
            print(f"  edge failed (exit {r.returncode})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
