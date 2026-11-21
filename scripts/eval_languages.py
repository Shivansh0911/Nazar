"""Language round-trip (W6.5): speak a CCTV question with TTS, transcribe it back, compare. We only claim a
language in the README when this passes.   python scripts/eval_languages.py
Writes data/eval/languages.json."""
from __future__ import annotations

import difflib
import json
import sys
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from nazar.core.config import get_settings  # noqa: E402
from nazar.core.openai_client import get_ai  # noqa: E402

PHRASES = {
    "Hindi": ("hi", "कल रात दस बजे के बाद दुकान पर कितने लोग आए?"),
    "Hinglish": ("hi", "Kal raat das baje ke baad dukaan pe kitne log aaye?"),
    "English": ("en", "How many people came to the shop after ten last night?"),
    "Tamil": ("ta", "நேற்று இரவு பத்து மணிக்குப் பிறகு கடைக்கு எத்தனை பேர் வந்தார்கள்?"),
    "Telugu": ("te", "నిన్న రాత్రి పది గంటల తర్వాత షాపుకు ఎంత మంది వచ్చారు?"),
    "Bengali": ("bn", "গতকাল রাত দশটার পরে দোকানে কতজন এসেছিল?"),
    "Marathi": ("mr", "काल रात्री दहा वाजल्यानंतर दुकानात किती लोक आले?"),
    "Gujarati": ("gu", "ગઈકાલે રાત્રે દસ વાગ્યા પછી દુકાને કેટલા લોકો આવ્યા?"),
    "Kannada": ("kn", "ನಿನ್ನೆ ರಾತ್ರಿ ಹತ್ತು ಗಂಟೆಯ ನಂತರ ಅಂಗಡಿಗೆ ಎಷ್ಟು ಜನ ಬಂದರು?"),
}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFC", s.lower())
    return " ".join("".join(ch for ch in s if ch.isalnum() or ch.isspace() or unicodedata.category(ch).startswith("M")).split())


def main() -> int:
    ai = get_ai()
    rows = []
    with tempfile.TemporaryDirectory() as d:
        for name, (code, text) in PHRASES.items():
            mp3 = Path(d) / f"{code}_{name}.mp3"
            ai.tts(text, code, out_path=mp3, ref="eval-lang")
            got, _lang = ai.transcribe(mp3, prompt="", ref="eval-lang")[:2]
            ratio = difflib.SequenceMatcher(None, norm(text), norm(got)).ratio()
            ok = ratio >= 0.75
            rows.append({"language": name, "said": text, "heard": got, "similarity": round(ratio, 2), "pass": ok})
            print(f"{name:<9} {'PASS' if ok else 'FAIL'} {ratio:.2f}  heard: {got}")
    out = get_settings().data_dir / "eval" / "languages.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "rows": rows,
                               "passed": [r["language"] for r in rows if r["pass"]]}, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
