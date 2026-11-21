"""SigLIP 2 image/text embeddings (local, GPU fp16 when available). Fallback: open_clip ViT-B-32 if installed.

All inputs are already face-blurred crops/keyframes or owner-uploaded photos (blurred before embedding).
Embeddings are L2-normalized 768-d vectors stored as pgvector halfvec.
"""
from __future__ import annotations

import logging
import os
import threading
import time

import numpy as np

log = logging.getLogger("nazar.vision.siglip")
MODEL_ID = os.environ.get("NAZAR_SIGLIP", "google/siglip2-base-patch16-224")
DIM = 768


class SigLIP:
    def __init__(self, device: str | None = None):
        self.device_pref = device
        self.model = None
        self.proc = None
        self.device = "cpu"
        self.lock = threading.Lock()
        self.last_used = 0.0

    def load(self) -> None:
        if self.model is not None:
            return
        import torch
        from transformers import AutoModel, AutoProcessor

        t0 = time.time()
        self.device = self.device_pref or ("cuda" if torch.cuda.is_available() else "cpu")
        dtype = torch.float16 if self.device == "cuda" else torch.float32
        self.model = AutoModel.from_pretrained(MODEL_ID, torch_dtype=dtype).to(self.device).eval()
        self.proc = AutoProcessor.from_pretrained(MODEL_ID, use_fast=True)
        self.dtype = dtype
        log.info("SigLIP 2 loaded on %s in %.1fs", self.device, time.time() - t0)

    def unload(self) -> None:
        with self.lock:
            if self.model is None:
                return
            import torch

            self.model = None
            self.proc = None
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            log.info("SigLIP unloaded (idle)")

    @staticmethod
    def _norm(x: np.ndarray) -> np.ndarray:
        n = np.linalg.norm(x, axis=1, keepdims=True)
        return x / np.maximum(n, 1e-8)

    def embed_images(self, images: list) -> np.ndarray:
        """images: list of RGB PIL images or HxWx3 RGB uint8 arrays."""
        import torch
        from PIL import Image

        with self.lock:
            self.load()
            self.last_used = time.time()
            pil = [im if isinstance(im, Image.Image) else Image.fromarray(im) for im in images]
            out = []
            for i in range(0, len(pil), 32):
                x = self.proc(images=pil[i:i + 32], return_tensors="pt")
                with torch.inference_mode():
                    f = self.model.get_image_features(pixel_values=x["pixel_values"].to(self.device, self.dtype))
                out.append(f.float().cpu().numpy())
            return self._norm(np.concatenate(out)) if out else np.zeros((0, DIM), np.float32)

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        import torch

        with self.lock:
            self.load()
            self.last_used = time.time()
            x = self.proc(text=[t.lower() for t in texts], padding="max_length", max_length=64, truncation=True,
                          return_tensors="pt")
            with torch.inference_mode():
                f = self.model.get_text_features(**{k: v.to(self.device) for k, v in x.items()})
            return self._norm(f.float().cpu().numpy())
