"""Count accuracy against human ground truth (counts come from SQL, exactly like /api/ask).

    python scripts/eval_counts.py                      # all windows in scripts/eval/ground_truth.yaml
    python scripts/eval_counts.py --trackers           # + re-run ByteTrack vs BoT-SORT on the same footage
    python scripts/eval_counts.py --camera shop-counter --from ... --to ... --truth 5   # one ad-hoc window

Writes data/eval/count_accuracy.json (shown on the Insights page).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from nazar.api.agent_tools import count_events  # noqa: E402
from nazar.core import db  # noqa: E402
from nazar.core.config import get_settings  # noqa: E402
from nazar.core.timeutil import parse_local  # noqa: E402


def window_times(w: dict) -> tuple[datetime, datetime]:
    """The stored footage of the window's source on its camera (first original of that file)."""
    row = db.fetch_one("SELECT t_start FROM originals WHERE camera_id=%s AND path LIKE %s ORDER BY t_start LIMIT 1",
                       (w["camera"], "%" + Path(w["source"]).name))
    if not row:
        raise SystemExit(f"{w['camera']}: no stored footage for {w['source']} - run scripts/demo_setup.py")
    t0 = row["t_start"] + timedelta(seconds=w.get("offset_s", 0))
    return t0, t0 + timedelta(seconds=w["duration_s"])


def nazar_count(camera: str, t0: datetime, t1: datetime) -> int:
    return count_events({"camera_id": camera, "cls": "person", "event": "present", "time_from": t0, "time_to": t1})["value"]


def tracker_run(w: dict, tracker: str) -> int:
    """Re-process the window's footage with another tracker on a scratch camera; returns its people count."""
    cam = f"eval-{tracker}"
    db.execute("DELETE FROM cameras WHERE id=%s", (cam,))
    start = "2026-01-01T10:00:00"
    env = {**__import__("os").environ, "NAZAR_TRACKER": tracker}
    p = subprocess.run([sys.executable, "-m", "nazar.edge.run", "--camera", cam, "--source", str(ROOT / w["source"]),
                        "--start-time", start, "--max-seconds", str(w.get("offset_s", 0) + w["duration_s"])],
                       cwd=ROOT / "backend", capture_output=True, text=True, env=env)
    if p.returncode != 0:
        raise SystemExit(p.stderr[-800:])
    settings = db.fetch_one("SELECT settings FROM cameras WHERE id=%s", (w["camera"],))
    _ = settings
    # eventize/stitch are not needed for "present" counts of root tracks; stitching runs in the worker
    import time

    time.sleep(8)  # let the worker stitch fragments (root_tracks)
    t0 = parse_local(start) + timedelta(seconds=w.get("offset_s", 0))
    n = nazar_count(cam, t0, t0 + timedelta(seconds=w["duration_s"]))
    db.execute("DELETE FROM cameras WHERE id=%s", (cam,))
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trackers", action="store_true", help="also compare ByteTrack and BoT-SORT on each window")
    ap.add_argument("--camera")
    ap.add_argument("--from", dest="t_from")
    ap.add_argument("--to", dest="t_to")
    ap.add_argument("--truth", type=int)
    args = ap.parse_args()
    out_dir = get_settings().data_dir / "eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.camera:
        n = nazar_count(args.camera, parse_local(args.t_from), parse_local(args.t_to))
        print(f"{args.camera}: Nazar {n} vs truth {args.truth} ({abs(n - args.truth) / max(1, args.truth):.0%} error)")
        return 0
    gt = yaml.safe_load((ROOT / "scripts" / "eval" / "ground_truth.yaml").read_text(encoding="utf-8"))
    rows = []
    for w in gt["windows"]:
        t0, t1 = window_times(w)
        n = nazar_count(w["camera"], t0, t1)
        r = {"name": w["name"], "camera": w["camera"], "truth": w["truth"], "counted": n,
             "err_pct": round(abs(n - w["truth"]) * 100 / max(1, w["truth"]), 1), "note": w.get("note")}
        if args.trackers:
            r["bytetrack"] = tracker_run(w, "bytetrack")
            r["botsort"] = tracker_run(w, "botsort")
        rows.append(r)
        extra = f" | bytetrack {r['bytetrack']} botsort {r['botsort']}" if args.trackers else ""
        print(f"{w['name']:<45} truth {w['truth']:>3}  Nazar {n:>3}  error {r['err_pct']:>5}%{extra}")
    mae = sum(abs(r["counted"] - r["truth"]) for r in rows) / len(rows)
    exact = sum(1 for r in rows if r["counted"] == r["truth"])
    summary = f"{exact}/{len(rows)} windows exact, mean absolute error {mae:.1f} people"
    print(summary)
    (out_dir / "count_accuracy.json").write_text(json.dumps(
        {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "rows": rows, "summary": summary,
         "rule": "people seen = root tracks >= 1.5 s with max confidence >= 0.6"}, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
