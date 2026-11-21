"""Starts/stops edge subprocesses so adding a camera in the UI needs no terminal.

- never more than MAX_EDGES at once (others queue)
- live (non-file) edges are restarted with backoff when they crash
- logs: data/logs/edge_<id>.log
"""
from __future__ import annotations

import collections
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..core import db
from ..core.config import get_settings

log = logging.getLogger("nazar.edges")
BACKEND_DIR = Path(__file__).resolve().parents[2]


@dataclass
class EdgeSpec:
    camera_id: str
    args: list[str]
    live: bool
    job_id: int | None = None


@dataclass
class EdgeProc:
    spec: EdgeSpec
    proc: subprocess.Popen
    started: float
    log_path: Path
    restarts: int = 0
    stopping: bool = False


@dataclass
class EdgeManager:
    max_edges: int = 2
    running: dict[str, EdgeProc] = field(default_factory=dict)
    queue: "collections.OrderedDict[str, EdgeSpec]" = field(default_factory=collections.OrderedDict)
    restart_at: dict[str, tuple[float, EdgeSpec, int]] = field(default_factory=dict)
    lock: threading.RLock = field(default_factory=threading.RLock)
    _thread: threading.Thread | None = None
    _stop: threading.Event = field(default_factory=threading.Event)

    def start_monitor(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._monitor, name="edge-monitor", daemon=True)
            self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        for cam in list(self.running):
            self.stop(cam)

    # ---- public ----------------------------------------------------------------
    def start(self, camera_id: str, *, args: list[str] | None = None, live: bool = True, job_id: int | None = None) -> str:
        spec = EdgeSpec(camera_id, list(args or []), live, job_id)
        with self.lock:
            if camera_id in self.running and self.running[camera_id].proc.poll() is None:
                return "running"
            self.restart_at.pop(camera_id, None)
            if len(self._alive()) >= self.max_edges:
                self.queue[camera_id] = spec
                return "queued"
            self._spawn(spec)
            return "started"

    def stop(self, camera_id: str) -> bool:
        with self.lock:
            self.queue.pop(camera_id, None)
            self.restart_at.pop(camera_id, None)
            ep = self.running.get(camera_id)
            if not ep:
                return False
            ep.stopping = True
        self._terminate(ep.proc)
        with self.lock:
            self.running.pop(camera_id, None)
        self._promote()
        return True

    def status(self, camera_id: str) -> dict:
        with self.lock:
            ep = self.running.get(camera_id)
            queued = camera_id in self.queue
        out = {"camera_id": camera_id, "running": False, "queued": queued, "pid": None, "uptime_s": None,
               "restarts": 0, "last_log": []}
        lp = get_settings().data_dir / "logs" / f"edge_{camera_id}.log"
        if ep and ep.proc.poll() is None:
            out.update(running=True, pid=ep.proc.pid, uptime_s=round(time.time() - ep.started, 1), restarts=ep.restarts)
        if lp.exists():
            try:
                with open(lp, "rb") as f:
                    f.seek(max(0, lp.stat().st_size - 4000))
                    out["last_log"] = f.read().decode("utf-8", "ignore").splitlines()[-12:]
            except OSError:
                pass
        return out

    def is_running(self, camera_id: str) -> bool:
        ep = self.running.get(camera_id)
        return bool(ep and ep.proc.poll() is None)

    # ---- internals ---------------------------------------------------------------
    def _alive(self) -> list[str]:
        return [c for c, ep in self.running.items() if ep.proc.poll() is None]

    def _spawn(self, spec: EdgeSpec, restarts: int = 0) -> None:
        logs = get_settings().data_dir / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        lp = logs / f"edge_{spec.camera_id}.log"
        f = open(lp, "a", encoding="utf-8")
        f.write(f"\n==== start {time.strftime('%Y-%m-%d %H:%M:%S')} args={spec.args}\n")
        f.flush()
        cmd = [sys.executable, "-m", "nazar.edge.run", "--camera", spec.camera_id, *spec.args]
        if spec.job_id is not None and "--job" not in spec.args:
            cmd += ["--job", str(spec.job_id)]
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        p = subprocess.Popen(cmd, cwd=str(BACKEND_DIR), stdout=f, stderr=subprocess.STDOUT, env=env, **kwargs)
        self.running[spec.camera_id] = EdgeProc(spec, p, time.time(), lp, restarts)
        log.info("edge %s started (pid %d)", spec.camera_id, p.pid)

    @staticmethod
    def _terminate(p: subprocess.Popen, timeout: float = 15.0) -> None:
        if p.poll() is not None:
            return
        try:
            if os.name == "nt":
                p.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                p.send_signal(signal.SIGTERM)
            p.wait(timeout=timeout)
        except Exception:
            p.kill()

    def _promote(self) -> None:
        with self.lock:
            while self.queue and len(self._alive()) < self.max_edges:
                _, spec = self.queue.popitem(last=False)
                self._spawn(spec)

    def _monitor(self) -> None:
        while not self._stop.is_set():
            try:
                with self.lock:
                    for cam, ep in list(self.running.items()):
                        rc = ep.proc.poll()
                        if rc is None or ep.stopping:
                            continue
                        self.running.pop(cam, None)
                        if ep.spec.live:
                            delay = min(60.0, 2.0 ** min(ep.restarts + 1, 6))
                            log.warning("live edge %s exited (rc=%s); restarting in %.0fs", cam, rc, delay)
                            self.restart_at[cam] = (time.time() + delay, ep.spec, ep.restarts + 1)
                        else:
                            log.info("file edge %s finished (rc=%s)", cam, rc)
                            if rc != 0 and ep.spec.job_id:
                                db.execute("UPDATE jobs SET state='error', error=%s, updated_at=now() "
                                           "WHERE id=%s AND state IN ('queued','processing')",
                                           (f"edge exited with code {rc}; see data/logs/edge_{cam}.log", ep.spec.job_id))
                    now = time.time()
                    for cam, (when, spec, n) in list(self.restart_at.items()):
                        if now >= when and len(self._alive()) < self.max_edges:
                            self.restart_at.pop(cam, None)
                            self._spawn(spec, restarts=n)
                self._promote()
            except Exception as e:
                log.exception("edge monitor error: %s", e)
            self._stop.wait(1.0)


_manager: EdgeManager | None = None


def get_manager() -> EdgeManager:
    global _manager
    if _manager is None:
        _manager = EdgeManager(max_edges=get_settings().MAX_EDGES)
        _manager.start_monitor()
    return _manager
