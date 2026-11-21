"""Worker (one process, several threads):  python -m nazar.worker.run

eventize (1 s) -> rules (live) + count tick (1 s) | stitcher (5 s) | enricher (2 s) | jobs (2 s) | retention (1 h)
"""
from __future__ import annotations

import argparse
import logging
import queue
import signal
import sys
import threading

from ..core import db
from ..core.config import get_settings
from ..core.logging import setup_logging
from ..core.migrate import migrate
from . import alive, enricher, eventize_loop, retention, rules_loop, stitcher

log = logging.getLogger("nazar.worker")


def jobs_once(ev: eventize_loop.Eventizer) -> int:
    """Move upload/demo jobs to `ready` once their tracks are eventized (and enriched when a key exists)."""
    has_key = get_settings().has_openai
    n = 0
    for j in db.fetch_all("SELECT id, camera_id FROM jobs WHERE state='enriching'"):
        pending_events = db.fetch_val(
            "SELECT count(*) FROM tracks WHERE job_id=%s AND updated_at > %s", (j["id"], ev.cursor)) if ev.cursor else 1
        if pending_events:
            continue
        if has_key:
            left = db.fetch_val(
                """SELECT count(*) FROM tracks WHERE job_id=%s AND enriched=false AND active=false AND merged_into IS NULL
                     AND enrich_attempts < %s AND t_end - t_start >= make_interval(secs => %s)""",
                (j["id"], enricher.MAX_ATTEMPTS, get_settings().ENRICH_MIN_SECONDS))
            if left:
                continue
            db.execute("UPDATE jobs SET state='ready', updated_at=now() WHERE id=%s", (j["id"],))
        else:
            db.execute("UPDATE jobs SET state='ready', note='events ready; descriptions need OPENAI_API_KEY', "
                       "updated_at=now() WHERE id=%s", (j["id"],))
        n += 1
    return n


def jobs_loop(stop: threading.Event, ev: eventize_loop.Eventizer) -> None:
    while not stop.is_set():
        try:
            jobs_once(ev)
        except Exception as e:
            log.exception("jobs loop error: %s", e)
        stop.wait(2.0)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-retention", action="store_true")
    args = ap.parse_args(argv)
    s = get_settings()
    (s.data_dir / "logs").mkdir(parents=True, exist_ok=True)
    setup_logging("nazar.worker", logfile=str(s.data_dir / "logs" / "worker.log"))
    migrate(verbose=False)
    stop = threading.Event()

    def _stop(*_):
        log.info("stopping worker")
        stop.set()

    signal.signal(signal.SIGINT, _stop)
    try:
        signal.signal(signal.SIGTERM, _stop)
    except Exception:
        pass

    q: "queue.Queue[dict]" = queue.Queue(maxsize=5000)
    ev = eventize_loop.Eventizer(q)
    engine = rules_loop.RuleEngine()
    enr = enricher.Enricher()
    threads = [
        threading.Thread(target=eventize_loop.loop, args=(stop, ev), name="eventize", daemon=True),
        threading.Thread(target=rules_loop.loop, args=(stop, engine, q, lambda cam: ev.zones.get(cam, [])),
                         name="rules", daemon=True),
        threading.Thread(target=stitcher.loop, args=(stop,), name="stitcher", daemon=True),
        threading.Thread(target=enricher.loop, args=(stop, enr), name="enricher", daemon=True),
        threading.Thread(target=jobs_loop, args=(stop, ev), name="jobs", daemon=True),
        threading.Thread(target=alive.loop, args=(stop,), name="alive", daemon=True),
    ]
    if not args.no_retention:
        threads.append(threading.Thread(target=retention.loop, args=(stop,), name="retention", daemon=True))
    for t in threads:
        t.start()
    log.info("worker running (openai=%s)", "yes" if s.has_openai else "no - enrichment paused")
    try:
        while not stop.is_set():
            stop.wait(30)
            log.info("worker: eventized=%d alerts=%d enriched=%d%s", ev.processed, engine.fired, enr.done,
                     f" (enricher paused: {enr.paused_reason})" if enr.paused_reason else "")
    except KeyboardInterrupt:
        stop.set()
    for t in threads:
        t.join(timeout=5)
    db.close_pool()
    return 0


if __name__ == "__main__":
    sys.exit(main())
