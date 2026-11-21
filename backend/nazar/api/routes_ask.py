"""POST /api/ask - text (JSON) or a voice note (multipart `audio`)."""
from __future__ import annotations

import re
import time
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
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
