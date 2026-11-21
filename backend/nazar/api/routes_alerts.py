"""Alerts list + acknowledge."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..core import db, storage
from ..core.timeutil import to_local
from .auth import require_token
from .deps import http_error

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])

ALERT_SQL = """SELECT a.*, r.human, r.camera_id AS rule_camera, c.name AS camera_name
                 FROM alerts a JOIN rules r ON r.id=a.rule_id LEFT JOIN cameras c ON c.id = COALESCE(a.camera_id, r.camera_id)"""


def alert_out(a: dict, token: str | None) -> dict:
    return {"id": a["id"], "rule_id": a["rule_id"], "track_id": a["track_id"],
            "camera_id": a["camera_id"] or a["rule_camera"], "camera_name": a.get("camera_name"),
            "t": to_local(a["t"]).isoformat(), "message": a["message"], "human": a["human"],
            "audio_url": storage.url(a["audio_key"], token), "snapshot_url": storage.url(a["snapshot_key"], token),
            "vision_confirmed": a["vision_confirmed"], "suppressed": a["vision_confirmed"] is False, "ack": a["ack"],
            "meta": a.get("meta") or {}, "created_at": to_local(a["created_at"]).isoformat()}


def get_alert(alert_id: int, token: str | None) -> dict | None:
    a = db.fetch_one(ALERT_SQL + " WHERE a.id=%s", (alert_id,))
    return alert_out(a, token) if a else None


@router.get("/alerts")
def list_alerts(limit: int = 50, token: str = Depends(require_token)):
    rows = db.fetch_all(ALERT_SQL + " ORDER BY a.created_at DESC LIMIT %s", (min(limit, 200),))
    return [alert_out(a, token) for a in rows]


@router.post("/alerts/{alert_id}/ack")
def ack(alert_id: int):
    if not db.execute("UPDATE alerts SET ack=true WHERE id=%s", (alert_id,)):
        raise http_error(404, "alert not found")
    return {"ok": True}
