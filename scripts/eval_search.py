"""Search quality: hit@3 and confidently-wrong rate over questions with ground-truth time windows.

    python scripts/eval_search.py --file scripts/eval/questions.yaml [--api http://localhost:8000]

For each question it calls /api/ask (text) and checks whether a returned clip overlaps a truth window in the top 3.
Confidently wrong = a Confirmed/Probable clip that overlaps no truth window. Saves data/eval/latest.json -> search.
Needs the API running with OPENAI_API_KEY set.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import yaml  # noqa: E402

from nazar.core.config import get_settings  # noqa: E402
from nazar.core.timeutil import parse_local  # noqa: E402


def post(api: str, path: str, body: dict, tok: str | None = None, timeout: int = 120) -> dict:
    req = urllib.request.Request(api + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **({"X-Nazar-Token": tok} if tok else {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def overlaps(a0, a1, b0, b1) -> bool:
    return a0 <= b1 and b0 <= a1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=str(ROOT / "scripts" / "eval" / "questions.yaml"))
    ap.add_argument("--api", default="http://localhost:8000")
    args = ap.parse_args()
    s = get_settings()
    qs = [q for q in (yaml.safe_load(Path(args.file).read_text(encoding="utf-8")) or {}).get("questions", [])
          if q.get("truth")]
    if not qs:
        print("no questions with truth windows in", args.file)
        return 1
    tok = post(args.api, "/api/auth", {"passcode": s.DEMO_PASSCODE})["token"]
    rows, hits, wrong, shown, lat = [], 0, 0, 0, []
    for q in qs:
        truth = [(parse_local(w["from"]), parse_local(w["to"])) for w in q["truth"]]
        t0 = time.perf_counter()
        try:
            r = post(args.api, "/api/ask", {"text": q["q"], "camera_id": q.get("camera_id")}, tok)
        except Exception as e:
            print(f"ERROR {q['q']}: {e}")
            continue
        lat.append((time.perf_counter() - t0) * 1000)
        clips = r.get("clips", [])
        top = clips[:3]
        hit = any(any(overlaps(parse_local(c["t_start"]), parse_local(c["t_end"]), a, b) for a, b in truth) for c in top)
        cw = [c for c in clips if c["level"] in ("confirmed", "probable")
              and not any(overlaps(parse_local(c["t_start"]), parse_local(c["t_end"]), a, b) for a, b in truth)]
        hits += hit
        wrong += len(cw)
        shown += sum(1 for c in clips if c["level"] in ("confirmed", "probable"))
        rows.append({"q": q["q"], "hit@3": hit, "clips": len(clips), "confidently_wrong": len(cw),
                     "reply": r.get("reply_text"), "latency_ms": round(lat[-1])})
        print(f"{'HIT ' if hit else 'MISS'}  {q['q']}  ({len(clips)} clips, {len(cw)} confidently wrong)")
    n = len(rows)
    out = {"n": n, "hit_at_3": round(hits / n, 3) if n else None,
           "confidently_wrong_rate": round(wrong / shown, 3) if shown else 0.0,
           "avg_latency_ms": round(sum(lat) / len(lat)) if lat else None,
           "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "rows": rows}
    d = s.data_dir / "eval"
    d.mkdir(parents=True, exist_ok=True)
    lp = d / "latest.json"
    latest = json.loads(lp.read_text(encoding="utf-8")) if lp.exists() else {}
    latest["search"] = {k: v for k, v in out.items() if k != "rows"}
    lp.write_text(json.dumps(latest, indent=2), encoding="utf-8")
    (d / "search.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nhit@3 {out['hit_at_3']}  confidently-wrong {out['confidently_wrong_rate']}  avg latency {out['avg_latency_ms']} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
