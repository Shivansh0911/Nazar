"""Rules: compile (-> validate -> replay, saved inactive), activate, deactivate, delete, list."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..core import db
from ..core.timeutil import to_local
from .agent import compile_rule, hit_thumbs
from .auth import require_token
from .deps import camera_or_404, http_error

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])


class CompileIn(BaseModel):
    text: str
    camera_id: str
    language: str | None = None


def rule_out(r: dict, token: str | None) -> dict:
    replay = r["replay"] or {}
    return {"rule_id": r["id"], "ok": True, "camera_id": r["camera_id"], "camera_name": r.get("camera_name"),
            "text": r["text"], "human": r["human"], "spec": r["spec"], "replay": replay, "active": r["active"],
            "language": r["language"], "created_at": to_local(r["created_at"]).isoformat(),
            "activated_at": to_local(r["activated_at"]).isoformat() if r["activated_at"] else None,
            "last_alert": to_local(r["last_alert"]).isoformat() if r.get("last_alert") else None,
            "alert_count": int(r.get("alert_count") or 0), "hit_thumbs": hit_thumbs((replay.get("hits") or [])[:4], token)}


RULE_SQL = """SELECT r.*, c.name AS camera_name,
                     (SELECT max(t) FROM alerts a WHERE a.rule_id=r.id) AS last_alert,
                     (SELECT count(*) FROM alerts a WHERE a.rule_id=r.id) AS alert_count
                FROM rules r LEFT JOIN cameras c ON c.id=r.camera_id"""


@router.post("/rules/compile")
def compile_route(body: CompileIn, token: str = Depends(require_token)):
    camera_or_404(body.camera_id)
    if not body.text.strip():
        raise http_error(400, "empty rule text")
    return compile_rule(body.text.strip(), body.camera_id, body.language, token=token)


@router.get("/rules")
def list_rules(token: str = Depends(require_token)):
    return [rule_out(r, token) for r in db.fetch_all(RULE_SQL + " ORDER BY r.created_at DESC")]


def _set(rule_id: int, active: bool, token: str) -> dict:
    n = db.execute("UPDATE rules SET active=%s, activated_at=CASE WHEN %s THEN now() ELSE activated_at END WHERE id=%s",
                   (active, active, rule_id))
    if not n:
        raise http_error(404, "rule not found")
    return rule_out(db.fetch_one(RULE_SQL + " WHERE r.id=%s", (rule_id,)), token)


@router.post("/rules/{rule_id}/activate")
def activate(rule_id: int, token: str = Depends(require_token)):
    return _set(rule_id, True, token)


@router.post("/rules/{rule_id}/deactivate")
def deactivate(rule_id: int, token: str = Depends(require_token)):
    return _set(rule_id, False, token)


@router.delete("/rules/{rule_id}")
def delete(rule_id: int):
    if not db.execute("DELETE FROM rules WHERE id=%s", (rule_id,)):
        raise http_error(404, "rule not found")
    return {"ok": True}
