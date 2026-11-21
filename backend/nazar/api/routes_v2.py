"""v2 routes: security events, morning digest, incident reports, settings, Telegram pairing, custom objects."""
from __future__ import annotations

import random
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from ..core import db, storage
from ..core.config import get_settings
from ..core.timeutil import to_local
from .auth import require_token
from .deps import http_error, window

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])


@router.get("/sec-events")
def sec_events(from_: str | None = None, to: str | None = None, camera_id: str | None = None, limit: int = 100,
               token: str = Depends(require_token)):
    t0, t1 = window(from_, to, 24 * 7)
    rows = db.fetch_all("SELECT s.*, c.name AS camera_name FROM sec_events s JOIN cameras c ON c.id=s.camera_id WHERE "
                        "s.t_start BETWEEN %s AND %s" + (" AND s.camera_id=%s" if camera_id else "") +
                        " ORDER BY s.t_start DESC LIMIT %s", (t0, t1, camera_id, limit) if camera_id else (t0, t1, limit))
    ids = [r["track_ids"][0] for r in rows if r["track_ids"]]
    crops = {r["id"]: (r["crop_keys"] or [None])[0] for r in db.fetch_all("SELECT id, crop_keys FROM tracks WHERE id = ANY(%s)", (ids,))}
    return [{"id": r["id"], "camera_id": r["camera_id"], "camera_name": r["camera_name"], "type": r["type"],
             "t": to_local(r["t_start"]).isoformat(), "t_end": to_local(r["t_end"]).isoformat(),
             "track_ids": list(r["track_ids"] or []), "level": r["level"], "reason": r["reason"], "verified_by": r["verified_by"],
             "thumb_url": storage.url(crops.get(r["track_ids"][0]) if r["track_ids"] else None, token)} for r in rows]


_digest_cache: dict[str, tuple[float, dict]] = {}


@router.get("/digest")
def digest(lang: str = "hinglish", voice: bool = True, token: str = Depends(require_token)):
    """Overnight summary as text (+ a voice note, synthesized once per hour)."""
    from ..worker.security import digest as make

    hit = _digest_cache.get(lang)
    if hit and time.time() - hit[0] < 300:
        d = dict(hit[1])
    else:
        d = make(language=lang)
        _digest_cache[lang] = (time.time(), d)
    d["audio_url"] = None
    if voice and get_settings().has_openai:
        key = f"tts/digest_{lang}_{datetime.now(timezone.utc):%Y%m%d%H}.mp3"
        p = storage.local_path(key)
        if not p.exists():
            try:
                from ..core.openai_client import get_ai

                get_ai().tts(d["text"], "hi" if lang in ("hi", "hinglish") else "en", out_path=p, ref="digest")
            except Exception:
                key = None
        d["audio_url"] = storage.url(key, token) if key else None
    return d


class ReportIn(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    alert_id: int | None = None
    sec_event_id: int | None = None
    track_ids: list[int] | None = None
    language: str = "en"


@router.post("/reports")
def create_report(body: ReportIn, token: str = Depends(require_token)):
    from .reports import create_report as make

    try:
        return make(title=body.title, alert_id=body.alert_id, sec_event_id=body.sec_event_id, track_ids=body.track_ids,
                    language=body.language, token=token)
    except ValueError as e:
        raise http_error(400, str(e))


@router.get("/reports")
def list_reports(token: str = Depends(require_token)):
    return [{"id": r["id"], "at": to_local(r["at"]).isoformat(), "title": r["title"], "language": r["language"],
             "pdf_url": storage.url(r["pdf_key"], token), "manifest_sha256": r["manifest_sha256"]}
            for r in db.fetch_all("SELECT * FROM reports WHERE pdf_key IS NOT NULL ORDER BY at DESC LIMIT 100")]


@router.get("/settings")
def settings_view():
    s = get_settings()
    chats = db.fetch_all("SELECT chat_id, name, paired_at FROM telegram_chats ORDER BY paired_at")
    return {"enrich_mode": s.ENRICH_MODE, "retention_days": s.RETENTION_DAYS, "telegram": {
        "configured": bool(s.TELEGRAM_BOT_TOKEN), "bot": s.TELEGRAM_BOT_USERNAME or None,
        "paired": [{"chat_id": c["chat_id"], "name": c["name"], "paired_at": to_local(c["paired_at"]).isoformat()} for c in chats]},
        "openai": s.has_openai, "storage": s.STORAGE_MODE, "max_edges": s.MAX_EDGES, "digest_time": s.DIGEST_TIME,
        "models": {"agent_fast": s.OPENAI_AGENT_FAST_MODEL, "agent": s.OPENAI_AGENT_MODEL, "vision": s.OPENAI_VISION_MODEL,
                   "transcribe": s.OPENAI_TRANSCRIBE_MODEL, "tts": s.OPENAI_TTS_MODEL}}


@router.post("/telegram/pair-code")
def pair_code():
    """A 6-digit code valid for 10 minutes; send /pair <code> to the bot to receive alerts and ask questions there."""
    s = get_settings()
    code = f"{random.SystemRandom().randint(0, 999999):06d}"
    db.execute("INSERT INTO kv(k, v) VALUES ('tg_pair', %s) ON CONFLICT (k) DO UPDATE SET v=EXCLUDED.v, updated_at=now()",
               (Jsonb({"code": code, "exp": time.time() + 600}),))
    bot = s.TELEGRAM_BOT_USERNAME or None
    chats = db.fetch_all("SELECT chat_id, name FROM telegram_chats ORDER BY paired_at")
    return {"code": code, "bot": bot, "link": f"https://t.me/{bot}" if bot else None, "expires_s": 600,
            "configured": bool(s.TELEGRAM_BOT_TOKEN), "paired": chats}


class CustomIn(BaseModel):
    camera_id: str
    name: str = Field(min_length=2, max_length=40)
    alert: bool = False


@router.get("/custom-objects")
def list_custom(camera_id: str | None = None):
    return db.fetch_all("SELECT id, camera_id, name, prompt_type, threshold, active, created_at FROM custom_objects"
                        + (" WHERE camera_id=%s" if camera_id else "") + " ORDER BY created_at DESC",
                        (camera_id,) if camera_id else None)


@router.post("/custom-objects")
def add_custom(body: CustomIn, token: str = Depends(require_token)):
    from .teach import teach_from_text

    r = teach_from_text(body.camera_id, body.name, alert=body.alert, ref="teach-ui")
    if not r.get("ok"):
        raise http_error(400, r.get("error") or "could not teach that object")
    return r


@router.delete("/custom-objects/{obj_id}")
def del_custom(obj_id: int):
    db.execute("UPDATE custom_objects SET active=false WHERE id=%s", (obj_id,))
    return {"ok": True}
