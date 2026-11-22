"""Narrated demo film (v3 P4): the silent app recording (scripts/demo_full.mjs) + a real soundtrack.

    python scripts/film_build.py [--telegram demo/telegram_phone.mp4]
Soundtrack: narration (gpt-4o-mini-tts, one narrator voice) for every on-screen chapter caption, the owner's real
Hindi voice note (the WAV fed to Chrome's fake mic), Nazar's real spoken replies (the answer's and the alert's MP3
from the app), mixed with ffmpeg and loudness-normalised (-16 LUFS). Waits are sped up (8x+, never the talking).
Writes demo/nazar_film.mp4 (+ demo/film_timeline.json).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from nazar.core import db, storage  # noqa: E402
from nazar.core.config import get_settings  # noqa: E402
from nazar.core.openai_client import get_ai  # noqa: E402

DEMO = ROOT / "demo"
NARR = DEMO / "narration"
VOICE = "onyx"
INSTR = "Warm, confident Indian-English documentary narrator. Unhurried, clear, friendly."


def probe_dur(p: Path) -> float:
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                                capture_output=True, text=True).stdout.strip() or 0)


def speed_parts(dur: float, fast: list, speed=8.0, max_wait=14.0):
    fast = sorted((max(0.0, s), min(dur, e)) for s, e in fast if e - s > 1.5)
    parts, cur = [], 0.0
    for s, e in fast:
        s = max(s, cur)
        if e <= s:
            continue
        if s > cur:
            parts.append((cur, s, 1.0))
        parts.append((s, e, max(speed, (e - s) / max_wait)))
        cur = e
    if cur < dur:
        parts.append((cur, dur, 1.0))
    return parts


def mapper(parts):
    def f(t: float) -> float:
        out = 0.0
        for s, e, sp in parts:
            if t <= s:
                return out
            out += (min(t, e) - s) / sp
            if t <= e:
                return out
        return out
    return f


def speakable(text: str) -> str:
    return (text.replace("₹0", "zero rupees").replace("₹", "rupees ").replace("×", " times").replace("→", ", then")
            .replace("~", "about ").replace("N−1", "N minus one"))


def tts(text: str, path: Path) -> None:
    if path.exists():
        return
    s = get_settings()
    r = get_ai().client.audio.speech.create(model=s.OPENAI_TTS_MODEL, voice=VOICE, input=text, instructions=INSTR,
                                            response_format="mp3")
    path.write_bytes(r.content)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(DEMO / "nazar_full.webm"))
    ap.add_argument("--fast", default=str(DEMO / "nazar_full_fast.json"))
    ap.add_argument("--log", default=str(get_settings().data_dir / "logs" / "demo_full.log"))
    ap.add_argument("--wav", default=str(DEMO / "q_hi.wav"))
    ap.add_argument("--out", default=str(DEMO / "nazar_film.mp4"))
    ap.add_argument("--telegram", help="optional phone screen recording, appended after the live alert chapter")
    a = ap.parse_args()
    NARR.mkdir(parents=True, exist_ok=True)
    src = Path(a.src)
    dur = probe_dur(src)
    parts = speed_parts(dur, json.loads(Path(a.fast).read_text()))
    m = mapper(parts)
    caps = []
    for line in Path(a.log).read_text(encoding="utf-8", errors="ignore").splitlines():
        mm = re.match(r"\[\s*(\d+)s\] (.+?) \| (.+)$", line)
        if mm:
            caps.append((float(mm.group(1)), mm.group(2).strip(), mm.group(3).strip()))
    # 1) silent picture with the same speed-ups as make_demo_mp4
    filt, labels = [], []
    for i, (s, e, sp) in enumerate(parts):
        filt.append(f"[0:v]trim=start={s:.3f}:end={e:.3f},setpts=(PTS-STARTPTS)/{sp:g}[v{i}]")
        labels.append(f"[v{i}]")
    filt.append("".join(labels) + f"concat=n={len(parts)}:v=1:a=0,fps=30,format=yuv420p[vout]")
    picture = DEMO / "film_picture.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-filter_complex", ";".join(filt), "-map", "[vout]",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "20", str(picture)], check=True)
    vdur = probe_dur(picture)
    # 2) sound events on the output timeline
    events = []  # (start_s, path, kind, gain)
    voice_t = reply_t = alert_t = None
    for t, chap, text in caps:
        if "VOICE" in chap:
            voice_t = m(t) + 0.6
        if "LIVE ALERT" in chap:
            alert_t = m(t) + 1.0
    hindi = db.fetch_one("SELECT answer->>'audio_key' AS k FROM queries WHERE input_kind='voice' AND answer ? 'audio_key' "
                         "ORDER BY id DESC LIMIT 1")
    alert = db.fetch_one("SELECT audio_key FROM alerts WHERE audio_key IS NOT NULL ORDER BY id DESC LIMIT 1")
    busy: list[tuple[float, float]] = []
    if voice_t is not None:
        wav = Path(a.wav)
        events.append((voice_t, wav, "owner voice note (Hindi)", 1.0))
        busy.append((voice_t, voice_t + probe_dur(wav)))
        if hindi and hindi["k"] and storage.local_path(hindi["k"]).exists():
            reply_t = voice_t + probe_dur(wav) + 7.0
            rp = storage.local_path(hindi["k"])
            events.append((reply_t, rp, "Nazar's spoken reply (Hindi)", 1.0))
            busy.append((reply_t, reply_t + probe_dur(rp)))
    if alert_t is not None and alert and storage.local_path(alert["audio_key"]).exists():
        ap_ = storage.local_path(alert["audio_key"])
        events.append((alert_t, ap_, "alert voice note (Hinglish)", 1.0))
        busy.append((alert_t, alert_t + probe_dur(ap_)))
    # narration: one line per caption, never over the voice notes/replies, never over itself
    cursor = 0.0
    for i, (t, chap, text) in enumerate(caps):
        spoken = speakable(text)
        p = NARR / f"n_{hashlib.sha1(spoken.encode()).hexdigest()[:12]}.mp3"
        tts(spoken, p)
        d = probe_dur(p)
        st = max(m(t) + 0.3, cursor)
        moved = True
        while moved:
            moved = False
            for b0, b1 in busy:
                if st < b1 and st + d > b0:
                    st, moved = b1 + 0.3, True
        events.append((st, p, f"narration: {chap}", 1.0))
        cursor = st + d + 0.25
    end = max(vdur, max(s + probe_dur(p) for s, p, _, _ in events) + 1.0)
    # 3) mix
    inputs, fl, mixl = [], [], []
    for k, (st, p, _, g) in enumerate(events):
        inputs += ["-i", str(p)]
        fl.append(f"[{k}:a]aresample=48000,aformat=channel_layouts=stereo,volume={g},adelay={int(st * 1000)}|{int(st * 1000)}[a{k}]")
        mixl.append(f"[a{k}]")
    fl.append("".join(mixl) + f"amix=inputs={len(events)}:normalize=0:duration=longest,apad=whole_dur={end:.2f},"
              "loudnorm=I=-16:TP=-1.5:LRA=11[aout]")
    mix = DEMO / "film_audio.m4a"
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(fl), "-map", "[aout]",
                    "-c:a", "aac", "-b:a", "160k", "-t", f"{end:.2f}", str(mix)], check=True)
    # 4) mux (hold the last frame if the talking runs longer than the picture)
    pad = max(0.0, end - vdur)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(picture), "-i", str(mix), "-filter_complex",
                    f"[0:v]tpad=stop_mode=clone:stop_duration={pad:.2f}[v]", "-map", "[v]", "-map", "1:a",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "copy", "-movflags", "+faststart",
                    "-shortest", a.out], check=True)
    tl = [{"t": round(s, 2), "what": w, "file": p.name} for s, p, w, _ in sorted(events, key=lambda x: x[0])]
    (DEMO / "film_timeline.json").write_text(json.dumps(tl, indent=1), encoding="utf-8")
    print(f"{a.out}: {probe_dur(Path(a.out)):.0f} s, {len(events)} audio events "
          f"(voice note {'yes' if voice_t else 'no'}, Hindi reply {'yes' if reply_t else 'no'}, alert voice {'yes' if alert_t else 'no'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
