"""76-d appearance fingerprint (SETU style): free, deterministic, no API.

60 = Lab histograms (L6 + a12 + b12) for upper and lower body regions
12 = whole-box HSV hue histogram on saturated, bright pixels
 4 = Sobel edge orientation histogram, magnitude weighted
Each block L1-normalized, then the full vector L2-normalized.
"""
from __future__ import annotations

import cv2
import numpy as np

DIM = 76
VEHICLES = {"car", "motorcycle", "bus", "truck", "bicycle"}


def _l1(v: np.ndarray) -> np.ndarray:
    s = float(v.sum())
    return v / s if s > 0 else v


def _lab_block(region: np.ndarray) -> np.ndarray:
    if region.size == 0:
        return np.zeros(30, np.float32)
    lab = cv2.cvtColor(region, cv2.COLOR_BGR2LAB)
    L = np.histogram(lab[..., 0], bins=6, range=(0, 256))[0].astype(np.float32)
    a = np.histogram(lab[..., 1], bins=12, range=(0, 256))[0].astype(np.float32)
    b = np.histogram(lab[..., 2], bins=12, range=(0, 256))[0].astype(np.float32)
    return np.concatenate([_l1(L), _l1(a), _l1(b)])


def fingerprint(crop_bgr: np.ndarray, cls: str = "person") -> np.ndarray:
    if crop_bgr is None or crop_bgr.size == 0:
        return np.zeros(DIM, np.float32)
    h = crop_bgr.shape[0]
    if cls in VEHICLES:
        upper = lower = crop_bgr
    else:
        upper = crop_bgr[int(h * 0.15): max(int(h * 0.50), int(h * 0.15) + 1)]
        lower = crop_bgr[int(h * 0.50): max(int(h * 0.90), int(h * 0.50) + 1)]
    blocks = [_lab_block(upper), _lab_block(lower)]

    hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
    mask = (hsv[..., 1] > 40) & (hsv[..., 2] > 40)
    hues = hsv[..., 0][mask]
    hue = np.histogram(hues, bins=12, range=(0, 180))[0].astype(np.float32)
    blocks.append(_l1(hue))

    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    mag = np.sqrt(gx * gx + gy * gy)
    ang = (np.degrees(np.arctan2(gy, gx)) + 180.0) % 180.0
    edges = np.histogram(ang, bins=4, range=(0, 180), weights=mag)[0].astype(np.float32)
    blocks.append(_l1(edges))

    v = np.concatenate(blocks).astype(np.float32)
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


def as_list(v) -> list[float] | None:
    """pgvector returns Vector objects (pgvector>=0.3); accept lists/arrays too."""
    if v is None:
        return None
    if hasattr(v, "to_list"):
        return list(v.to_list())
    return [float(x) for x in v]


def cosine(a, b) -> float:
    a = np.asarray(a, np.float32)
    b = np.asarray(b, np.float32)
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))
