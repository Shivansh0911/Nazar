"""Visual search by words or photo, AI verification of top hits, cross-camera journey (W3)."""
from __future__ import annotations

import json
import uuid

import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field
from psycopg.types.json import Jsonb

from ..core import db, storage
from ..core.vision_client import VisionUnavailable
from . import visual
from .auth import require_token
from .deps import http_error, window

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])
MAX_PHOTO_MB = 12


def _blur_photo(data: bytes, box: list[float] | None) -> tuple[bytes, bool]:
    """Decode, crop to the owner's box, blur any faces. Returns (jpeg, face_only) - face_only = the photo is
    basically a face (Nazar never searches by face)."""
    from ..edge.faceblur import FaceBlurrer

    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise http_error(400, "could not read that image")
    h, w = img.shape[:2]
    if box and len(box) == 4:
        x1, y1, x2, y2 = [float(v) for v in box]
        X1, Y1, X2, Y2 = int(max(0, x1) * w), int(max(0, y1) * h), int(min(1, x2) * w), int(min(1, y2) * h)
        if X2 - X1 > 8 and Y2 - Y1 > 8:
            img = img[Y1:Y2, X1:X2].copy()
            h, w = img.shape[:2]
    if max(h, w) > 1024:
        s = 1024 / max(h, w)
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    b = FaceBlurrer()
    faces = b.detect(img)
    face_area = max(((f[2] - f[0]) * (f[3] - f[1]) for f in faces), default=0.0)
    out = b.egress(img, [], detect=False)
    for fx1, fy1, fx2, fy2 in faces:
        hh, ww = out.shape[:2]
        pw, ph = (fx2 - fx1) * 0.3, (fy2 - fy1) * 0.3
        b._blur_region(out, int((fx1 - pw) * ww), int((fy1 - ph) * hh), int((fx2 + pw) * ww), int((fy2 + ph) * hh))
    ok, buf = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return buf.tobytes(), face_area > 0.12


@router.post("/search/visual")
async def visual_search(text: str | None = Form(None), image: UploadFile | None = File(None),
                        purpose: str | None = Form(None), camera_ids: str | None = Form(None),
                        time_from: str | None = Form(None), time_to: str | None = Form(None),
                        cls: str | None = Form(None), box: str | None = Form(None), verify: bool = Form(False),
                        limit: int = Form(12), token: str = Depends(require_token)):
    """Search the local visual index by words (any language) and/or a photo (bag, jacket, vehicle...)."""
    t0, t1 = window(time_from, time_to, 24 * 7)
    cams = [c for c in (camera_ids or "").split(",") if c] or None
    classes = [c for c in (cls or "").split(",") if c] or None
    image_key = None
    jpeg = None
    if image is not None:
        data = await image.read()
        if len(data) > MAX_PHOTO_MB * 1024 * 1024:
            raise http_error(413, f"photo larger than {MAX_PHOTO_MB} MB")
        jpeg, face_only = _blur_photo(data, json.loads(box) if box else None)
        if face_only:
            raise http_error(422, "Nazar does not search by face. Crop the photo to the clothes, bag or vehicle "
                                  "(or describe them in words) and try again.")
        image_key = f"photo_searches/{uuid.uuid4().hex}.jpg"
        storage.put_bytes(jpeg, image_key)
    if not jpeg and not (text or "").strip():
        raise http_error(400, "give words or a photo")
    try:
        vec = visual.query_vector(text=(text or "").strip() or None, image_jpeg=jpeg)
    except VisionUnavailable as e:
        raise http_error(503, str(e))
    hits = visual.search(vec, t_from=t0, t_to=t1, camera_ids=cams, cls=classes, limit=max(1, min(limit, 40)),
                         mode="photo" if jpeg else "text")
    if jpeg is not None:
        db.execute("INSERT INTO photo_searches(purpose, image_key, params, result_count) VALUES (%s,%s,%s,%s)",
                   ((purpose or "").strip()[:300] or None, image_key,
                    Jsonb({"text": text, "cameras": cams, "cls": classes, "from": t0.isoformat(), "to": t1.isoformat()}),
                    len(hits)))
    verified = False
    if verify and text and hits:
        try:
            visual.verify(text, hits, user_waiting=True, ref=f"vs:{uuid.uuid4().hex[:10]}")
            verified = True
        except Exception as e:
            return {"hits": visual.with_urls(hits, token), "verified": False, "note": f"AI check failed: {e}"[:200]}
    return {"hits": visual.with_urls(hits, token), "verified": verified, "query_image_url": storage.url(image_key, token),
            "window": {"from": t0.isoformat(), "to": t1.isoformat()}}


class VerifyIn(BaseModel):
    question: str = Field(min_length=2, max_length=300)
    hits: list[dict] = Field(min_length=1, max_length=40)


@router.post("/search/verify")
def verify_hits(body: VerifyIn, token: str = Depends(require_token)):
    """AI-check the top hits (<= 8, low detail). Only recorded 'yes' + similarity -> Probable."""
    hits = []
    for h in body.hits:
        kind = h.get("kind")
        if kind == "track":
            r = db.fetch_one("SELECT crop_keys FROM tracks WHERE id=%s", (int(h["id"]),))
            key = (r and (r["crop_keys"] or [None])[0])
        elif kind == "keyframe":
            key = db.fetch_val("SELECT key FROM keyframes WHERE id=%s", (int(h["id"]),))
        else:
            continue
        if key:
            hits.append({**h, "thumb_key": key, "sim": float(h.get("sim") or 0), "level": "candidate"})
    if not hits:
        raise http_error(400, "nothing to verify")
    visual.verify(body.question, hits, user_waiting=True, ref=f"vs:{uuid.uuid4().hex[:10]}")
    return {"hits": visual.with_urls(hits, token)}


@router.get("/journey/{track_id}")
def journey(track_id: int, hours: float = 24.0, token: str = Depends(require_token)):
    j = visual.journey(track_id, hours=min(max(hours, 1.0), 72.0))
    visual.with_urls(j["steps"], token)
    names = {r["id"]: r["name"] for r in db.fetch_all("SELECT id, name FROM cameras")}
    j["summary"] = " → ".join(names.get(c, c) for c in j.get("cameras", []))
    for s in j["steps"]:
        s["camera_name"] = names.get(s["camera_id"], s["camera_id"])
    return j


@router.get("/photo-searches")
def photo_search_audit(limit: int = 50, token: str = Depends(require_token)):
    rows = db.fetch_all("SELECT id, at, purpose, image_key, result_count FROM photo_searches ORDER BY at DESC LIMIT %s",
                        (min(limit, 200),))
    return [{"id": r["id"], "at": r["at"].isoformat(), "purpose": r["purpose"], "result_count": r["result_count"],
             "image_url": storage.url(r["image_key"], token)} for r in rows]
