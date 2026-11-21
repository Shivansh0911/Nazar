"""Photo-taught objects (W4): compare every newly indexed track crop on a camera with the owner's photo (SigLIP 2,
local). A match >= the object's threshold becomes a Candidate sighting (sec_events type 'sighting') and, when a rule
for custom:<name> is active, an alert with snapshot + voice note."""
from __future__ import annotations

import logging
import threading

from psycopg.types.json import Jsonb

from ..core import db
from ..core.rules import Hit, RuleSpec
from ..core.timeutil import dt_to_ms

log = logging.getLogger("nazar.visual_watch")


def run_once() -> int:
    objs = db.fetch_all("SELECT id, camera_id, name, threshold, last_checked_id, prompt_emb::text AS emb FROM custom_objects "
                        "WHERE active AND prompt_type='visual' AND prompt_emb IS NOT NULL")
    n = 0
    for o in objs:
        rows = db.fetch_all(
            "SELECT id, t_start, t_end, 1 - (vis_emb <=> %s::halfvec) AS sim FROM tracks WHERE camera_id=%s "
            "AND t_end > now() - interval '15 minutes' AND vis_emb IS NOT NULL AND merged_into IS NULL "
            "ORDER BY id LIMIT 500", (o["emb"], o["camera_id"]))  # dedupe: sec_events + alerts are unique per track
        if not rows:
            continue
        from ..api.teach import slug

        cls = f"custom:{slug(o['name'])}"
        rules = [r for r in db.fetch_all("SELECT * FROM rules WHERE camera_id=%s AND active", (o["camera_id"],))
                 if (r["spec"] or {}).get("cls") == cls]
        for r in rows:
            if float(r["sim"]) < float(o["threshold"]):
                continue
            n += 1
            db.execute("INSERT INTO sec_events(camera_id, type, t_start, t_end, track_ids, level, reason, meta) VALUES "
                       "(%s,'sighting',%s,%s,%s,'candidate',%s,%s) ON CONFLICT DO NOTHING",
                       (o["camera_id"], r["t_start"], r["t_end"], [r["id"]], f"looks like your photo of '{o['name']}' "
                        f"(sim {float(r['sim']):.2f})", Jsonb({"object": o["name"], "sim": round(float(r["sim"]), 3)})))
            for rule in rules:
                if rule.get("activated_at") and r["t_end"] < rule["activated_at"]:
                    continue
                from .alerts import build

                build({**rule, "rs": RuleSpec.model_validate(rule["spec"])},
                      Hit(track_id=r["id"], t_ms=dt_to_ms(r["t_start"]), zone="anywhere", trigger="zone_enter",
                          extra={"sim": round(float(r["sim"]), 3), "photo_match": True}))
    return n


def loop(stop: threading.Event, interval: float = 5.0) -> None:
    while not stop.is_set():
        try:
            if run_once():
                log.info("photo-taught object sightings found")
        except Exception as e:
            log.warning("visual watch: %s", e)
        stop.wait(interval)
