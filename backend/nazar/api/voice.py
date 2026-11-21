"""Voice in: save the recording with the right extension (the transcription API uses it), transcribe."""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import UploadFile

from ..core import db, storage
from ..core.media import duration
from ..core.openai_client import get_ai

EXT_BY_TYPE = {
    "audio/webm": ".webm", "video/webm": ".webm", "audio/ogg": ".ogg", "audio/opus": ".ogg",
    "audio/mp4": ".mp4", "video/mp4": ".mp4", "audio/m4a": ".m4a", "audio/x-m4a": ".m4a", "audio/aac": ".m4a",
    "audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/wave": ".wav",
}
OK_EXT = {".webm", ".ogg", ".mp4", ".m4a", ".mp3", ".wav", ".mpga", ".mpeg", ".flac"}
MAX_BYTES = 10 * 1024 * 1024


def save_audio(upload: UploadFile) -> Path:
    ext = Path(upload.filename or "").suffix.lower()
    if ext not in OK_EXT:
        ctype = (upload.content_type or "").split(";")[0].strip().lower()
        ext = EXT_BY_TYPE.get(ctype, ".webm")
    out = storage.data_dir() / "voice" / f"{uuid.uuid4().hex}{ext}"
    out.parent.mkdir(parents=True, exist_ok=True)
    data = upload.file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("voice note is too large (max 10 MB)")
    if len(data) < 200:
        raise ValueError("voice note is empty")
    out.write_bytes(data)
    return out


def transcription_prompt(camera_id: str | None) -> str:
    rows = db.fetch_all("SELECT name, zones FROM cameras" + (" WHERE id=%s" if camera_id else ""),
                        (camera_id,) if camera_id else None)
    labels = sorted({z.get("label") or z.get("name") for r in rows for z in (r["zones"] or [])})
    names = sorted({r["name"] for r in rows})
    return ("Shop CCTV questions in Hindi, English or Hinglish. Zones: " + ", ".join(labels[:30]) +
            ". Cameras: " + ", ".join(names[:20]) +
            ". Words: camera, counter, gate, desk, parcel, bag, kitne log, kab, raat, subah.")


def transcribe(path: Path, camera_id: str | None, ref: str) -> tuple[str, str, float]:
    try:
        secs = duration(path)
    except Exception:
        secs = 0.0
    return get_ai().transcribe(path, transcription_prompt(camera_id), ref=ref, seconds=secs)
