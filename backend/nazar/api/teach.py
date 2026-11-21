"""Teach it anything (W4): "gas cylinder pe nazar rakho" -> a custom object on a camera, detected with YOLOE
(open-vocabulary, text prompts). Replay first: the past is checked on the stored, face-blurred keyframes (local, Rs 0)
and sightings become tracks with cls = custom:<name> (Candidate until a person or AI check confirms). Then the live
edge runs YOLOE on that camera's frames (~2 fps) so rules can fire on the new class.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime, timedelta, timezone

import cv2
import numpy as np

from ..core import db, storage
from ..core.timeutil import to_local

log = logging.getLogger("nazar.teach")
YOLOE_WEIGHTS = "yoloe-26s-seg.pt"
_model = None
_model_lock = threading.Lock()


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40] or "object"


def yoloe(classes: list[str]):
    """One shared YOLOE instance (lazy); set_classes is cheap."""
    global _model
    from pathlib import Path

    from ultralytics import YOLOE

    with _model_lock:
        if _model is None:
            w = Path(__file__).resolve().parents[2] / "models" / YOLOE_WEIGHTS
            _model = YOLOE(str(w) if w.exists() else YOLOE_WEIGHTS)
        _model.set_classes(classes)
        return _model


class OpenVocab:
    """Live open-vocabulary detector for a camera's active custom objects (used by the edge)."""

    def __init__(self, camera_id: str, imgsz: int = 640):
        self.camera_id = camera_id
        self.imgsz = imgsz
        self.objects: list[dict] = []
        self.model = None
        self.tracker = None
        self.last_refresh = 0.0

    def refresh(self) -> bool:
        import time

        if time.monotonic() - self.last_refresh < 10:
            return bool(self.objects)
        self.last_refresh = time.monotonic()
        rows = db.fetch_all("SELECT id, name, prompt_text, threshold FROM custom_objects WHERE camera_id=%s AND active AND prompt_type='text' "
                            "ORDER BY id", (self.camera_id,))
        if [r["id"] for r in rows] != [o["id"] for o in self.objects]:
            self.objects = rows
            if rows:
                self.model = yoloe([r["prompt_text"] or r["name"] for r in rows])
                from ..edge.detector import make_tracker

                self.tracker = make_tracker("bytetrack", 2.0)
        return bool(self.objects)

    def detect(self, frame: np.ndarray):
        """-> list of Det with cls 'custom:<name>' and ids offset by 5_000_000 (separate tracker)."""
        from ..edge.detector import Det, _NpBoxes

        if not self.objects or self.model is None:
            return []
        h, w = frame.shape[:2]
        thr = min(float(o["threshold"] or 0.25) for o in self.objects)
        r = self.model.predict(frame, conf=thr, imgsz=self.imgsz, verbose=False, half=True)[0]
        b = r.boxes
        if b is None or len(b) == 0:
            tracks = self.tracker.update(_NpBoxes(np.zeros((0, 4)), np.zeros(0), np.zeros(0)), frame)
        else:
            tracks = self.tracker.update(_NpBoxes(b.xyxy.cpu().numpy(), b.conf.cpu().numpy(), b.cls.cpu().numpy()), frame)
        out = []
        for t in tracks:
            k = int(t[6])
            if 0 <= k < len(self.objects):
                x1, y1, x2, y2 = (float(np.clip(t[0] / w, 0, 1)), float(np.clip(t[1] / h, 0, 1)),
                                  float(np.clip(t[2] / w, 0, 1)), float(np.clip(t[3] / h, 0, 1)))
                if x2 > x1 and y2 > y1:
                    out.append(Det(int(t[4]) + 5_000_000, f"custom:{slug(self.objects[k]['name'])}", (x1, y1, x2, y2), float(t[5])))
        return out


def replay_keyframes(obj_id: int, hours: float = 24.0, max_frames: int = 400) -> dict:
    """Run YOLOE over the camera's stored keyframes (blurred, 512 px) and store sightings as custom tracks."""
    o = db.fetch_one("SELECT * FROM custom_objects WHERE id=%s", (obj_id,))
    if not o:
        return {"error": "not found"}
    last = db.fetch_val("SELECT max(t) FROM keyframes WHERE camera_id=%s", (o["camera_id"],))
    if last is None:
        return {"frames": 0, "sightings": 0}
    rows = db.fetch_all("SELECT t, key FROM keyframes WHERE camera_id=%s AND t >= %s ORDER BY t DESC LIMIT %s",
                        (o["camera_id"], last - timedelta(hours=hours), max_frames))
    rows.reverse()
    m = yoloe([o["prompt_text"] or o["name"]])
    cls = f"custom:{slug(o['name'])}"
    groups: list[dict] = []  # consecutive sightings -> one track
    for r in rows:
        img = cv2.imread(str(storage.local_path(r["key"])))
        if img is None:
            continue
        res = m.predict(img, conf=float(o["threshold"] or 0.25), verbose=False, half=True)[0]
        if res.boxes is None or len(res.boxes) == 0:
            continue
        h, w = img.shape[:2]
        k = int(np.argmax(res.boxes.conf.cpu().numpy()))
        x1, y1, x2, y2 = res.boxes.xyxy.cpu().numpy()[k] / np.array([w, h, w, h])
        conf = float(res.boxes.conf[k])
        t_ms = int(r["t"].timestamp() * 1000)
        pt = [t_ms, round(float(x1), 4), round(float(y1), 4), round(float(x2), 4), round(float(y2), 4), round(conf, 3)]
        if groups and t_ms - groups[-1]["path"][-1][0] <= 4500:
            groups[-1]["path"].append(pt)
            groups[-1]["max_conf"] = max(groups[-1]["max_conf"], conf)
        else:
            groups.append({"path": [pt], "max_conf": conf, "key": r["key"], "box": (x1, y1, x2, y2)})
    run_id = f"teach-{obj_id}"
    db.execute("DELETE FROM tracks WHERE camera_id=%s AND run_id=%s", (o["camera_id"], run_id))
    for i, g in enumerate(groups):
        img = cv2.imread(str(storage.local_path(g["key"])))
        crop_keys = []
        if img is not None:
            h, w = img.shape[:2]
            x1, y1, x2, y2 = g["box"]
            c = img[max(0, int(y1 * h) - 4):int(y2 * h) + 4, max(0, int(x1 * w) - 4):int(x2 * w) + 4]
            if c.size:
                ok, buf = cv2.imencode(".jpg", c, [cv2.IMWRITE_JPEG_QUALITY, 85])
                if ok:
                    key = f"crops/{o['camera_id']}/{run_id}_{i}.jpg"
                    storage.put_bytes(buf.tobytes(), key)
                    crop_keys.append(key)
        t0 = datetime.fromtimestamp(g["path"][0][0] / 1000, tz=timezone.utc)
        t1 = datetime.fromtimestamp(g["path"][-1][0] / 1000, tz=timezone.utc)
        db.execute("INSERT INTO tracks(camera_id, run_id, local_id, cls, t_start, t_end, active, path, max_conf, crop_keys, "
                   "custom_object_id) VALUES (%s,%s,%s,%s,%s,%s,false,%s::jsonb,%s,%s,%s)",
                   (o["camera_id"], run_id, i, cls, t0, t1, json.dumps(g["path"]), round(g["max_conf"], 3), crop_keys, obj_id))
    return {"frames": len(rows), "sightings": len(groups), "first": to_local(datetime.fromtimestamp(groups[0]["path"][0][0] / 1000,
            tz=timezone.utc)).isoformat() if groups else None}


def teach_from_text(camera_id: str, name: str, *, alert: bool = False, ref: str | None = None) -> dict:
    name = (name or "").strip()[:40]
    if len(name) < 2:
        return {"ok": False, "error": "name the object"}
    cam = db.fetch_one("SELECT id, name FROM cameras WHERE id=%s", (camera_id,))
    if not cam:
        return {"ok": False, "error": f"camera {camera_id} not found"}
    row = db.fetch_one("INSERT INTO custom_objects(camera_id, name, prompt_type, prompt_text) VALUES (%s,%s,'text',%s) "
                       "ON CONFLICT (camera_id, name) DO UPDATE SET active=true, prompt_text=EXCLUDED.prompt_text RETURNING id",
                       (camera_id, name.lower(), name.lower()))
    obj_id = row["id"]
    rep = {}
    try:
        rep = replay_keyframes(obj_id)
    except Exception as e:
        log.warning("teach replay failed: %s", e)
        rep = {"error": str(e)[:200]}
    rule = None
    if alert:
        from psycopg.types.json import Jsonb

        from ..core.rules import RuleSpec

        spec = RuleSpec(camera_id=camera_id, trigger="zone_enter", cls=f"custom:{slug(name)}", zone="anywhere")
        rule = db.fetch_one("INSERT INTO rules(camera_id, text, spec, human, active, language) VALUES (%s,%s,%s,%s,false,'en') "
                            "RETURNING id", (camera_id, f"alert when a {name} appears", Jsonb(spec.dump()),
                                             f"Alert me with a voice note when a {name} appears on {cam['name']}."))["id"]
    n = rep.get("sightings", 0)
    msg = (f"Now watching for '{name}' on {cam['name']}. Replay on the last day of stored frames: "
           + (f"{n} possible sighting{'s' if n != 1 else ''} (Candidates - check them)." if n else "no sightings.")
           + (" A rule is ready to activate." if rule else ""))
    return {"ok": True, "object_id": obj_id, "name": name, "camera_id": camera_id, "cls": f"custom:{slug(name)}",
            "replay": rep, "rule_id": rule, "message": msg}


# ---- teach by photo (SigLIP 2 image prompt; local, Rs 0) -------------------------------------------------------------
PHOTO_MATCH_SIM = 0.85  # floor of the adaptive image->image threshold (SigLIP 2)


def teach_from_photo(camera_id: str, name: str, jpeg: bytes, image_key: str, *, alert: bool = False,
                     threshold: float = PHOTO_MATCH_SIM) -> dict:
    """Store the photo embedding as a custom object, replay it over the last day (Candidates), optionally add an
    alert rule. Live matching runs in the worker (nazar.worker.visual_watch)."""
    from datetime import timezone as _tz

    from ..core.vision_client import embed_images, vec_literal
    from . import visual

    name = (name or "").strip()[:40] or "my object"
    cam = db.fetch_one("SELECT id, name FROM cameras WHERE id=%s", (camera_id,))
    if not cam:
        return {"ok": False, "error": f"camera {camera_id} not found"}
    vec = embed_images([jpeg])[0]
    top = db.fetch_val("SELECT COALESCE(max(id), 0) FROM tracks WHERE camera_id=%s", (camera_id,))
    # SigLIP image-image similarity is high for any CCTV crop (~0.81 median), so the threshold adapts: only matches
    # above the 97.5th percentile of this photo's similarity to everything indexed so far count (min 0.85)
    p99 = db.fetch_val("SELECT percentile_cont(0.975) WITHIN GROUP (ORDER BY 1 - (vis_emb <=> %s::halfvec)) FROM "
                       "(SELECT vis_emb FROM tracks WHERE vis_emb IS NOT NULL ORDER BY id DESC LIMIT 5000) x", (vec_literal(vec),))
    threshold = max(threshold, float(p99 or 0))
    obj_id = db.fetch_one(
        "INSERT INTO custom_objects(camera_id, name, prompt_type, prompt_image_key, prompt_emb, threshold, last_checked_id) "
        "VALUES (%s,%s,'visual',%s,%s::halfvec,%s,%s) ON CONFLICT (camera_id, name) DO UPDATE SET prompt_type='visual', "
        "prompt_image_key=EXCLUDED.prompt_image_key, prompt_emb=EXCLUDED.prompt_emb, threshold=EXCLUDED.threshold, "
        "last_checked_id=EXCLUDED.last_checked_id, active=true RETURNING id",
        (camera_id, name.lower(), image_key, vec_literal(vec), threshold, top))["id"]
    now = datetime.now(_tz.utc)
    hits = [h for h in visual.search(vec, t_from=now - timedelta(days=1), t_to=now, camera_ids=[camera_id], limit=12,
                                     mode="photo") if h["sim"] >= threshold]
    rule = None
    if alert:
        from psycopg.types.json import Jsonb

        from ..core.rules import RuleSpec

        spec = RuleSpec(camera_id=camera_id, trigger="zone_enter", cls=f"custom:{slug(name)}", zone="anywhere")
        rule = db.fetch_one("INSERT INTO rules(camera_id, text, spec, human, active, language) VALUES (%s,%s,%s,%s,false,'en') "
                            "RETURNING id", (camera_id, f"alert when my {name} is seen", Jsonb(spec.dump()),
                                             f"Alert me with a voice note when {name} (from my photo) is seen on {cam['name']}."))["id"]
    msg = (f"Now watching {cam['name']} for '{name}' from your photo (appearance match, no training). Replay on the "
           f"last day: {len(hits)} similar sighting{'s' if len(hits) != 1 else ''} (Candidates - check them)."
           + (" A rule is ready to activate." if rule else ""))
    return {"ok": True, "object_id": obj_id, "name": name, "camera_id": camera_id, "cls": f"custom:{slug(name)}",
            "threshold": round(threshold, 3), "replay": {"sightings": len(hits), "hits": hits[:6]}, "rule_id": rule,
            "message": msg}
