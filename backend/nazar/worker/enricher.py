"""Enricher: 1-3 face-blurred crops per finished root track -> vision caption + attributes -> embedding."""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from pgvector import Vector
from psycopg.types.json import Jsonb

from ..core import db, storage, usage
from ..core.config import get_settings
from ..core.openai_client import AIKeyProblem, AIUnavailable, get_ai
from ..core.schemas import TrackCaption

log = logging.getLogger("nazar.enricher")
MAX_ATTEMPTS = 3
VEHICLES = ("car", "motorcycle", "bus", "truck", "bicycle")
# finished root tracks worth describing: >= ENRICH_MIN_SECONDS, vehicles only when they stay (parked / slow)
ELIGIBLE_SQL = ("enriched = false AND active = false AND merged_into IS NULL AND enrich_attempts < 3 "
                "AND t_end - t_start >= make_interval(secs => %(min_s)s) "
                "AND (cls NOT IN ('car','motorcycle','bus','truck','bicycle') "
                "     OR t_end - t_start >= make_interval(secs => %(veh_s)s))")


def eligible_params() -> dict:
    s = get_settings()
    return {"min_s": s.ENRICH_MIN_SECONDS, "veh_s": s.ENRICH_VEHICLE_MIN_SECONDS}


def embed_text(cls: str, c: TrackCaption) -> str:
    carrying = ", ".join(c.carrying) if c.carrying else "nothing"
    return (f"{cls}. {c.caption}. upper {c.upper_color}, lower {c.lower_color}. headwear {c.headwear}. "
            f"carrying {carrying}. action {c.action}. vehicle {c.vehicle_type} {c.vehicle_color}. {c.notable}").strip()


class Enricher:
    def __init__(self):
        self.s = get_settings()
        self.pool = ThreadPoolExecutor(max_workers=max(1, self.s.ENRICH_CONCURRENCY), thread_name_prefix="enrich")
        self.paused_reason: str | None = None
        self.done = 0

    def _candidates(self, limit: int = 32) -> list[dict]:
        return db.fetch_all(
            f"SELECT id, camera_id, cls, crop_keys FROM tracks WHERE {ELIGIBLE_SQL} ORDER BY t_end DESC LIMIT %(limit)s",
            {**eligible_params(), "limit": limit})

    def _caption(self, tr: dict):
        imgs = []
        for k in (tr["crop_keys"] or [])[:3]:
            p = storage.local_path(k)
            if p.exists():
                imgs.append(p.read_bytes())
        if not imgs:
            raise ValueError("no crops on disk")
        cap, _ = get_ai().caption_track(imgs, tr["cls"], camera_id=tr["camera_id"], ref=str(tr["id"]))
        return cap

    def run_once(self) -> int:
        ai = get_ai()
        if not ai.available():
            self.paused_reason = "OPENAI_API_KEY not set"
            return 0
        spent = usage.spent_today(("caption", "embed"))
        if spent >= self.s.ENRICH_DAILY_USD_CAP:
            if self.paused_reason != "cap":
                log.warning("daily enrichment cap reached ($%.2f >= $%.2f); pausing", spent, self.s.ENRICH_DAILY_USD_CAP)
            self.paused_reason = "cap"
            return 0
        self.paused_reason = None
        rows = self._candidates()
        if not rows:
            return 0
        futures = {self.pool.submit(self._caption, r): r for r in rows}
        ok: list[tuple[dict, TrackCaption]] = []
        for f, r in futures.items():
            try:
                ok.append((r, f.result()))
            except (AIUnavailable, AIKeyProblem) as e:
                log.error("enrichment stopped: %s", e)
                self.paused_reason = str(e)
                return 0
            except Exception as e:
                log.warning("caption failed for track %s: %s", r["id"], e)
                db.execute("UPDATE tracks SET enrich_attempts = enrich_attempts + 1, enrich_error=%s WHERE id=%s",
                           (str(e)[:300], r["id"]))
        if not ok:
            return 0
        try:
            vecs = ai.embed([embed_text(r["cls"], c) for r, c in ok], camera_id=None, ref="enrich")
        except Exception as e:
            log.warning("embedding failed: %s", e)
            for r, _ in ok:
                db.execute("UPDATE tracks SET enrich_attempts = enrich_attempts + 1, enrich_error=%s WHERE id=%s",
                           (f"embed: {e}"[:300], r["id"]))
            return 0
        with db.conn() as c:
            for (r, cap), v in zip(ok, vecs):
                c.execute("UPDATE tracks SET caption=%s, attrs=%s, caption_emb=%s, enriched=true, enrich_error=NULL "
                          "WHERE id=%s", (cap.caption, Jsonb(cap.model_dump()), Vector(v), r["id"]))
        self.done += len(ok)
        log.info("enriched %d track(s)", len(ok))
        return len(ok)


def loop(stop: threading.Event, enr: Enricher, interval: float = 2.0) -> None:
    backoff = interval
    while not stop.is_set():
        try:
            n = enr.run_once()
            backoff = interval
            if n:
                continue
        except Exception as e:
            log.exception("enricher error: %s", e)
            backoff = min(60.0, backoff * 2)
        stop.wait(backoff)
