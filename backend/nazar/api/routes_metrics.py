"""Cost per camera-day (measured from usage rows) vs. a naive 'every frame to AI' baseline."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends

from ..core import db
from ..core.config import get_settings
from .auth import require_token

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])
SECONDS_PER_DAY = 86_400


def compute_metrics() -> dict:
    s = get_settings()
    inr = s.USD_INR
    total = float(db.fetch_val("SELECT COALESCE(sum(cost_usd),0) FROM usage") or 0)
    by_kind = [{"kind": r["kind"], "usd": float(r["usd"]), "inr": round(float(r["usd"]) * inr, 2), "calls": r["n"]}
               for r in db.fetch_all("SELECT kind, sum(cost_usd) usd, count(*) n FROM usage GROUP BY 1 ORDER BY 2 DESC")]
    by_model = [{"model": r["model"], "usd": float(r["usd"]), "inr": round(float(r["usd"]) * inr, 2), "calls": r["n"]}
                for r in db.fetch_all("SELECT model, sum(cost_usd) usd, count(*) n FROM usage GROUP BY 1 ORDER BY 2 DESC")]
    # footage actually watched by the edge (stored segments)
    footage_h = float(db.fetch_val("SELECT COALESCE(sum(extract(epoch FROM t_end - t_start)),0) FROM coverage") or 0) / 3600
    # cost of describing the footage we hold: the latest caption call of every enriched track (+ embeddings);
    # re-enrichment experiments still show in total spend, but do not inflate the per-camera-day figure
    cap_usd = float(db.fetch_val(
        """SELECT COALESCE(sum(c.cost_usd),0) FROM (
             SELECT DISTINCT ON (u.ref) u.cost_usd FROM usage u JOIN tracks t ON t.id::text = u.ref
              WHERE u.kind='caption' AND t.enriched ORDER BY u.ref, u.at DESC) c""") or 0)
    emb_usd = float(db.fetch_val("SELECT COALESCE(sum(cost_usd),0) FROM usage WHERE kind='embed' AND ref='enrich'") or 0)
    enrich_usd = cap_usd + emb_usd
    described = int(db.fetch_val("SELECT count(*) FROM tracks WHERE enriched") or 0)
    # naive baseline: one image per second at the measured price of one caption image. Conservative: a real
    # "every frame to AI" system would send full frames (more tokens) - which Nazar never does (privacy rule).
    cap = db.fetch_one("SELECT COALESCE(sum(cost_usd),0) usd, COALESCE(sum(images),0) imgs FROM usage WHERE kind='caption'")
    per_image = float(cap["usd"]) / int(cap["imgs"]) if cap and int(cap["imgs"] or 0) > 0 else None
    baseline_kind = "caption-sized image (measured price)"
    cost_day = (enrich_usd / footage_h * 24 * inr) if footage_h > 0 and enrich_usd > 0 else None
    naive_day = per_image * SECONDS_PER_DAY * inr if per_image else None
    ratio = (naive_day / cost_day) if (naive_day and cost_day) else None
    tracks = int(db.fetch_val("SELECT count(*) FROM tracks") or 0)
    from ..worker.enricher import ELIGIBLE_SQL, eligible_params

    backlog = int(db.fetch_val(f"SELECT count(*) FROM tracks WHERE {ELIGIBLE_SQL}", eligible_params()) or 0)
    lat = db.fetch_one("SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) p50, "
                       "percentile_cont(0.9) WITHIN GROUP (ORDER BY latency_ms) p90, count(*) n FROM queries")
    dist = {"confirmed": 0, "probable": 0, "candidate": 0}
    for r in db.fetch_all("SELECT answer FROM queries WHERE answer IS NOT NULL ORDER BY id DESC LIMIT 500"):
        ans = r["answer"] or {}
        for c in ans.get("clips") or []:
            if c.get("level") in dist:
                dist[c["level"]] += 1
        if ans.get("count"):
            dist["confirmed"] += 1
    unknown = int(db.fetch_val("SELECT count(*) FROM usage WHERE unknown_price") or 0)
    ev = None
    p = s.data_dir / "eval" / "latest.json"
    if p.exists():
        try:
            ev = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            ev = None
    return {
        "total_usd": round(total, 6), "total_inr": round(total * inr, 2), "by_kind": by_kind, "by_model": by_model,
        "cost_per_camera_day_inr": round(cost_day, 2) if cost_day is not None else None,
        "naive_per_camera_day_inr": round(naive_day, 0) if naive_day is not None else None,
        "ratio": round(ratio, 0) if ratio else None, "footage_hours": round(footage_h, 3),
        "tracks_processed": tracks, "enrich_backlog": backlog,
        "ask_latency_p50_ms": round(lat["p50"]) if lat and lat["p50"] is not None else None,
        "ask_latency_p90_ms": round(lat["p90"]) if lat and lat["p90"] is not None else None,
        "query_count": int(lat["n"]) if lat else 0, "level_distribution": dist, "unknown_price_calls": unknown,
        "enrich_usd": round(enrich_usd, 6), "per_image_usd": per_image, "baseline_kind": baseline_kind,
        "tracks_described": described,
        "per_track_usd": round(cap_usd / described, 6) if described else None,
        "per_track_inr": round(cap_usd / described * inr, 4) if described else None,
        "tracks_per_hour": round(described / footage_h) if footage_h > 0 else None, "usd_inr": inr, "eval": ev,
    }


@router.get("/metrics")
def metrics():
    return compute_metrics()
