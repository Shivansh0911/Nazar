"""Alert builder: (optional) vision confirm -> message in the owner's language -> snapshot -> notify -> TTS."""
from __future__ import annotations

import logging
import time
from pathlib import Path

import cv2
import numpy as np
from psycopg.types.json import Jsonb

from ..core import db, storage
from ..core.openai_client import AIKeyProblem, AIUnavailable, get_ai
from ..core.rules import Hit, RuleSpec
from ..core.timeutil import fmt_local

log = logging.getLogger("nazar.alerts")

CLS_HI = {"person": "कोई", "any_bag": "बैग", "backpack": "बैग", "handbag": "बैग", "suitcase": "बैग", "car": "गाड़ी",
          "motorcycle": "बाइक", "bicycle": "साइकिल", "laptop": "लैपटॉप", "cell phone": "फ़ोन", "bottle": "बोतल"}
CLS_EN = {"person": "Someone", "any_bag": "A bag", "backpack": "A bag", "handbag": "A bag", "suitcase": "A bag",
          "car": "A car", "motorcycle": "A motorcycle", "bicycle": "A bicycle", "laptop": "A laptop",
          "cell phone": "A phone", "bottle": "A bottle", "bus": "A bus", "truck": "A truck"}


def _zone_label(camera_id: str, zone: str) -> str:
    if zone == "anywhere":
        return "camera"
    row = db.fetch_one("SELECT zones FROM cameras WHERE id=%s", (camera_id,))
    for z in (row or {}).get("zones") or []:
        if z.get("name") == zone:
            return z.get("label") or zone
    return zone.replace("_", " ")


def message_for(spec: RuleSpec, hit: Hit, language: str, zone_label: str) -> str:
    when = fmt_local(hit.t, "hi" if language == "hi" else ("hinglish" if language == "hinglish" else "en"))
    trig = spec.trigger
    if language == "hi":
        who = CLS_HI.get(spec.cls, spec.cls)
        if trig == "object_removed":
            return f"{zone_label} से {who} उठाया गया — {when}"
        if trig == "zone_enter":
            return f"{zone_label} पर {who} आया — {when}"
        if trig == "zone_exit":
            return f"{zone_label} से {who} निकला — {when}"
        if trig == "dwell_over":
            return f"{zone_label} पर {who} {spec.dwell_s} सेकंड से ज़्यादा रुका — {when}"
        return f"{zone_label} पर {hit.extra.get('n', (spec.count or 0) + 1)} लोग — {when}"
    if language == "hinglish":
        if trig == "object_removed":
            return f"{zone_label} se bag uthaya gaya — {when}"
        if trig == "zone_enter":
            return f"{zone_label} pe koi aaya — {when}"
        if trig == "zone_exit":
            return f"{zone_label} se koi nikla — {when}"
        if trig == "dwell_over":
            return f"{zone_label} pe koi {spec.dwell_s} second se zyada ruka — {when}"
        return f"{zone_label} pe {hit.extra.get('n', (spec.count or 0) + 1)} log hain — {when}"
    who = CLS_EN.get(spec.cls, spec.cls)
    if trig == "object_removed":
        return f"{who} was taken from {zone_label} at {when}"
    if trig == "zone_enter":
        return f"{who} entered {zone_label} at {when}"
    if trig == "zone_exit":
        return f"{who} left {zone_label} at {when}"
    if trig == "dwell_over":
        return f"{who} stayed at {zone_label} for over {spec.dwell_s} s at {when}"
    return f"{hit.extra.get('n', (spec.count or 0) + 1)} people at {zone_label} at {when}"


def _live_frame(camera_id: str, max_age_s: float = 15.0) -> np.ndarray | None:
    p = storage.local_path(f"live/{camera_id}.jpg")
    try:
        if p.exists() and time.time() - p.stat().st_mtime <= max_age_s:
            return cv2.imread(str(p))
    except Exception:
        return None
    return None


def _evidence_image(camera_id: str, track_id: int, box: list | None, live: bool) -> tuple[np.ndarray | None, np.ndarray | None]:
    """Returns (full_snapshot_for_alert, crop_for_vision_check). Everything is already face-blurred."""
    frame = _live_frame(camera_id) if live else None
    crop = None
    if frame is not None and box:
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = box
        pw, ph = (x2 - x1) * 0.15, (y2 - y1) * 0.15
        X1, Y1, X2, Y2 = max(0, int((x1 - pw) * w)), max(0, int((y1 - ph) * h)), min(w, int((x2 + pw) * w)), min(h, int((y2 + ph) * h))
        if X2 > X1 and Y2 > Y1:
            crop = frame[Y1:Y2, X1:X2].copy()
            snap = frame.copy()
            cv2.rectangle(snap, (int(x1 * w), int(y1 * h)), (int(x2 * w), int(y2 * h)), (40, 40, 230), 2)
            return snap, crop
    row = db.fetch_one("SELECT crop_keys FROM tracks WHERE id=%s", (track_id,))
    keys = (row or {}).get("crop_keys") or []
    for k in keys:
        p = storage.local_path(k)
        if p.exists():
            crop = cv2.imread(str(p))
            break
    return (frame if frame is not None else crop), crop


def build(rule: dict, hit: Hit) -> int | None:
    """Create the alert once per (rule, track). Returns the new alert id, or None if it already existed."""
    spec: RuleSpec = rule.get("rs") or RuleSpec.model_validate(rule["spec"])
    language = rule.get("language") or "en"
    zone_label = _zone_label(spec.camera_id, spec.zone)
    msg = message_for(spec, hit, language, zone_label)
    meta = {"zone": spec.zone, "trigger": spec.trigger, **({"actor_track_id": hit.actor_track_id} if hit.actor_track_id else {}),
            **({"object_track_id": hit.object_track_id} if hit.object_track_id else {}), **hit.extra}
    row = db.fetch_one(
        "INSERT INTO alerts(rule_id, track_id, camera_id, t, message, meta) VALUES (%s,%s,%s,%s,%s,%s) "
        "ON CONFLICT (rule_id, track_id) DO NOTHING RETURNING id",
        (rule["id"], hit.track_id, spec.camera_id, hit.t, msg, Jsonb(meta)))
    if not row:
        return None
    alert_id = row["id"]
    tr = db.fetch_one("SELECT active, t_end FROM tracks WHERE id=%s", (hit.track_id,)) or {}
    live = bool(tr.get("active")) or (time.time() - hit.t.timestamp() < 20)
    snap, crop = _evidence_image(spec.camera_id, hit.object_track_id or hit.track_id, hit.box, live)
    if snap is not None:
        ok, buf = cv2.imencode(".jpg", snap, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ok:
            key = storage.put_bytes(buf.tobytes(), f"snap/{alert_id}.jpg")
            db.execute("UPDATE alerts SET snapshot_key=%s WHERE id=%s", (key, alert_id))

    confirmed = None
    ai = get_ai()
    if spec.confirm_with_vision and ai.available() and crop is not None:
        try:
            ok, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 85])
            res, _ = ai.vision_check(buf.tobytes(), spec.confirm_with_vision, camera_id=spec.camera_id,
                                     ref=f"alert:{alert_id}")
            confirmed = bool(res.yes)
            meta["vision_reason"] = res.reason
        except (AIUnavailable, AIKeyProblem) as e:
            log.warning("vision confirm skipped: %s", e)
        except Exception as e:
            log.error("vision confirm failed: %s", e)
        db.execute("UPDATE alerts SET vision_confirmed=%s, meta=%s WHERE id=%s", (confirmed, Jsonb(meta), alert_id))
    if confirmed is False:
        log.info("alert %s suppressed by vision check (%s)", alert_id, meta.get("vision_reason"))
        return alert_id

    db.execute("SELECT pg_notify('nazar_alerts', %s)", (str(alert_id),))
    log.info("ALERT %s rule=%s track=%s: %s", alert_id, rule["id"], hit.track_id, msg)
    if ai.available():
        try:
            out = storage.local_path(f"tts/alert_{alert_id}.mp3")
            p = ai.tts(msg, language, out_path=out, ref=f"alert:{alert_id}")
            key = storage.put(p, f"tts/alert_{alert_id}.mp3")
            db.execute("UPDATE alerts SET audio_key=%s WHERE id=%s", (key, alert_id))
            db.execute("SELECT pg_notify('nazar_alerts', %s)", (f"{alert_id}:audio",))
        except Exception as e:
            log.error("alert TTS failed: %s", e)
    return alert_id
