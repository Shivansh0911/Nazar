"""WebSocket hub: alerts via Postgres LISTEN (dedicated thread) + camera status every 5 s."""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..core import db
from .auth import valid

log = logging.getLogger("nazar.ws")
router = APIRouter()


class Hub:
    def __init__(self):
        self.clients: dict[WebSocket, str] = {}
        self.loop: asyncio.AbstractEventLoop | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        if self._thread is None:
            self._thread = threading.Thread(target=self._listen, name="pg-listen", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _listen(self) -> None:
        while not self._stop.is_set():
            try:
                conn = db.connect_raw(autocommit=True)
                conn.execute("LISTEN nazar_alerts")
                log.info("listening for alerts")
                while not self._stop.is_set():
                    for n in conn.notifies(timeout=1.0):
                        if self.loop is not None:
                            asyncio.run_coroutine_threadsafe(self._on_notify(n.payload), self.loop)
            except Exception as e:
                log.warning("LISTEN connection problem (%s); retrying", e)
                time.sleep(3)

    async def _on_notify(self, payload: str) -> None:
        from .routes_alerts import get_alert

        aid_s, _, what = payload.partition(":")
        try:
            aid = int(aid_s)
        except ValueError:
            return
        for ws, token in list(self.clients.items()):
            try:
                alert = await asyncio.to_thread(get_alert, aid, token)
                if alert:
                    await ws.send_json({"type": "alert", "update": bool(what), "alert": alert})
            except Exception:
                self.clients.pop(ws, None)

    async def broadcast(self, msg: dict) -> None:
        data = json.dumps(msg, default=str)
        for ws in list(self.clients):
            try:
                await ws.send_text(data)
            except Exception:
                self.clients.pop(ws, None)


hub = Hub()


async def status_pusher() -> None:
    from .routes_cameras import camera_rows

    while True:
        await asyncio.sleep(5)
        if not hub.clients:
            continue
        try:
            rows = await asyncio.to_thread(camera_rows)
            await hub.broadcast({"type": "camera_status", "cameras": [
                {"id": r["id"], "live": r["live"], "edge_running": r["edge_running"], "today_count": r["today_count"],
                 "last_heartbeat_age_s": r["last_heartbeat_age_s"], "status_note": r["status_note"]} for r in rows]})
        except Exception as e:
            log.warning("status push failed: %s", e)


@router.websocket("/api/ws")
async def ws_endpoint(ws: WebSocket):
    token = ws.query_params.get("token")
    if not valid(token):
        await ws.close(code=4401)
        return
    await ws.accept()
    hub.clients[ws] = token  # type: ignore[assignment]
    try:
        await ws.send_json({"type": "hello"})
        while True:
            msg = await ws.receive_text()
            if msg == "ping":
                await ws.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        pass
    finally:
        hub.clients.pop(ws, None)
