"""Cost per camera-day vs. the naive 'every frame to AI' baseline (same logic as /api/metrics).

    python scripts/cost_report.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from nazar.api.routes_metrics import compute_metrics  # noqa: E402


def inr(v, d=2):
    return "—" if v is None else f"₹{v:,.{d}f}"


def main() -> int:
    m = compute_metrics()
    print(f"Measured {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC on {m['footage_hours']:.2f} h of footage, "
          f"{m['tracks_processed']} tracks")
    print(f"  total OpenAI spend        {inr(m['total_inr'])}  (${m['total_usd']:.4f})")
    for k in m["by_kind"]:
        print(f"    {k['kind']:<12} {inr(k['inr']):>10}  ×{k['calls']}")
    print(f"  enrichment spend          ${m['enrich_usd']:.4f}")
    print(f"  cost per camera-day       {inr(m['cost_per_camera_day_inr'])}")
    per_img = m.get("per_image_usd")
    print(f"  one caption image         {'—' if per_img is None else f'${per_img:.6f}'}")
    print(f"  tracks described          {m.get('tracks_described')}  (${m.get('per_track_usd') or 0:.6f} per track)")
    print(f"  naive per camera-day      {inr(m['naive_per_camera_day_inr'], 0)}  (one {m.get('baseline_kind')} per second, 86,400/day)")
    print(f"  ratio                     {'—' if not m['ratio'] else f'{m['ratio']:,.0f}x cheaper'}")
    if m["cost_per_camera_day_inr"] is None:
        print("\nNo enrichment cost yet: set OPENAI_API_KEY and run the worker so tracks get captioned.")
    if m["unknown_price_calls"]:
        print(f"\nWarning: {m['unknown_price_calls']} calls used a model without a price (set PRICES_JSON).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
