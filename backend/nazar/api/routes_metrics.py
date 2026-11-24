"""Cost truth (W13): measured unit costs from `usage` rows - indexing is local (Rs 0 AI), you pay per question,
per verification, per report and for optional on-demand captions. Plus latency, accuracy and pipeline speed."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends

from ..core import db
from ..core.config import get_settings
from .auth import require_token

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])
V2_SINCE = "2026-11-22 00:30:00+05:30"  # queries/usage after the v2 agent went live (unit costs use these)


def _pct(sql: str, params=None) -> dict:
    r = db.fetch_one(sql, params)
    return {k: (float(v) if v is not None else None) for k, v in (r or {}).items()}


def _load(path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except Exception:
        return None


def compute_metrics() -> dict:
    s = get_settings()
    inr = s.USD_INR
    total = float(db.fetch_val("SELECT COALESCE(sum(cost_usd),0) FROM usage") or 0)
    today = float(db.fetch_val("SELECT COALESCE(sum(cost_usd),0) FROM usage WHERE at >= date_trunc('day', now() AT TIME "
                               "ZONE 'Asia/Kolkata') AT TIME ZONE 'Asia/Kolkata'") or 0)
    by_kind = [{"kind": r["kind"], "usd": float(r["usd"]), "inr": round(float(r["usd"]) * inr, 2), "calls": r["n"]}
               for r in db.fetch_all("SELECT kind, sum(cost_usd) usd, count(*) n FROM usage GROUP BY 1 ORDER BY 2 DESC")]
    by_model = [{"model": r["model"], "usd": float(r["usd"]), "inr": round(float(r["usd"]) * inr, 2), "calls": r["n"]}
                for r in db.fetch_all("SELECT model, sum(cost_usd) usd, count(*) n FROM usage GROUP BY 1 ORDER BY 2 DESC")]
    by_tier = [{"tier": r["t"] or "standard", "calls": r["n"], "inr": round(float(r["usd"]) * inr, 2)}
               for r in db.fetch_all("SELECT service_tier t, count(*) n, sum(cost_usd) usd FROM usage GROUP BY 1")]
    footage_h = float(db.fetch_val("SELECT COALESCE(sum(extract(epoch FROM t_end - t_start)),0) FROM coverage") or 0) / 3600
    indexed = db.fetch_one("SELECT count(*) FILTER (WHERE vis_emb IS NOT NULL) tr, count(*) total FROM tracks")
    kf = int(db.fetch_val("SELECT count(*) FROM keyframes WHERE emb IS NOT NULL") or 0)
    # per question (v2 agent): total cost of each question incl. its tools, verification and voice reply
    q = _pct("SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY cost_usd) p50, percentile_cont(0.9) WITHIN GROUP "
             "(ORDER BY cost_usd) p90, count(*) n FROM queries WHERE created_at >= %s AND model IS NOT NULL", (V2_SINCE,))
    lat = _pct("SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) p50, percentile_cont(0.9) WITHIN GROUP "
               "(ORDER BY latency_ms) p90, percentile_cont(0.5) WITHIN GROUP (ORDER BY first_text_ms) f50, "
               "percentile_cont(0.9) WITHIN GROUP (ORDER BY first_text_ms) f90, count(*) n FROM queries "
               "WHERE created_at >= %s AND model IS NOT NULL", (V2_SINCE,))
    models = [{"model": r["model"], "n": r["n"]} for r in db.fetch_all(
        "SELECT model, count(*) n FROM queries WHERE created_at >= %s AND model IS NOT NULL GROUP BY 1", (V2_SINCE,))]
    ver = _pct("SELECT avg(cost_usd) per_call, sum(cost_usd) / NULLIF(sum(images),0) per_image, count(*) n "
               "FROM usage WHERE kind='verify'")
    rep = _pct("SELECT avg(c) per_report, count(*) n FROM (SELECT sum(cost_usd) c FROM usage WHERE kind IN "
               "('report','describe') AND ref LIKE 'report:%%' GROUP BY ref) x")
    cap = _pct("SELECT avg(cost_usd) per_caption, count(*) n FROM usage WHERE kind='caption' AND at >= %s", (V2_SINCE,))
    cap_all = _pct("SELECT avg(cost_usd) per_caption, count(*) n FROM usage WHERE kind='caption'")
    captions_today = float(db.fetch_val("SELECT COALESCE(sum(cost_usd),0) FROM usage WHERE kind IN ('caption','embed') "
                                        "AND at >= now() - interval '24 hours'") or 0)
    per_q = q.get("p50")
    per_cap = cap.get("per_caption") or cap_all.get("per_caption")
    emb = _pct("SELECT avg(cost_usd) per_call, sum(cost_usd) total, count(*) n FROM usage WHERE kind='embed'")
    dist = {"confirmed": 0, "probable": 0, "candidate": 0}
    for r in db.fetch_all("SELECT answer FROM queries WHERE answer IS NOT NULL ORDER BY id DESC LIMIT 500"):
        ans = r["answer"] or {}
        for c in ans.get("clips") or []:
            if c.get("level") in dist:
                dist[c["level"]] += 1
        if ans.get("count"):
            dist["confirmed"] += 1
    ev_dir = s.data_dir / "eval"
    bench = _load(ev_dir / "bench.json")
    acc = {"counts": _load(ev_dir / "count_accuracy.json"), "tracking": _load(ev_dir / "tracking.json"),
           "battery": _load(ev_dir / "battery.json"), "security": _load(ev_dir / "security.json"),
           "languages": _load(ev_dir / "languages.json"), "legacy": _load(ev_dir / "latest.json")}
    from ..worker.enricher import ELIGIBLE_SQL, eligible_params

    backlog = int(db.fetch_val(f"SELECT count(*) FROM tracks WHERE {ELIGIBLE_SQL}", eligible_params()) or 0)
    unknown = int(db.fetch_val("SELECT count(*) FROM usage WHERE unknown_price") or 0)

    def r_inr(v):
        return round(v * inr, 3) if v is not None else None

    return {
        "usd_inr": inr, "total_usd": round(total, 6), "total_inr": round(total * inr, 2),
        "today_inr": round(today * inr, 2), "by_kind": by_kind, "by_model": by_model, "by_tier": by_tier,
        "enrich_mode": (s.ENRICH_MODE or "smart").lower(),
        "unit_costs": {
            "index_per_hour_inr": 0.0,  # SigLIP 2 + YOLO run locally: no AI call while indexing
            "question_p50_inr": r_inr(per_q), "question_p90_inr": r_inr(q.get("p90")), "questions": int(q.get("n") or 0),
            "verify_per_call_inr": r_inr(ver.get("per_call")), "verify_per_image_inr": r_inr(ver.get("per_image")),
            "verifications": int(ver.get("n") or 0),
            "report_inr": r_inr(rep.get("per_report")), "reports": int(rep.get("n") or 0),
            "embed_calls": int(emb.get("n") or 0), "embed_total_inr": round(float(emb.get("total") or 0) * inr, 4),
            "embed_per_call_inr": r_inr(emb.get("per_call")),
            "caption_inr": r_inr(per_cap), "captions_24h_inr": round(captions_today * inr, 2),
        },
        "latency": {"p50_ms": lat.get("p50"), "p90_ms": lat.get("p90"), "first_text_p50_ms": lat.get("f50"),
                    "first_text_p90_ms": lat.get("f90"), "n": int(lat.get("n") or 0), "models": models},
        "index": {"footage_hours": round(footage_h, 2), "tracks": int(indexed["total"] or 0),
                  "tracks_indexed": int(indexed["tr"] or 0), "keyframes_indexed": kf},
        "pipeline": bench, "accuracy": acc, "level_distribution": dist, "enrich_backlog": backlog,
        "unknown_price_calls": unknown,
        # v1 fields kept for old clients
        "footage_hours": round(footage_h, 3), "tracks_processed": int(indexed["total"] or 0),
        "ask_latency_p50_ms": lat.get("p50"), "ask_latency_p90_ms": lat.get("p90"), "query_count": int(lat.get("n") or 0),
        "cost_per_camera_day_inr": None, "naive_per_camera_day_inr": None, "ratio": None, "eval": None,
    }


@router.get("/metrics")
def metrics():
    return compute_metrics()
