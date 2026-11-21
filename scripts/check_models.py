"""One tiny real call per configured OpenAI model; prints OK/FAIL.  python scripts/check_models.py"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from nazar.core.config import get_settings  # noqa: E402
from nazar.core.openai_client import NazarAI  # noqa: E402


class Ping(BaseModel):
    ok: bool
    word: str


def main() -> int:
    s = get_settings()
    if not s.has_openai:
        print("OPENAI_API_KEY is empty in .env - paste it and run again.")
        return 1
    ai = NazarAI()
    results = []

    def check(name: str, model: str, fn):
        try:
            detail = fn()
            results.append(True)
            print(f"OK    {name:<10} {model:<26} {detail}")
        except Exception as e:
            results.append(False)
            print(f"FAIL  {name:<10} {model:<26} {type(e).__name__}: {str(e)[:160]}")
            if name == "vision" and ai._is_model_missing(e):
                print(f"      -> set OPENAI_VISION_MODEL={s.OPENAI_VISION_FALLBACK} in .env (fallback)")

    img = np.zeros((64, 64, 3), np.uint8)
    img[:, :32] = (0, 0, 255)
    jpg = cv2.imencode(".jpg", img)[1].tobytes()

    def vision():
        ai._vision_model_override = s.OPENAI_VISION_MODEL  # no silent fallback here
        cap, cost = ai.parse(s.OPENAI_VISION_MODEL, [{"role": "user", "content": [
            {"type": "input_text", "text": "Detector class: person. 1 crop."},
            {"type": "input_image", "image_url": "data:image/jpeg;base64," + __import__("base64").b64encode(jpg).decode(),
             "detail": "low"}]}], __import__("nazar.core.schemas", fromlist=["TrackCaption"]).TrackCaption,
            kind="check", ref="check_models")
        return f"caption='{cap.caption[:40]}' ${cost:.6f}"

    def agent():
        p, cost = ai.parse(s.OPENAI_AGENT_MODEL, "Reply ok=true and word='namaste'.", Ping, kind="check", ref="check_models")
        return f"{p.model_dump()} ${cost:.6f}"

    def embed():
        v = ai.embed(["a person in a red shirt carrying a bag"], kind="check", ref="check_models")
        return f"dims={len(v[0])}"

    tts_path = Path(tempfile.gettempdir()) / "nazar_check_tts.mp3"

    def tts():
        p = ai.tts("namaste", "hi", out_path=tts_path, ref="check_models")
        return f"{p.stat().st_size} bytes"

    def transcribe():
        src = tts_path if tts_path.exists() else None
        if src is None:
            raise RuntimeError("TTS failed, nothing to transcribe")
        text, lang, secs = ai.transcribe(src, "Hindi or English greeting", ref="check_models")
        return f"'{text}' lang={lang} {secs:.1f}s"

    check("vision", s.OPENAI_VISION_MODEL, vision)
    check("agent", s.OPENAI_AGENT_MODEL, agent)
    check("embed", s.OPENAI_EMBED_MODEL, embed)
    check("tts", s.OPENAI_TTS_MODEL, tts)
    check("transcribe", s.OPENAI_TRANSCRIBE_MODEL, transcribe)
    print(f"\n{sum(results)}/{len(results)} models OK")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
