"""POST /api/ask - text (JSON) or a voice note (multipart `audio`)."""
from __future__ import annotations

import re
import time
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from ..core import storage
from ..core.openai_client import get_ai
from ..core.schemas import AskResponse
from . import voice
from .agent import ask
from .auth import require_token
from .deps import http_error

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])


class AskIn(BaseModel):
    text: str
    camera_id: str | None = None


@router.post("/ask", response_model=AskResponse)
async def ask_route(request: Request, token: str = Depends(require_token)):
    t0 = time.perf_counter()
    ref = f"q:{uuid.uuid4().hex[:12]}"
    ctype = request.headers.get("content-type", "")
    get_ai().client  # raises AIUnavailable -> 503 before doing any work
    from starlette.concurrency import run_in_threadpool

    if ctype.startswith("multipart/"):
        form = await request.form()
        audio = form.get("audio")
        camera_id = (form.get("camera_id") or None) or None
        if audio is None or not hasattr(audio, "file"):
            raise http_error(400, "multipart request needs an 'audio' file")
        try:
            path = await run_in_threadpool(voice.save_audio, audio)
        except ValueError as e:
            raise http_error(400, str(e))
        text, _lang, _secs = await run_in_threadpool(voice.transcribe, path, camera_id, ref)
        if not text.strip():
            raise http_error(422, "could not hear a question in that voice note")
        return await run_in_threadpool(lambda: ask(text, camera_id, token=token, transcript=text, input_kind="voice",
                                                   t_start=t0, ref=ref))
    try:
        body = AskIn.model_validate(await request.json())
    except Exception:
        raise http_error(400, "send JSON {text, camera_id?} or multipart audio")
    if not body.text.strip():
        raise http_error(400, "empty question")
    return await run_in_threadpool(lambda: ask(body.text.strip(), body.camera_id, token=token, input_kind="text",
                                               t_start=t0, ref=ref))


@router.get("/ask/audio/{name}")
def ask_audio(name: str):
    """The voice reply of an answer. It is synthesized after the text answer is returned, so wait for it (<= 30 s)."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}\.mp3", name):
        raise http_error(400, "bad name")
    p = storage.local_path(f"tts/{name}")
    failed = storage.local_path(f"tts/{name}.failed")
    deadline = time.time() + 30
    while not p.exists():
        if failed.exists() or time.time() > deadline:
            raise http_error(404, "voice reply not available")
        time.sleep(0.15)
    return FileResponse(p, media_type="audio/mpeg", headers={"Cache-Control": "private, max-age=3600"})


def _sse(kind: str, data) -> bytes:
    import json

    return f"event: {kind}\ndata: {json.dumps(data, default=str, ensure_ascii=False)}\n\n".encode("utf-8")


@router.post("/ask/stream")
async def ask_stream(request: Request, token: str = Depends(require_token)):
    """Server-sent events: status ("Counting..."), text (reply deltas as they are generated), reset (escalated to the
    bigger model), transcript (voice notes), result (the full AskResponse), error."""
    import asyncio
    import threading

    t0 = time.perf_counter()
    ref = f"q:{uuid.uuid4().hex[:12]}"
    ctype = request.headers.get("content-type", "")
    get_ai().client
    audio_path = None
    camera_id = None
    text = None
    if ctype.startswith("multipart/"):
        form = await request.form()
        audio = form.get("audio")
        camera_id = (form.get("camera_id") or None) or None
        if audio is None or not hasattr(audio, "file"):
            raise http_error(400, "multipart request needs an 'audio' file")
        from starlette.concurrency import run_in_threadpool

        try:
            audio_path = await run_in_threadpool(voice.save_audio, audio)
        except ValueError as e:
            raise http_error(400, str(e))
    else:
        try:
            body = AskIn.model_validate(await request.json())
        except Exception:
            raise http_error(400, "send JSON {text, camera_id?} or multipart audio")
        text, camera_id = body.text.strip(), body.camera_id
        if not text:
            raise http_error(400, "empty question")
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()

    def push(kind, data):
        loop.call_soon_threadsafe(q.put_nowait, (kind, data))

    def work():
        nonlocal text
        try:
            transcript = None
            if audio_path is not None:
                push("status", "Listening to the voice note…")
                t, _lang, _secs = voice.transcribe(audio_path, camera_id, ref)
                if not t.strip():
                    push("error", "could not hear a question in that voice note")
                    return
                text = transcript = t
                push("transcript", t)
            res = ask(text, camera_id, token=token, transcript=transcript,
                      input_kind="voice" if audio_path else "text", t_start=t0, ref=ref, on_event=push)
            push("result", AskResponse.model_validate(res).model_dump(mode="json"))
        except Exception as e:
            push("error", str(e)[:300])
        finally:
            push("end", None)

    threading.Thread(target=work, daemon=True).start()

    async def gen():
        yield _sse("status", "Thinking…")
        while True:
            kind, data = await q.get()
            if kind == "end":
                break
            yield _sse(kind, data)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/receipts/{query_id}")
def receipts(query_id: int, page: int = 0, size: int = 48, hour: str | None = None,
             token: str = Depends(require_token)):
    """Receipts of a count answer (every counted track), paginated; `hour` = ISO bucket start to filter."""
    from datetime import datetime, timedelta

    from ..core import db

    row = db.fetch_one("SELECT answer FROM queries WHERE id=%s", (query_id,))
    cnt = (row or {}).get("answer", {}).get("count") if row else None
    if not cnt:
        raise http_error(404, "no count in that answer")
    ids = cnt.get("receipt_ids") or []
    times = cnt.get("receipt_times") or []
    pairs = list(zip(ids, times))
    if hour:
        h0 = datetime.fromisoformat(hour)
        step = {"10s": 10, "1min": 60, "5min": 300, "15min": 900, "hour": 3600, "day": 86400}.get(cnt.get("bucket", "hour"), 3600)
        h1 = h0 + timedelta(seconds=step)
        pairs = [(i, t) for i, t in pairs if h0 <= datetime.fromisoformat(t) < h1]
    size = max(1, min(size, 96))
    chunk = pairs[page * size:(page + 1) * size]
    rows = db.fetch_all("SELECT id, camera_id, crop_keys, zone_path FROM tracks WHERE id = ANY(%s)",
                        ([i for i, _ in chunk],))
    by = {r["id"]: r for r in rows}
    fb = {int(r["ref"]): r["correct"] for r in db.fetch_all(
        "SELECT ref, correct FROM feedback WHERE kind='receipt' AND ref = ANY(%s)", ([str(i) for i, _ in chunk],))}
    items = [{"track_id": i, "t": t, "camera_id": by.get(i, {}).get("camera_id"), "level": "confirmed",
              "zones": list(by.get(i, {}).get("zone_path") or []),
              "thumb_url": storage.url((by.get(i, {}).get("crop_keys") or [None])[0], token),
              "marked_wrong": fb.get(i) is False} for i, t in chunk]
    wrong = db.fetch_val("SELECT count(*) FROM feedback WHERE kind='receipt' AND correct=false AND ref = ANY(%s)",
                         ([str(i) for i in ids],))
    return {"query_id": query_id, "total": len(pairs), "page": page, "size": size, "items": items,
            "value": cnt.get("value"), "marked_wrong": int(wrong or 0),
            "after_review": int(cnt.get("value") or 0) - int(wrong or 0)}


class FeedbackIn(BaseModel):
    kind: str
    ref: str
    correct: bool
    note: str | None = None


@router.post("/feedback")
def feedback(body: FeedbackIn):
    """A human marks a receipt / hit right or wrong; stored for evaluation (never changes the SQL count itself)."""
    from ..core import db

    if body.kind not in ("receipt", "hit", "alert", "sec_event"):
        raise http_error(400, "unknown feedback kind")
    db.execute("INSERT INTO feedback(kind, ref, correct, note) VALUES (%s,%s,%s,%s) ON CONFLICT (kind, ref) DO UPDATE "
               "SET correct=EXCLUDED.correct, note=EXCLUDED.note, at=now()",
               (body.kind, body.ref[:100], body.correct, (body.note or "")[:300] or None))
    return {"ok": True}
