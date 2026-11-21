"""Re-download and normalize the demo clips listed in samples/sources.yaml.

    python scripts/fetch_samples.py            # demo clips + extras
    python scripts/fetch_samples.py --only clip6_bag --force

Normalization: H.264, yuv420p, max 1280 px wide, max 30 fps, no audio, <= 5 minutes.
Entries with `raw: true` are kept as downloaded (used to test upload of 4K / portrait files).
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import yaml  # noqa: E402

from nazar.core.config import ffmpeg_bin, ffprobe_bin  # noqa: E402

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"


def http_get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(req, timeout=180) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    os.replace(tmp, dest)


def pexels_file_url(pid: int, slug: str, prefer_width: int = 1920) -> str:
    html = http_get(f"https://www.pexels.com/video/{slug}-{pid}/").decode("utf-8", "ignore")
    files = sorted(set(re.findall(r"https://videos\.pexels\.com/video-files/%d/[^\"\\]+?\.mp4" % pid, html)))
    if not files:
        raise RuntimeError(f"no video files found on the Pexels page for {pid}")

    def dims(f: str) -> tuple[int, int]:
        m = re.search(r"_(\d+)_(\d+)_", f)
        return (int(m.group(1)), int(m.group(2))) if m else (0, 0)

    # choose the file whose longer side is closest to (but not above) prefer_width
    def score(f: str):
        w, h = dims(f)
        side = max(w, h)
        return (side <= prefer_width, side)

    return max(files, key=score)


def normalize(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.stem + ".tmp.mp4")
    cmd = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-t", "300", "-an",
           "-vf", "scale='min(1280,iw)':-2", "-fpsmax", "30", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(tmp)]
    subprocess.run(cmd, check=True, timeout=900)
    os.replace(tmp, dst)


def ffprobe_summary(p: Path) -> str:
    r = subprocess.run([ffprobe_bin(), "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=codec_name,width,height,avg_frame_rate,pix_fmt:format=duration", "-of",
                        "default=nw=1:nk=0", str(p)], capture_output=True, text=True, timeout=60)
    return " ".join(r.stdout.split())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="substring of the output file name")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-extras", action="store_true")
    args = ap.parse_args()
    cfg = yaml.safe_load((ROOT / "samples" / "sources.yaml").read_text(encoding="utf-8"))
    entries = list(cfg.get("clips", [])) + ([] if args.no_extras else list(cfg.get("extras", [])))
    raw_dir = ROOT / "samples" / "raw"
    failed = []
    for e in entries:
        out = ROOT / e["out"]
        if args.only and args.only not in out.name:
            continue
        if out.exists() and not args.force:
            print(f"ok (exists)  {e['out']}  {ffprobe_summary(out)}")
            continue
        try:
            if e["source"] == "pexels":
                url = pexels_file_url(int(e["pexels_id"]), e["slug"], int(e.get("prefer_width", 1920)))
                raw = raw_dir / f"px_{e['pexels_id']}_{Path(url).name}"
            else:
                url = e["url"]
                raw = raw_dir / Path(url).name
            if not raw.exists() or args.force:
                print(f"download {url}")
                download(url, raw)
            if e.get("raw"):
                out.parent.mkdir(parents=True, exist_ok=True)
                with open(raw, "rb") as fi, open(out, "wb") as fo:
                    fo.write(fi.read())
            else:
                normalize(raw, out)
            print(f"ok           {e['out']}  {ffprobe_summary(out)}")
        except Exception as ex:  # keep going; list what to fetch by hand
            failed.append((e, ex))
            print(f"FAILED       {e['out']}: {ex}")
    if failed:
        print("\nSome downloads failed. Fetch these pages manually and save the video as the given file:")
        for e, _ in failed:
            print(f"  {e.get('page')}  ->  {e['out']}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
