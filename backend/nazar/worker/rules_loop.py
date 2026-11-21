"""Live rule evaluation: driven by eventized tracks, plus a 1 s tick for count_over."""
from __future__ import annotations

import logging
import queue
import threading
import time
from datetime import datetime, timedelta, timezone

from ..core import db
from ..core.replay import evaluate_one
from ..core.rules import RuleSpec, evaluate_count
from . import alerts

log = logging.getLogger("nazar.rules")
GRACE = timedelta(seconds=5)


class RuleEngine:
    def __init__(self):
        self.rules: list[dict] = []
        self._loaded = 0.0
        self.last_count_hit: dict[int, int] = {}
        self.fired = 0

    def active_rules(self) -> list[dict]:
        if time.monotonic() - self._loaded > 2.0:
            rows = db.fetch_all("SELECT id, camera_id, text, spec, human, language, activated_at, created_at "
                                "FROM rules WHERE active ORDER BY id")
            out = []
            for r in rows:
                try:
                    r["rs"] = RuleSpec.model_validate(r["spec"])
                    out.append(r)
                except Exception as e:
                    log.error("rule %s has an invalid spec: %s", r["id"], e)
            self.rules = out
            self._loaded = time.monotonic()
        return self.rules

    def _since(self, rule: dict) -> datetime:
        return (rule.get("activated_at") or rule["created_at"]) - GRACE

    def on_track(self, track: dict, zones: list[dict]) -> int:
        n = 0
        for rule in self.active_rules():
            rs: RuleSpec = rule["rs"]
            if rs.camera_id != track["camera_id"] or rs.trigger == "count_over":
                continue
            if track["cls"] not in rs.classes():
                continue
            since = self._since(rule)
            if track["t_end"] < since:
                continue
            for hit in evaluate_one(rs, track, zones):
                if hit.t < since:
                    continue
                if alerts.build(rule, hit):
                    n += 1
        self.fired += n
        return n

    def count_tick(self, zones_by_cam: dict[str, list]) -> int:
        n = 0
        for rule in self.active_rules():
            rs: RuleSpec = rule["rs"]
            if rs.trigger != "count_over":
                continue
            since = max(self._since(rule), datetime.now(timezone.utc) - timedelta(seconds=90))
            tracks = db.fetch_all(
                "SELECT id, camera_id, cls, path, active, t_start, t_end FROM tracks WHERE camera_id=%s "
                "AND cls = ANY(%s) AND t_end >= %s AND merged_into IS NULL", (rs.camera_id, list(rs.classes()), since))
            hits = evaluate_count(rs, tracks, zones_by_cam.get(rs.camera_id, []),
                                  last_hit_ms=self.last_count_hit.get(rule["id"]))
            for h in hits:
                if h.t < since:
                    continue
                self.last_count_hit[rule["id"]] = h.t_ms
                if alerts.build(rule, h):
                    n += 1
        self.fired += n
        return n


def loop(stop: threading.Event, engine: RuleEngine, in_q: "queue.Queue[dict]", zones_of) -> None:
    last_tick = 0.0
    while not stop.is_set():
        try:
            try:
                tr = in_q.get(timeout=0.5)
                engine.on_track(tr, zones_of(tr["camera_id"]))
            except queue.Empty:
                pass
            if time.monotonic() - last_tick >= 1.0:
                last_tick = time.monotonic()
                engine.count_tick({r["camera_id"]: zones_of(r["camera_id"]) for r in engine.active_rules()})
        except Exception as e:
            log.exception("rules loop error: %s", e)
            stop.wait(1.0)
