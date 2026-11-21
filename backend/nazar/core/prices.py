"""OpenAI price table (USD). Override any entry with env PRICES_JSON, e.g.
PRICES_JSON={"gpt-5.4-mini": {"input": 0.25, "cached": 0.025, "output": 2.0}}
Token prices are per 1M tokens; audio prices are per minute.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache

from .config import get_settings

log = logging.getLogger("nazar.prices")

DEFAULT_PRICES: dict[str, dict] = {
    "gpt-6-luna": {"input": 0.10, "cached": 0.01, "output": 0.50},
    "gpt-6-sol": {"input": 2.00, "cached": 0.20, "output": 10.00},
    "text-embedding-3-small": {"input": 0.02},
    "gpt-4o-transcribe": {"audio_minute": 0.006},
    "gpt-4o-mini-tts": {"audio_minute": 0.015},
}
FLEX_FACTOR = 0.5  # Flex processing is priced at about half of Standard
_warned: set[str] = set()


@lru_cache
def price_table() -> dict[str, dict]:
    table = {k: dict(v) for k, v in DEFAULT_PRICES.items()}
    raw = get_settings().PRICES_JSON.strip()
    if raw:
        try:
            for k, v in json.loads(raw).items():
                table.setdefault(k, {}).update(v)
        except Exception as e:
            log.warning("PRICES_JSON is not valid JSON (%s); using defaults", e)
    return table


def _lookup(model: str) -> dict | None:
    t = price_table()
    if model in t:
        return t[model]
    # dated snapshots like gpt-6-luna-2026-05-01
    for k in sorted(t, key=len, reverse=True):
        if model.startswith(k):
            return t[k]
    return None


def cost_tokens(model: str, input_tokens: int = 0, cached_tokens: int = 0, output_tokens: int = 0) -> tuple[float, bool]:
    """Returns (usd, unknown_price)."""
    p = _lookup(model)
    if p is None or ("input" not in p):
        if model not in _warned:
            log.warning("no price for model %s; counting cost as 0 (set PRICES_JSON)", model)
            _warned.add(model)
        return 0.0, True
    fresh = max(0, (input_tokens or 0) - (cached_tokens or 0))
    usd = (fresh * p.get("input", 0) + (cached_tokens or 0) * p.get("cached", p.get("input", 0))
           + (output_tokens or 0) * p.get("output", 0)) / 1_000_000
    return usd, False


def cost_audio(model: str, seconds: float) -> tuple[float, bool]:
    p = _lookup(model)
    if p is None or "audio_minute" not in p:
        if model not in _warned:
            log.warning("no audio price for model %s; counting cost as 0 (set PRICES_JSON)", model)
            _warned.add(model)
        return 0.0, True
    return p["audio_minute"] * max(0.0, seconds) / 60.0, False


def usd_to_inr(usd: float) -> float:
    return usd * get_settings().USD_INR
