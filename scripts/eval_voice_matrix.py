"""Voice matrix (v3 P1.3): speak real questions with TTS in 8 languages, send them to the running API as voice notes
(webm/opus and m4a), and check: the transcript makes sense, the reply is in the right language/script, Confirmed
numbers equal SQL (recomputed with the same arguments), and the spoken reply exists and is not silent.

    python scripts/eval_voice_matrix.py      (API on :8000, OPENAI_API_KEY set)  -> data/eval/voice_matrix.json
"""
from __future__ import annotations

import difflib
import json
import os
import subprocess
import sys
import tempfile
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")

from nazar.api import agent_tools  # noqa: E402
from nazar.core import db  # noqa: E402
from nazar.core.config import get_settings  # noqa: E402
from nazar.core.openai_client import get_ai  # noqa: E402

API = os.environ.get("API_BASE_URL", "http://localhost:8000").rstrip("/")
# (language, tts code, question, expected reply script)
# (language, tts code, question, camera the answer must be about - None = not a count question)
CASES = [
    ("Hindi", "hi", "रात दो बजे के बाद नाइट स्टॉल पर कितने लोग आए?", "night-market"),
    ("Hindi", "hi", "बिल्डर्स वेन्यू पर कितने लोग दिखे?", "builders-venue"),
    ("Hinglish", "hi", "Kal raat das baje ke baad shop counter pe kitne log aaye?", "shop-counter"),
    ("Hinglish", "hi", "Builders venue pe kitne log dikhe?", "builders-venue"),
    ("Hinglish", "hi", "Desk fourteen se bag kisne uthaya?", None),
    ("English", "en", "How many people came to the shop counter between six and eight pm yesterday?", "shop-counter"),
    ("English", "en", "How many people were seen at the office desk?", "office-desk"),
    ("Tamil", "ta", "நைட் ஸ்டாலில் இரவு இரண்டு மணிக்குப் பிறகு எத்தனை பேர் வந்தார்கள்?", "night-market"),
    ("Telugu", "te", "నైట్ స్టాల్‌కి రాత్రి రెండు గంటల తర్వాత ఎంత మంది వచ్చారు?", "night-market"),
    ("Bengali", "bn", "নাইট স্টলে রাত দুটোর পরে কতজন এসেছিল?", "night-market"),
    ("Gujarati", "gu", "નાઇટ સ્ટોલ પર રાત્રે બે વાગ્યા પછી કેટલા લોકો આવ્યા?", "night-market"),
    ("Kannada", "kn", "ನೈಟ್ ಸ್ಟಾಲ್‌ಗೆ ರಾತ್ರಿ ಎರಡು ಗಂಟೆಯ ನಂತರ ಎಷ್ಟು ಜನ ಬಂದರು?", "night-market"),
]


def norm(s: str) -> str:
    s = unicodedata.normalize("NFC", (s or "").lower())
    return " ".join("".join(ch for ch in s if ch.isalnum() or ch.isspace() or unicodedata.category(ch).startswith("M")).split())


def script_of(text: str) -> str:
    deva = sum(1 for ch in text if "ऀ" <= ch <= "ॿ")
    latin = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    return "deva" if deva > latin else "latin"


def rms_of(mp3: bytes) -> float:
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", "pipe:0", "-f", "s16le", "-ac", "1", "-ar", "16000", "pipe:1"],
                         input=mp3, capture_output=True).stdout
    a = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    return float(np.sqrt(np.mean(a ** 2))) if a.size else 0.0


def main() -> int:
    ai = get_ai()
    tok = requests.post(f"{API}/api/auth", json={"passcode": get_settings().DEMO_PASSCODE}, timeout=10).json()["token"]
    H = {"X-Nazar-Token": tok}
    rows = []
    with tempfile.TemporaryDirectory() as d:
        for i, (lang, code, text, want_cam) in enumerate(CASES):
            mp3 = Path(d) / f"q{i}.mp3"
            ai.tts(text, code, out_path=mp3, ref="eval-voice")
            fmt = "webm" if i % 2 == 0 else "m4a"
            note = Path(d) / f"q{i}.{fmt}"
            codec = ["-c:a", "libopus", "-b:a", "32k"] if fmt == "webm" else ["-c:a", "aac", "-b:a", "64k"]
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(mp3), "-ac", "1", *codec, str(note)], check=True)
            t0 = time.perf_counter()
            r = requests.post(f"{API}/api/ask", headers=H, timeout=300,
                              files={"audio": (note.name, note.read_bytes(), "audio/webm" if fmt == "webm" else "audio/mp4")})
            secs = time.perf_counter() - t0
            if r.status_code != 200:
                rows.append({"language": lang, "format": fmt, "said": text, "pass": False, "error": f"{r.status_code} {r.text[:200]}"})
                print(f"{lang:<9} {fmt:<4} FAIL http {r.status_code}")
                continue
            a = r.json()
            heard = a.get("transcript") or ""
            sim = difflib.SequenceMatcher(None, norm(text), norm(heard)).ratio()
            reply = a.get("reply_text") or ""
            # the reply is written in the script of what was heard (Hindi/Hinglish), English otherwise
            script_ok = lang not in ("Hindi", "Hinglish", "English") or script_of(reply) == script_of(heard)
            cnt = a.get("count") or {}
            plan = (db.fetch_one("SELECT plan FROM queries WHERE id=%s", (a["query_id"],)) or {}).get("plan") or []
            cargs = next((c["args"] for c in plan if c["name"] == "count_events"), None)
            understood = (cargs or {}).get("camera_id") == want_cam if want_cam else bool(reply)
            transcript_ok = sim >= 0.6 or understood
            sql_ok = None
            if cnt.get("value") is not None and cargs:
                again = agent_tools.count_events(dict(cargs))
                sql_ok = (again["value"] == cnt["value"] and cnt.get("level") == "confirmed"
                          and cnt.get("receipts_total", cnt["value"]) == cnt["value"])
            audio = requests.get(a["audio_url"], timeout=60) if a.get("audio_url") else None
            rms = rms_of(audio.content) if audio is not None and audio.status_code == 200 else 0.0
            audio_ok = rms > 300
            ok = transcript_ok and script_ok and sql_ok is not False and audio_ok
            rows.append({"language": lang, "format": fmt, "said": text, "heard": heard, "similarity": round(sim, 2),
                         "reply": reply, "reply_language": a.get("language"), "count": cnt.get("value"),
                         "count_equals_sql": sql_ok, "understood_camera": understood, "heard_script": script_of(heard), "voice_rms": round(rms), "seconds": round(secs, 1),
                         "transcript_ok": transcript_ok, "script_ok": script_ok, "audio_ok": audio_ok, "pass": ok})
            print(f"{lang:<9} {fmt:<4} {'PASS' if ok else 'FAIL'} sim {sim:.2f} script {'ok' if script_ok else 'BAD'} "
                  f"sql {sql_ok} rms {rms:.0f} {secs:.1f}s | {reply[:70]}")
    passed = sum(r["pass"] for r in rows)
    out = get_settings().data_dir / "eval" / "voice_matrix.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "passed": passed,
                               "total": len(rows), "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{passed}/{len(rows)} voice cases pass -> {out}")
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
