"""Vision service (one process owns the shared GPU models for search):  python -m nazar.vision.service

- POST /embed/text  {"texts": [...]}                 -> {"vectors": [[...768]]}
- POST /embed/image {"images": ["<base64 jpeg>", ...]} -> {"vectors": [...]}   (images must already be blurred)
- GET  /health
- background indexer: embeds new track crops (tracks.vis_emb) and scene keyframes (keyframes.emb) - local, Rs 0.
- releases GPU memory after 10 idle minutes; reloads on demand.
Listens on 127.0.0.1 only (VISION_URL).
"""
from __future__ import annotations

import base64
import io
import logging
import threading
import time

import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from ..core import db, storage
from ..core.config import get_settings
from ..core.logging import setup_logging
from .siglip import SigLIP

log = logging.getLogger("nazar.vision")
app = FastAPI(title="nazar-vision")
model = SigLIP()
IDLE_UNLOAD_S = 180  # release GPU memory quickly on an 8 GB laptop
stats = {"tracks_indexed": 0, "keyframes_indexed": 0, "errors": 0, "started": time.time()}


class TextIn(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=64)


class ImageIn(BaseModel):
    images: list[str] = Field(min_length=1, max_length=64)


def _vec_str(v: np.ndarray) -> str:
    return "[" + ",".join(f"{x:.5f}" for x in v.tolist()) + "]"


@app.get("/health")
def health():
    return {"ok": True, "loaded": model.model is not None, "device": model.device, **stats}


@app.post("/embed/text")
def embed_text(body: TextIn):
    return {"vectors": model.embed_texts(body.texts).round(5).tolist()}


@app.post("/embed/image")
def embed_image(body: ImageIn):
    from PIL import Image

    try:
        ims = [Image.open(io.BytesIO(base64.b64decode(b))).convert("RGB") for b in body.images]
    except Exception:
        raise HTTPException(400, "invalid image")
    return {"vectors": model.embed_images(ims).round(5).tolist()}


def _load_rgb(key: str):
    import cv2

    p = storage.local_path(key)
    img = cv2.imread(str(p))
    if img is None:
        return None
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def index_once(limit: int = 64) -> int:
    """Embed up to `limit` finished tracks and `limit` keyframes that have no visual embedding yet."""
    done = 0
    rows = db.fetch_all("SELECT id, crop_keys FROM tracks WHERE vis_indexed = false AND active = false "
                        "ORDER BY id DESC LIMIT %s", (limit,))
    if rows:
        ims, ids, empty = [], [], []
        for r in rows:
            img = _load_rgb(r["crop_keys"][0]) if r["crop_keys"] else None
            if img is None:
                empty.append(r["id"])
            else:
                ims.append(img)
                ids.append(r["id"])
        if ims:
            vecs = model.embed_images(ims)
            with db.conn() as c:
                with c.cursor() as cur:
                    cur.executemany("UPDATE tracks SET vis_emb=%s::halfvec, vis_indexed=true WHERE id=%s",
                                    [(_vec_str(v), i) for v, i in zip(vecs, ids)])
            stats["tracks_indexed"] += len(ids)
            done += len(ids)
        if empty:
            db.execute("UPDATE tracks SET vis_indexed=true WHERE id = ANY(%s)", (empty,))
    kfs = db.fetch_all("SELECT id, key FROM keyframes WHERE emb IS NULL ORDER BY id DESC LIMIT %s", (limit,))
    if kfs:
        ims, ids, gone = [], [], []
        for r in kfs:
            img = _load_rgb(r["key"])
            (gone if img is None else ids).append(r["id"])
            if img is not None:
                ims.append(img)
        if ims:
            vecs = model.embed_images(ims)
            with db.conn() as c:
                with c.cursor() as cur:
                    cur.executemany("UPDATE keyframes SET emb=%s::halfvec WHERE id=%s",
                                    [(_vec_str(v), i) for v, i in zip(vecs, ids)])
            stats["keyframes_indexed"] += len(ids)
            done += len(ids)
        if gone:
            db.execute("DELETE FROM keyframes WHERE id = ANY(%s)", (gone,))
    return done


def indexer_loop(stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            n = index_once()
        except Exception as e:
            stats["errors"] += 1
            log.warning("indexer: %s", e)
            n = 0
        if n == 0:
            if model.model is not None and time.time() - model.last_used > IDLE_UNLOAD_S:
                model.unload()
            stop.wait(2.0)


def main() -> None:
    setup_logging("nazar.vision")
    s = get_settings()
    stop = threading.Event()
    threading.Thread(target=indexer_loop, args=(stop,), name="indexer", daemon=True).start()
    port = int(s.VISION_URL.rsplit(":", 1)[-1].split("/")[0])
    import os

    # loopback by default; the prod compose sets VISION_BIND=0.0.0.0 inside the private Docker network
    uvicorn.run(app, host=os.environ.get("VISION_BIND", "127.0.0.1"), port=port, log_level="warning")
    stop.set()


if __name__ == "__main__":
    main()
