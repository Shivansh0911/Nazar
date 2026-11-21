"""Zone helpers: validation, default boxes and AI suggestions from a (face-blurred) snapshot."""
from __future__ import annotations

import base64
import re

from .config import get_settings
from .schemas import ZoneIn, ZoneSuggestions

ZONE_SYSTEM = (
    "You help a shop owner mark areas on their CCTV view. Look at the face-blurred snapshot and propose up to 6 "
    "useful zones where people or vehicles stand or pass: e.g. counter, entrance, gate, desk, cash area, parking, "
    "footpath, road. For each zone return: name (snake_case English, short), label (short owner-friendly words), and "
    "polygon: 4-8 points [x, y] normalized 0..1 (x right, y down) tracing the FLOOR area where feet would be. "
    "Zones must not cover the whole frame. Never describe people."
)


def slugify(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")
    return s[:40] or "zone"


def clean_zones(zones: list) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for z in zones or []:
        zi = z if isinstance(z, ZoneIn) else ZoneIn.model_validate(z)
        name = slugify(zi.name)
        if name in seen or name == "anywhere":
            continue
        pts = [[round(min(1.0, max(0.0, float(p[0]))), 4), round(min(1.0, max(0.0, float(p[1]))), 4)]
               for p in zi.polygon if len(p) >= 2]
        if len(pts) < 3:
            continue
        seen.add(name)
        out.append({"name": name, "label": (zi.label or name.replace("_", " ").title())[:40], "polygon": pts})
    return out


def default_zones() -> list[dict]:
    return [
        {"name": "counter", "label": "Counter", "polygon": [[0.3, 0.35], [0.7, 0.35], [0.7, 0.85], [0.3, 0.85]]},
        {"name": "entrance", "label": "Entrance", "polygon": [[0.0, 0.3], [0.25, 0.3], [0.25, 0.95], [0.0, 0.95]]},
    ]


def suggest_zones(jpeg: bytes, camera_id: str | None = None) -> list[dict]:
    from .openai_client import get_ai

    ai = get_ai()
    inp = [{"role": "user", "content": [
        {"type": "input_text", "text": "Propose zones for this camera view."},
        {"type": "input_image", "image_url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode(), "detail": "high"},
    ]}]
    res, _ = ai.parse(get_settings().OPENAI_AGENT_MODEL, inp, ZoneSuggestions, kind="zones", instructions=ZONE_SYSTEM,
                      camera_id=camera_id, ref="suggest-zones", images=1, max_output_tokens=1500)
    return clean_zones(res.zones[:6])
