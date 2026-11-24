"""Optional: every new alert gets an investigation (AUTO_INVESTIGATE_ALERTS=true).

The result shows up under Investigate -> Recent runs (trigger "alert"). Anything the investigator wants to send or
switch still waits for the owner's approval. One run at a time, at most MAX_PER_HOUR, so a noisy rule cannot run up a bill.
"""
from __future__ import annotations

import logging
import threading

from ..core import db
from ..core.config import get_settings

log = logging.getLogger("nazar.auto_investigate")
MAX_PER_HOUR = 6


def next_alert() -> int | None:
    """The oldest alert of the last 10 minutes that has no run yet, unless the hourly budget is used up."""
    done = db.fetch_val("SELECT count(*) FROM agent_runs WHERE trigger='alert' AND created_at > now() - interval '1 hour'")
    if int(done or 0) >= MAX_PER_HOUR:
        return None
    return db.fetch_val("SELECT a.id FROM alerts a WHERE a.created_at > now() - interval '10 minutes' AND NOT EXISTS "
                        "(SELECT 1 FROM agent_runs r WHERE r.alert_id = a.id) ORDER BY a.id LIMIT 1")


def loop(stop: threading.Event) -> None:
    s = get_settings()
    if not s.AUTO_INVESTIGATE_ALERTS or not s.has_openai:
        return
    from ..agentic import investigator

    log.info("auto-investigation of new alerts is on (max %d per hour)", MAX_PER_HOUR)
    while not stop.wait(5):
        try:
            aid = next_alert()
            if aid is None:
                continue
            goal, cam = investigator.alert_goal(int(aid))
            res = investigator.investigate(goal, cam, token=None, trigger="alert", alert_id=int(aid), voice=False)
            log.info("alert %s investigated: run %s, %d findings, %d actions waiting", aid, res["run_id"],
                     len(res["findings"]), len(res["actions"]))
        except Exception as e:
            log.warning("auto-investigation failed: %s", e)
            stop.wait(30)
