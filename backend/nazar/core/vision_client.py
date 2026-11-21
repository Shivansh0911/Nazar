"""Client for the local vision service (SigLIP 2 embeddings). Rs 0 per call - nothing leaves the machine."""
from __future__ import annotations

import base64
import logging

import httpx

from .config import get_settings

log = logging.getLogger("nazar.vision_client")


class VisionUnavailable(RuntimeError):
    pass


def _post(path: str, payload: dict, timeout: float = 60.0) -> dict:
    url = get_settings().VISION_URL.rstrip("/") + path
    try:
        r = httpx.post(url, json=payload, timeout=timeout)
    except httpx.HTTPError as e:
        raise VisionUnavailable("the local vision service is not running (start: python -m nazar.vision.service)") from e
    if r.status_code != 200:
        raise VisionUnavailable(f"vision service error {r.status_code}: {r.text[:200]}")
    return r.json()


def embed_texts(texts: list[str]) -> list[list[float]]:
    return _post("/embed/text", {"texts": texts})["vectors"]


def embed_images(jpegs: list[bytes]) -> list[list[float]]:
    return _post("/embed/image", {"images": [base64.b64encode(b).decode() for b in jpegs]})["vectors"]


def health() -> dict | None:
    try:
        r = httpx.get(get_settings().VISION_URL.rstrip("/") + "/health", timeout=3.0)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def vec_literal(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.5f}" for x in v) + "]"
