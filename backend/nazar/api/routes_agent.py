"""Investigator API: start a run (SSE), list/read runs, approve or reject queued actions, list connected tools."""
from __future__ import annotations

import asyncio
import threading

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from ..agentic import hub as mcp_hub
from ..agentic import investigator
from ..core import db
from ..core.openai_client import get_ai
from . import agent
from .auth import require_token
from .deps import http_error
from .routes_ask import _sse

router = APIRouter(prefix="/api/agent", dependencies=[Depends(require_token)])


class InvestigateIn(BaseModel):
    goal: str | None = None
    camera_id: str | None = None
    alert_id: int | None = None


class DecideIn(BaseModel):
    approve: bool


@router.post("/investigate")
async def investigate_route(body: InvestigateIn, token: str = Depends(require_token)):
    """Server-sent events: run {run_id}, status, plan (the steps, re-sent on every change), tool (running/done/failed),
    action (queued for approval), text (the summary), result (the case file), error."""
    get_ai().client  # 503 before any work when no key is configured
    goal, camera_id, trigger = (body.goal or "").strip(), body.camera_id, "user"
    if body.alert_id is not None:
        try:
            goal, camera_id = await run_in_threadpool(investigator.alert_goal, body.alert_id)
        except ValueError:
            raise http_error(404, "alert not found")
        trigger = "alert"
    if not goal:
        raise http_error(400, "send {goal} or {alert_id}")
    if len(goal) > 2000:
        raise http_error(400, "goal is too long (2000 characters max)")
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()

    def push(kind, data):
        loop.call_soon_threadsafe(q.put_nowait, (kind, data))

    def work():
        try:
            res = investigator.investigate(goal, camera_id, token=token, trigger=trigger, alert_id=body.alert_id,
                                           on_event=push)
            push("result", res)
        except Exception as e:
            push("error", str(e)[:300])
        finally:
            push("end", None)

    threading.Thread(target=work, daemon=True).start()

    async def gen():
        yield _sse("status", "Reading the goal…")
        while True:
            kind, data = await q.get()
            if kind == "end":
                break
            yield _sse(kind, data)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/runs")
def runs(limit: int = 20):
    rows = db.fetch_all("SELECT r.*, (SELECT count(*) FROM agent_actions a WHERE a.run_id=r.id AND a.status='pending') "
                        "AS pending_actions FROM agent_runs r ORDER BY r.created_at DESC LIMIT %s", (max(1, min(limit, 100)),))
    return [investigator.run_out(r) for r in rows]


@router.get("/runs/{run_id}")
def run(run_id: int, token: str = Depends(require_token)):
    r = investigator.get_run(run_id, token)
    if not r:
        raise http_error(404, "run not found")
    return r


@router.post("/runs/{run_id}/actions/{action_id}")
def decide(run_id: int, action_id: int, body: DecideIn):
    """Approve (run it now) or reject one queued action."""
    try:
        return investigator.decide_action(run_id, action_id, body.approve)
    except LookupError:
        raise http_error(404, "no pending action with that id (already decided?)")


@router.get("/tools")
def tools():
    """Everything the investigator can use: Nazar's own tools and the connected MCP servers."""
    hub = mcp_hub.get_hub(wait=False)
    native = [{"name": t["name"], "description": t["description"]} for t in agent.TOOLS]
    native.append({"name": "activate_rule", "description": "Switch a drafted rule on (needs your approval)."})
    return {"native": native, "servers": hub.status(), "config": str(mcp_hub.config_path())}
