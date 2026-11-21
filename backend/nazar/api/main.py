"""Nazar API:  uvicorn nazar.api.main:app --port 8000"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..core import db, storage
from ..core.config import get_settings
from ..core.logging import setup_logging
from ..core.migrate import migrate
from . import (routes_alerts, routes_ask, routes_cameras, routes_clips, routes_live, routes_metrics, routes_rules,
               routes_search, routes_upload, routes_visual, ws)
from .auth import issue, require_token
from .deps import http_error, install_error_handlers
from .edge_manager import get_manager

log = logging.getLogger("nazar.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    (s.data_dir / "logs").mkdir(parents=True, exist_ok=True)
    setup_logging("nazar.api", logfile=str(s.data_dir / "logs" / "api.log"))
    try:
        migrate(verbose=False)
    except Exception as e:
        log.error("migrations failed (is the database up?): %s", e)
    mgr = get_manager()
    if s.AUTO_START_EDGES:
        try:
            for r in db.fetch_all("SELECT id FROM cameras WHERE active AND kind <> 'file'"):
                log.info("auto-starting edge for live camera %s: %s", r["id"], mgr.start(r["id"], live=True))
        except Exception as e:
            log.error("could not auto-start edges: %s", e)
    ws.hub.start(asyncio.get_running_loop())
    pusher = asyncio.create_task(ws.status_pusher())
    yield
    pusher.cancel()
    ws.hub.stop()
    mgr.shutdown()
    db.close_pool()


app = FastAPI(title="Nazar API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=get_settings().web_origins, allow_credentials=False,
                   allow_methods=["*"], allow_headers=["*"])
install_error_handlers(app)


class AuthIn(BaseModel):
    passcode: str


@app.post("/api/auth")
def auth(body: AuthIn):
    tok = issue(body.passcode)
    if not tok:
        raise http_error(401, "wrong passcode")
    return {"token": tok}


@app.get("/api/health")
def health():
    s = get_settings()
    ok = db.ping()
    cams = []
    if ok:
        try:
            cams = [{"id": c["id"], "live": c["live"], "edge_running": c["edge_running"]}
                    for c in routes_cameras.camera_rows()]
        except Exception:
            pass
    return {"ok": ok, "db": ok, "openai_key": s.has_openai, "storage": s.STORAGE_MODE, "cameras": cams,
            "models": {"vision": s.OPENAI_VISION_MODEL, "agent": s.OPENAI_AGENT_MODEL, "embed": s.OPENAI_EMBED_MODEL,
                       "transcribe": s.OPENAI_TRANSCRIBE_MODEL, "tts": s.OPENAI_TTS_MODEL}}


@app.get("/media/{key:path}", dependencies=[Depends(require_token)])
def media(key: str):
    try:
        p = storage.local_path(key)
    except ValueError:
        raise http_error(400, "bad key")
    if not p.exists() or not p.is_file():
        raise http_error(404, "not found")
    media_type = {".jpg": "image/jpeg", ".mp4": "video/mp4", ".mp3": "audio/mpeg", ".png": "image/png"}.get(p.suffix.lower())
    return FileResponse(p, media_type=media_type, headers={"Cache-Control": "private, max-age=3600"})


for r in (routes_cameras, routes_live, routes_upload, routes_search, routes_clips, routes_rules, routes_alerts,
          routes_metrics, routes_ask, routes_visual):
    app.include_router(r.router)
app.include_router(ws.router)
