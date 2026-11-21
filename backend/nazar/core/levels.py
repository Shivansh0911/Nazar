"""Evidence levels. This module is the ONLY place a level is decided; the model never sets one."""
from __future__ import annotations

from typing import Literal

from .config import get_settings

Level = Literal["confirmed", "probable", "candidate"]
LEVEL_ORDER = {"confirmed": 0, "probable": 1, "candidate": 2}


def assign_level(*, structural_only: bool, sim: float | None, attr_requested: int, attr_matched: int,
                 probable_sim: float | None = None, candidate_sim: float | None = None) -> Level | None:
    s = get_settings()
    p_sim = s.LEVEL_PROBABLE_SIM if probable_sim is None else probable_sim
    c_sim = s.LEVEL_CANDIDATE_SIM if candidate_sim is None else candidate_sim
    if structural_only:
        return "confirmed"
    if attr_requested > 0 and attr_matched == attr_requested and (sim is None or sim >= p_sim):
        return "probable"
    if attr_requested == 0 and sim is not None and sim >= p_sim + 0.1:
        return "probable"
    if (sim is not None and sim >= c_sim) or attr_matched >= 1:
        return "candidate"
    return None


def sort_key(level: str, score: float = 0.0) -> tuple:
    return (LEVEL_ORDER.get(level, 9), -score)
