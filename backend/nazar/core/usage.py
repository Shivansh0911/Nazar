"""Write one `usage` row per OpenAI call (with cost)."""
from __future__ import annotations

import logging

from . import db

log = logging.getLogger("nazar.usage")


def record(kind: str, model: str, *, camera_id: str | None = None, ref: str | None = None,
           input_tokens: int | None = None, cached_tokens: int | None = None, output_tokens: int | None = None,
           images: int | None = None, audio_seconds: float | None = None, cost_usd: float = 0.0,
           unknown_price: bool = False, service_tier: str | None = None) -> None:
    try:
        db.execute(
            """INSERT INTO usage(kind, model, camera_id, ref, input_tokens, cached_tokens, output_tokens,
                                 images, audio_seconds, cost_usd, unknown_price, service_tier)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (kind, model, camera_id, ref, input_tokens, cached_tokens, output_tokens, images, audio_seconds,
             round(float(cost_usd), 6), unknown_price, service_tier),
        )
    except Exception as e:  # never break the caller because of accounting
        log.error("could not record usage (%s %s): %s", kind, model, e)


def spent_today(kinds: tuple[str, ...]) -> float:
    v = db.fetch_val(
        "SELECT COALESCE(sum(cost_usd),0) FROM usage WHERE kind = ANY(%s) AND at >= date_trunc('day', now())",
        (list(kinds),),
    )
    return float(v or 0)
