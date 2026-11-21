"""Count accuracy against a human ground truth (counts come from SQL, exactly like /api/ask).

    python scripts/eval_counts.py --camera shop-counter --from "yesterday 18:30" --to "yesterday 18:31" --truth 5
    python scripts/eval_counts.py --camera lobby --zone entrance --event enter --from ... --to ... --truth 37

Result is appended to data/eval/counts.json and summarized into data/eval/latest.json (shown on /metrics).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from nazar.api.agent_tools import count_events  # noqa: E402
from nazar.core.config import get_settings  # noqa: E402
from nazar.core.timeutil import parse_local  # noqa: E402


def save(entry: dict) -> dict:
    d = get_settings().data_dir / "eval"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "counts.json"
    rows = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
    rows.append(entry)
    p.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    latest_p = d / "latest.json"
    latest = json.loads(latest_p.read_text(encoding="utf-8")) if latest_p.exists() else {}
    accs = [r["accuracy"] for r in rows]
    latest["counts"] = {"n": len(rows), "mean_accuracy": round(sum(accs) / len(accs), 3),
                        "last": entry, "measured_at": entry["measured_at"]}
    latest_p.write_text(json.dumps(latest, indent=2), encoding="utf-8")
    return latest["counts"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", required=True)
    ap.add_argument("--zone")
    ap.add_argument("--event", default=None, help="enter | exit | dwell | present (default: enter with a zone, else present)")
    ap.add_argument("--cls", default="person")
    ap.add_argument("--from", dest="t_from", required=True)
    ap.add_argument("--to", dest="t_to", required=True)
    ap.add_argument("--truth", type=int, required=True, help="your manual count for the same window")
    args = ap.parse_args()
    event = args.event or ("enter" if args.zone else "present")
    r = count_events({"camera_id": args.camera, "zone": args.zone, "cls": args.cls, "event": event,
                      "time_from": parse_local(args.t_from), "time_to": parse_local(args.t_to)})
    pred = r["value"]
    acc = 1.0 - abs(pred - args.truth) / max(1, args.truth)
    entry = {"camera": args.camera, "zone": args.zone, "event": event, "cls": args.cls, "from": r["time_from"],
             "to": r["time_to"], "predicted": pred, "truth": args.truth, "accuracy": round(max(0.0, acc), 3),
             "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    summary = save(entry)
    print(f"predicted {pred} vs truth {args.truth} -> accuracy {entry['accuracy']:.0%}  "
          f"(mean over {summary['n']} evals: {summary['mean_accuracy']:.0%})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
