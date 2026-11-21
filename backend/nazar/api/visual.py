"""Local visual index search (W3): text or photo -> tracks + scene keyframes, AI verification, cross-camera journey.

Similarity comes from the local SigLIP 2 index (Rs 0). Every hit starts as Candidate. Only a RECORDED AI
verification "yes" (table `verifications`) plus enough similarity can make a hit Probable - decided here, in code.
No face recognition: the index is built from face-blurred crops/keyframes; photos are blurred before embedding.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel

from ..core import db, storage
from ..core.config import get_settings
from ..core.timeutil import to_local
from ..core.vision_client import embed_images, embed_texts, vec_literal

log = logging.getLogger("nazar.visual")
BAGS = ["backpack", "handbag", "suitcase"]
VEHICLES = ["car", "motorcycle", "bicycle", "bus", "truck"]
KF_DEDUPE_S = 12.0


def _cls_filter(cls: list[str] | None) -> list[str] | None:
    if not cls:
        return None
    out = set()
    for c in cls:
        if c in ("any_bag", "bag"):
            out |= set(BAGS)
        elif c in ("vehicle", "any_vehicle"):
            out |= set(VEHICLES)
        else:
            out.add(c)
    return sorted(out)


def query_vector(text: str | None = None, image_jpeg: bytes | None = None) -> list[float]:
    if image_jpeg is not None:
        return embed_images([image_jpeg])[0]
    if not text:
        raise ValueError("need text or an image")
    return embed_texts([text])[0]


def search(vec: list[float], *, t_from: datetime, t_to: datetime, camera_ids: list[str] | None = None,
           cls: list[str] | None = None, limit: int = 12, keyframes: bool = True, mode: str = "text",
           exclude_track: int | None = None) -> list[dict]:
    """Ranked hits (tracks + keyframes). Track hits use root tracks only; keyframes are deduped per ~12 s."""
    q = vec_literal(vec)
    where = ["t.merged_into IS NULL", "t.vis_emb IS NOT NULL", "t.t_end >= %s", "t.t_start <= %s"]
    params: list[Any] = [t_from, t_to]
    if camera_ids:
        where.append("t.camera_id = ANY(%s)")
        params.append(list(camera_ids))
    cf = _cls_filter(cls)
    if cf:
        where.append("t.cls = ANY(%s)")
        params.append(cf)
    if exclude_track:
        where.append("t.id <> %s")
        params.append(exclude_track)
    rows = db.fetch_all(
        f"SELECT t.id, t.camera_id, t.cls, t.t_start, t.t_end, t.crop_keys, t.caption, t.zone_path, "
        f"1 - (t.vis_emb <=> %s::halfvec) AS sim FROM tracks t WHERE {' AND '.join(where)} "
        f"ORDER BY t.vis_emb <=> %s::halfvec LIMIT %s", [q, *params, q, max(limit * 3, 30)])
    hits = [{"kind": "track", "id": r["id"], "track_id": r["id"], "camera_id": r["camera_id"], "cls": r["cls"],
             "t": to_local(r["t_start"]).isoformat(), "t_start": to_local(r["t_start"]).isoformat(),
             "t_end": to_local(r["t_end"]).isoformat(), "sim": round(float(r["sim"]), 4),
             "thumb_key": (r["crop_keys"] or [None])[0], "caption": r["caption"], "zones": list(r["zone_path"] or [])}
            for r in rows]
    # scene keyframes answer questions about things that were never tracked (shutter, cylinder, rain...)
    if keyframes and not cf and mode == "text":
        kw = ["k.emb IS NOT NULL", "k.t BETWEEN %s AND %s"]
        kp: list[Any] = [t_from, t_to]
        if camera_ids:
            kw.append("k.camera_id = ANY(%s)")
            kp.append(list(camera_ids))
        krows = db.fetch_all(
            f"SELECT k.id, k.camera_id, k.t, k.key, k.persons, 1 - (k.emb <=> %s::halfvec) AS sim FROM keyframes k "
            f"WHERE {' AND '.join(kw)} ORDER BY k.emb <=> %s::halfvec LIMIT %s", [q, *kp, q, limit * 4])
        kept: list[dict] = []
        for r in krows:
            if any(k["camera_id"] == r["camera_id"] and abs((k["_t"] - r["t"]).total_seconds()) < KF_DEDUPE_S for k in kept):
                continue
            kept.append({"kind": "keyframe", "id": r["id"], "track_id": None, "camera_id": r["camera_id"], "cls": "scene",
                         "t": to_local(r["t"]).isoformat(), "t_start": to_local(r["t"]).isoformat(),
                         "t_end": to_local(r["t"]).isoformat(), "sim": round(float(r["sim"]), 4),
                         "thumb_key": r["key"], "caption": None, "zones": [], "_t": r["t"]})
        for k in kept:
            k.pop("_t", None)
        hits.extend(kept)
    hits.sort(key=lambda h: -h["sim"])
    hits = hits[:limit]
    for h in hits:
        h["level"] = "candidate"
        h["why"] = f"looks similar (local index, sim {h['sim']:.2f})"
    apply_recorded_verifications(hits, None)
    return hits


# ---- verification ---------------------------------------------------------------------------------------
class HitCheck(BaseModel):
    index: int
    match: Literal["yes", "no", "unclear"]
    reason: str


class HitChecks(BaseModel):
    results: list[HitCheck]


VERIFY_SYSTEM = """You check CCTV search results. Each numbered image is a face-blurred crop or scene frame from a
shop/home camera. For EACH image decide whether it shows what the owner is looking for: "yes" only if clearly visible,
"no" if clearly not, "unclear" if too small/blurry/occluded. Judge clothing, objects, vehicles, scene state only -
never faces, identity, ethnicity, religion, caste or age. reason: <= 12 words, English."""


def _norm_q(q: str) -> str:
    return " ".join(q.lower().split())[:300]


def level_for(sim: float, match: str | None) -> str | None:
    """THE rule: Probable = local similarity AND an independent AI check agree; 'no' drops the hit."""
    if match == "no":
        return None
    if match == "yes" and sim >= get_settings().VERIFY_MIN_SIM:
        return "probable"
    return "candidate"


def apply_recorded_verifications(hits: list[dict], question: str | None) -> None:
    ids_t = [h["id"] for h in hits if h["kind"] == "track"]
    ids_k = [h["id"] for h in hits if h["kind"] == "keyframe"]
    if not ids_t and not ids_k:
        return
    rows = db.fetch_all("SELECT DISTINCT ON (kind, ref_id) kind, ref_id, match, reason, question FROM verifications "
                        "WHERE (kind='track' AND ref_id = ANY(%s)) OR (kind='keyframe' AND ref_id = ANY(%s)) "
                        + ("AND question=%s " if question else "") + "ORDER BY kind, ref_id, at DESC",
                        (ids_t, ids_k, _norm_q(question)) if question else (ids_t, ids_k))
    by = {(r["kind"], r["ref_id"]): r for r in rows}
    for h in hits:
        v = by.get((h["kind"], h["id"]))
        if v is None:
            continue
        lvl = level_for(h["sim"], v["match"])
        h["verified"] = v["match"]
        if lvl is None:
            h["level"] = "dropped"
            h["why"] = f"AI check: no - {v['reason']}"
        else:
            h["level"] = lvl
            if lvl == "probable":
                h["why"] = f"verified by AI: {v['reason']} · sim {h['sim']:.2f}"
            elif v["match"] == "unclear":
                h["why"] = f"AI check unclear: {v['reason']} · sim {h['sim']:.2f}"


def verify(question: str, hits: list[dict], *, user_waiting: bool = True, ref: str | None = None,
           k: int = 8) -> list[dict]:
    """Send the top K hits (blurred crops/keyframes, detail low) to the vision model; record each verdict."""
    from ..core.openai_client import _jpeg_data_url, get_ai

    ai = get_ai()
    top = [h for h in hits if h.get("thumb_key") and h.get("level") != "dropped"][:k]
    if not top or not ai.available():
        return hits
    content: list[dict] = [{"type": "input_text", "text": f"The owner is looking for: {question}\n"
                                                          f"{len(top)} images follow, numbered from 0."}]
    for i, h in enumerate(top):
        p = storage.local_path(h["thumb_key"])
        if not p.exists():
            continue
        content.append({"type": "input_text", "text": f"Image {i}:"})
        content.append({"type": "input_image", "image_url": _jpeg_data_url(p.read_bytes()), "detail": "low"})
    s = get_settings()
    res, _ = ai.parse(s.OPENAI_VISION_MODEL, [{"role": "user", "content": content}], HitChecks, kind="verify",
                      instructions=VERIFY_SYSTEM, ref=ref or "verify", images=len(top), max_output_tokens=800,
                      reasoning=s.VISION_REASONING_EFFORT or None, tier=None if user_waiting else "flex")
    qn = _norm_q(question)
    rows = []
    for r in res.results:
        if 0 <= r.index < len(top):
            h = top[r.index]
            rows.append((qn, h["kind"], h["id"], r.match, r.reason[:200], h["sim"], ref))
    if rows:
        with db.conn() as c:
            with c.cursor() as cur:
                cur.executemany("INSERT INTO verifications(question, kind, ref_id, match, reason, sim, usage_ref) "
                                "VALUES (%s,%s,%s,%s,%s,%s,%s)", rows)
    apply_recorded_verifications(hits, question)
    # verified tracks get a description in the background (smart enrichment)
    from ..worker.enricher import request

    request([h["id"] for h in top if h["kind"] == "track" and h.get("verified") == "yes"])
    hits[:] = [h for h in hits if h.get("level") != "dropped"]
    order = {"probable": 0, "candidate": 1}
    hits.sort(key=lambda h: (order.get(h["level"], 2), -h["sim"]))
    return hits


# ---- journey --------------------------------------------------------------------------------------------
def journey(track_id: int, hours: float = 24.0, limit: int = 12) -> dict:
    """Same-looking object on other cameras/times (SigLIP crop cosine + 76-d appearance + time plausibility).
    All sightings are Candidates unless verified. Never uses faces."""
    s = get_settings()
    tr = db.fetch_one("SELECT id, camera_id, cls, t_start, t_end, vis_emb::text AS v, crop_keys FROM tracks WHERE id=%s",
                      (track_id,))
    if not tr or not tr["v"]:
        return {"track_id": track_id, "steps": [], "note": "this track is not in the visual index yet"}
    group = BAGS if tr["cls"] in BAGS else VEHICLES if tr["cls"] in VEHICLES else [tr["cls"]]
    t0, t1 = tr["t_start"] - timedelta(hours=hours), tr["t_end"] + timedelta(hours=hours)
    rows = db.fetch_all(
        "SELECT t.id, t.camera_id, t.cls, t.t_start, t.t_end, t.crop_keys, 1 - (t.vis_emb <=> %s::halfvec) AS sim, "
        "CASE WHEN t.appearance IS NULL OR s.appearance IS NULL THEN NULL ELSE 1 - (t.appearance <=> s.appearance) END AS app "
        "FROM tracks t, tracks s WHERE s.id=%s AND t.id <> s.id AND t.merged_into IS NULL AND t.vis_emb IS NOT NULL "
        "AND t.cls = ANY(%s) AND t.t_start BETWEEN %s AND %s ORDER BY t.vis_emb <=> %s::halfvec LIMIT 60",
        (tr["v"], track_id, group, t0, t1, tr["v"]))
    steps = []
    for r in rows:
        sim = float(r["sim"])
        app = float(r["app"]) if r["app"] is not None else None
        score = sim * 0.7 + (app if app is not None else sim) * 0.3
        if sim < s.JOURNEY_MIN_SIM:
            continue
        # cannot be on two different cameras at the same time
        if r["camera_id"] != tr["camera_id"] and r["t_start"] < tr["t_end"] and r["t_end"] > tr["t_start"]:
            continue
        steps.append({"track_id": r["id"], "camera_id": r["camera_id"], "cls": r["cls"],
                      "t_start": to_local(r["t_start"]).isoformat(), "t_end": to_local(r["t_end"]).isoformat(),
                      "sim": round(sim, 3), "appearance": round(app, 3) if app is not None else None,
                      "score": round(score, 3), "thumb_key": (r["crop_keys"] or [None])[0], "level": "candidate",
                      "why": f"same look (sim {sim:.2f}" + (f", colours {app:.2f})" if app is not None else ")")})
    steps.sort(key=lambda x: -x["score"])
    steps = steps[:limit]
    anchor = {"track_id": tr["id"], "camera_id": tr["camera_id"], "cls": tr["cls"],
              "t_start": to_local(tr["t_start"]).isoformat(), "t_end": to_local(tr["t_end"]).isoformat(),
              "sim": 1.0, "score": 1.0, "thumb_key": (tr["crop_keys"] or [None])[0], "level": "confirmed",
              "why": "the sighting you picked", "anchor": True}
    timeline = sorted([anchor, *steps], key=lambda x: x["t_start"])
    cams = []
    for st in timeline:
        if not cams or cams[-1] != st["camera_id"]:
            cams.append(st["camera_id"])
    return {"track_id": track_id, "steps": timeline, "cameras": cams,
            "summary": " → ".join(cams), "note": None if steps else "no similar sightings found"}


def with_urls(items: list[dict], token: str | None) -> list[dict]:
    for h in items:
        h["thumb_url"] = storage.url(h.pop("thumb_key", None), token)
    return items
