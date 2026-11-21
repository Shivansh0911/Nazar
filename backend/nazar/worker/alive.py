"""Tiny liveness marker so scripts can tell whether a worker is running."""
from __future__ import annotations

import os
import threading
import time

from ..core import storage

MARK = "logs/worker.alive"


def touch() -> None:
    p = storage.local_path(MARK)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"{os.getpid()} {time.time():.0f}")


def is_alive(max_age_s: float = 30.0) -> bool:
    p = storage.local_path(MARK)
    try:
        return time.time() - p.stat().st_mtime < max_age_s
    except OSError:
        return False


def loop(stop: threading.Event, every: float = 10.0) -> None:
    while not stop.is_set():
        try:
            touch()
        except Exception:
            pass
        stop.wait(every)
