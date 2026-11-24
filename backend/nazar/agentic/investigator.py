"""Investigator: think -> execute -> case file.

The Ask agent answers one question in one or two rounds. The investigator takes a GOAL ("find out what happened at the
counter last night and tell the guard group"), writes a plan, works through it with the same server-side tools plus
any connected MCP tools, revises the plan as evidence comes in, and returns a case file.

The hard rules still hold:
- facts, counts and evidence levels come from server tool results, never from the model. A finding's level is derived
  here from the tool calls the model cites for it (weakest link); a finding with no supporting call is "unverified".
- nothing that changes the world runs on the model's say-so: activating a rule and every external MCP tool that is
  not read-only are QUEUED as pending actions, and run only when the owner approves them.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Literal

from psycopg.types.json import Jsonb
from pydantic import BaseModel

from ..api import agent
from ..core import db
from ..core.config import get_settings
from ..core.levels import LEVEL_ORDER
from ..core.openai_client import detect_language, get_ai
from . import hub as mcp_hub

log = logging.getLogger("nazar.investigator")

PLAN_SYSTEM = """You plan an investigation of the owner's own CCTV footage (shops, homes, offices in India) for
Nazar. You do not run anything yet. Read the goal, the cameras, their data coverage and the available tools, then
write a short plan: 3 to 7 steps, each ONE concrete check that a tool can do (count, search, security events,
analysis, journey of a track, describe a moment, compare periods, external tool). Order them so early steps find the
leads later steps need. If the goal asks to tell/save/send/switch something, the last step is that action.
title: at most 8 words, in the owner's language and script. how: which tool and what window, one English sentence.
understanding: one sentence restating the goal in the owner's language. Never plan face recognition or identifying
people; appearance means clothes, bags and vehicles only."""

INVESTIGATION_RULES = """

INVESTIGATION MODE (this overrides the reply-format rules above).
You were given a goal, not a single question. Work like a careful security analyst:
1. Follow your plan (below). When you start a step call update_plan to mark it "doing"; when it is finished mark it
   done / failed / skipped with a one-sentence finding taken from tool results. Put update_plan in the SAME round as
   the next tools, so no round is spent only on bookkeeping.
2. Follow the evidence. When a result opens a lead (a track id, an odd hour, a security event), add a step with
   update_plan.add_steps and chase it: journey for a track, describe_clip for a moment, list_events around a time,
   compare_periods against the day before. Mark steps that became pointless as skipped.
3. If a tool fails or returns nothing, try ONE different approach (another tool, a wider window), record it, move on.
   Never repeat an identical call.
4. Tools whose names start with mcp__ are other systems the owner connected (chat, maps, files, web, memory, smart
   home). Use them when the goal needs them. Send them text only; never invent data; when you write something for
   other people, say how sure each fact is (confirmed by the tracker / possible match).
5. Tools marked "needs the owner's approval" and activate_rule are QUEUED, not run. Call each once with its final
   arguments, do not wait for or retry it, and say in the summary that it awaits approval. create_rule only drafts.
6. Stop when the goal is answered or the leads are exhausted, then return the final JSON:
   summary = 2-5 sentences in the owner's language and script: what happened, how sure, what awaits approval.
   findings = the key findings (at most 8). call_indexes = the tool_call_index values of the results that support the
   finding. The server sets the evidence level from them; a finding without call_indexes is shown as unverified.
   recommendations = up to 4 concrete next actions for the owner. show_track_ids, count_ref, charts, followups and
   confidence as described above.
Never state a number that is not in a tool result. Never describe faces or guess identity."""

UPDATE_PLAN = {
    "type": "function", "name": "update_plan", "strict": True,
    "description": "Record progress on the plan: mark steps doing/done/failed/skipped with a finding, and add new steps "
                   "when the evidence opens a lead.",
    "parameters": {"type": "object", "additionalProperties": False, "required": ["updates", "add_steps"], "properties": {
        "updates": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["step", "status", "finding"],
            "properties": {"step": {"type": "integer", "description": "step number"},
                           "status": {"type": "string", "enum": ["doing", "done", "failed", "skipped"]},
                           "finding": {"type": ["string", "null"], "description": "one sentence, from tool results"}}}},
        "add_steps": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["title", "how"],
            "properties": {"title": {"type": "string"}, "how": {"type": "string"}}}}}},
}
ACTIVATE_RULE = {
    "type": "function", "name": "activate_rule", "strict": True,
    "description": "Ask the owner to switch a drafted watch rule on [needs the owner's approval: it is queued, not run].",
    "parameters": {"type": "object", "additionalProperties": False, "required": ["rule_id", "reason"], "properties": {
        "rule_id": {"type": "integer"}, "reason": {"type": "string", "description": "one sentence for the owner"}}},
}

_CHARTS = agent.ANSWER_SCHEMA["properties"]["charts"]
FINAL_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["summary", "language", "findings", "recommendations", "show_track_ids", "count_ref", "charts",
                 "followups", "confidence"],
    "properties": {
        "summary": {"type": "string"},
        "language": {"type": "string", "enum": ["hi", "en", "hinglish"]},
        "findings": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["title", "detail", "call_indexes"],
            "properties": {"title": {"type": "string"}, "detail": {"type": "string"},
                           "call_indexes": {"type": "array", "items": {"type": "integer"}}}}},
        "recommendations": {"type": "array", "items": {"type": "string"}},
        "show_track_ids": {"type": "array", "items": {"type": "integer"}},
        "count_ref": {"type": ["integer", "null"]},
        "charts": _CHARTS,
        "followups": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "string", "enum": ["high", "low"]},
    },
}


class PlanStep(BaseModel):
    title: str
    how: str


class Plan(BaseModel):
    understanding: str
    language: Literal["hi", "en", "hinglish"]
    steps: list[PlanStep]


class Finding(BaseModel):
    title: str
    detail: str
    call_indexes: list[int] = []


class CaseFile(BaseModel):
    summary: str
    language: Literal["hi", "en", "hinglish"]
    findings: list[Finding] = []
    recommendations: list[str] = []
    show_track_ids: list[int] = []
    count_ref: int | None = None
    charts: list[dict] = []
    followups: list[str] = []
    confidence: Literal["high", "low"] = "high"


# ------------------------------------------------------------------------------------------------ evidence levels
FACT_TOOLS = {"count_events", "peak_occupancy", "camera_gaps", "analytics_query", "compare_periods", "heatmap",
              "create_rule"}  # create_rule: its replay hits are tracker facts
AI_TOOLS = {"journey", "describe_clip"}  # appearance similarity / an AI description: never more than a Candidate
NOT_EVIDENCE = {"make_report", "teach_object", "update_plan", "activate_rule"}


def _best(levels: list[str]) -> str | None:
    known = [lv for lv in levels if lv in LEVEL_ORDER]
    return min(known, key=LEVEL_ORDER.__getitem__) if known else None


def call_level(call: dict) -> str | None:
    """The evidence level one tool result can carry. Decided here, from server data only."""
    r, name = call.get("result"), call.get("name", "")
    if not isinstance(r, dict) or r.get("error") or r.get("queued") or name in NOT_EVIDENCE:
        return None
    if name.startswith(mcp_hub.PREFIX):
        return "external"
    if name in FACT_TOOLS:
        return "confirmed"
    if name in AI_TOOLS:
        return "candidate"
    if name == "look_now":
        return "candidate" if r.get("vision_answer") else "confirmed"
    if name == "search_tracks":
        return _best([x.get("level") for x in r.get("results", [])] + [h.get("level") for h in r.get("visual_hits") or []])
    if name == "visual_search":
        return _best([h.get("level") for h in r.get("hits", [])])
    if name == "list_events":
        return _best([e.get("level") for e in r.get("events", [])])
    return None


def finding_level(call_indexes: list[int], calls: list[dict]) -> str:
    """Weakest link over the cited tool results. No usable citation -> 'unverified' (the model's own reasoning)."""
    by = {c["index"]: c for c in calls}
    levels = [lv for lv in (call_level(by[i]) for i in call_indexes if i in by) if lv]
    internal = [lv for lv in levels if lv in LEVEL_ORDER]
    if internal:
        return max(internal, key=LEVEL_ORDER.__getitem__)
    return "external" if levels else "unverified"


# ------------------------------------------------------------------------------------------------ small helpers
def brief(name: str, r: Any) -> str:
    """One line about a tool result for the live trace (server-written, no model text)."""
    if not isinstance(r, dict):
        return "done"
    if r.get("error"):
        return "failed: " + str(r["error"])[:120]
    if r.get("queued"):
        return "waiting for your approval"
    if name == "count_events":
        return f"{r.get('value')} {r.get('label', '')}".strip()
    if name == "peak_occupancy":
        return f"peak {r.get('max')}" + (f" at {r['at'][11:16]}" if r.get("at") else "")
    if name == "search_tracks":
        return f"{r.get('matched', 0)} tracks" + (f", {len(r.get('visual_hits') or [])} visual hits" if r.get("visual_fallback") else "")
    if name == "visual_search":
        return f"{r.get('matched', 0)} hits, {r.get('probable', 0)} AI-verified"
    if name == "list_events":
        return f"{r.get('count', 0)} security events"
    if name == "analytics_query":
        return f"{r.get('row_count', 0)} rows"
    if name == "journey":
        return f"{len(r.get('steps') or [])} sightings"
    if name == "camera_gaps":
        return f"{r.get('offline_minutes', 0)} min without footage"
    if name == "compare_periods" and "a" in r:
        return f"{r['a']['value']} vs {r['b']['value']}"
    if name == "create_rule":
        return f"rule drafted, {r.get('replay_count') or 0} past hits" if r.get("ok") else "could not draft the rule"
    if name == "make_report":
        return "PDF ready" if r.get("pdf_url") else "done"
    if name.startswith(mcp_hub.PREFIX):
        return " ".join(str(r.get("text") or "done").split()).strip("{}[] ")[:120] or "done"
    return "done"


def _external_catalog(hub: mcp_hub.Hub) -> str:
    lines = []
    for s in hub.status():
        if s["state"] == "connected" and s["tools"]:
            names = ", ".join(t["name"] + ("*" if t["needs_approval"] else "") for t in s["tools"][:12])
            lines.append(f"- {s['name']}: {s.get('description') or 'external tools'} ({names})")
    if not lines:
        return "External tools: none connected."
    return "External tools the owner connected (* = runs only after the owner approves):\n" + "\n".join(lines)


def _plan_text(steps: list[dict]) -> str:
    return "Your plan:\n" + "\n".join(f"{s['id']}. {s['title']} - {s['how']}" for s in steps)


Emit = Callable[[str, Any], None]


class _Run:
    """State of one investigation."""

    def __init__(self, goal: str, camera_id: str | None, token: str | None, ref: str, hub: mcp_hub.Hub, emit: Emit):
        self.goal, self.camera_id, self.token, self.ref, self.hub, self.emit = goal, camera_id, token, ref, hub, emit
        self.run_id = 0
        self.steps: list[dict] = []
        self.calls: list[dict] = []
        self.actions: list[dict] = []
        self.trace: list[dict] = []
        self._lock = threading.Lock()

    # ---- plan ----
    def set_plan(self, plan: Plan) -> None:
        self.steps = [{"id": i + 1, "title": s.title.strip(), "how": s.how.strip(), "status": "pending", "finding": None,
                       "calls": []} for i, s in enumerate(plan.steps[:8])]
        self.emit("plan", self.steps)

    def update_plan(self, args: dict) -> dict:
        by = {s["id"]: s for s in self.steps}
        for u in args.get("updates") or []:
            s = by.get(int(u.get("step", 0)))
            if s and u.get("status") in ("doing", "done", "failed", "skipped"):
                s["status"] = u["status"]
                if u.get("finding"):
                    s["finding"] = str(u["finding"])[:400]
        for a in (args.get("add_steps") or [])[: max(0, 12 - len(self.steps))]:
            self.steps.append({"id": len(self.steps) + 1, "title": str(a.get("title", ""))[:120], "how": str(a.get("how", ""))[:300],
                               "status": "pending", "finding": None, "calls": [], "added": True})
        self.emit("plan", self.steps)
        return {"ok": True, "plan": [{"step": s["id"], "title": s["title"], "status": s["status"]} for s in self.steps]}

    def current_step(self) -> dict | None:
        return next((s for s in self.steps if s["status"] == "doing"), None) or \
            next((s for s in self.steps if s["status"] == "pending"), None)

    # ---- actions that need the owner ----
    def queue_action(self, tool: str, args: dict) -> dict:
        label = "Activate rule" if tool == "activate_rule" else self.hub.label(tool)
        reason = str(args.get("reason") or "")[:300] or None
        clean = {k: v for k, v in args.items() if not (tool == "activate_rule" and k == "reason")}
        row = db.fetch_one("INSERT INTO agent_actions(run_id, tool, label, args, reason) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                           (self.run_id, tool, label, Jsonb(clean), reason))
        action = {"id": row["id"], "tool": tool, "label": label, "args": clean, "reason": reason, "status": "pending",
                  "result": None}
        self.actions.append(action)
        self.emit("action", action)
        return {"queued": True, "action_id": action["id"],
                "note": "queued for the owner's approval - not run yet; do not call it again; mention it in the summary"}

    # ---- one tool ----
    def run_tool(self, name: str, args: dict) -> dict:
        if name == "activate_rule" or (name.startswith(mcp_hub.PREFIX) and not self.hub.read_only(name)):
            if name.startswith(mcp_hub.PREFIX) and not self.hub.has(name):
                return {"error": f"unknown tool {name}"}
            return self.queue_action(name, args)
        if name.startswith(mcp_hub.PREFIX):
            return self.hub.call(name, args)
        return agent._exec_tool(name, args, self.ref, self.token)


def _label(name: str, hub: mcp_hub.Hub) -> str:
    if name.startswith(mcp_hub.PREFIX):
        return hub.label(name)
    return agent.STATUS.get(name, name.replace("_", " ")).rstrip("…")


def _execute(run: _Run, model: str) -> CaseFile:
    s = get_settings()
    ai = get_ai()
    tools = agent.TOOLS + [UPDATE_PLAN, ACTIVATE_RULE] + run.hub.function_tools()
    instructions = agent._system() + INVESTIGATION_RULES
    text_fmt = {"format": {"type": "json_schema", "name": "case_file", "schema": FINAL_SCHEMA, "strict": True}}
    inp: list[dict] = [
        {"role": "developer", "content": agent.camera_context(run.camera_id) + "\n" + _external_catalog(run.hub)},
        {"role": "user", "content": run.goal},
        {"role": "developer", "content": _plan_text(run.steps)},
    ]
    seen: set[str] = set()
    max_steps = max(2, int(s.AGENT_MAX_STEPS))
    for rnd in range(max_steps + 1):
        last = rnd == max_steps
        if last:
            inp.append({"role": "developer", "content": "The step budget is used up. Write the final JSON now from what "
                                                         "you have; say what could not be checked."})
        resp, _ = ai.agent_step(model=model, input=inp, tools=None if last else tools, instructions=instructions,
                                text=text_fmt, kind="investigate", ref=run.ref, camera_id=run.camera_id,
                                reasoning=s.INVESTIGATOR_REASONING_EFFORT or None)
        fcalls = [o for o in (resp.output or []) if getattr(o, "type", None) == "function_call"]
        if not fcalls:
            raw = getattr(resp, "output_text", "") or ""
            try:
                return CaseFile.model_validate(json.loads(raw))
            except Exception:
                log.warning("investigator returned non-JSON final text; wrapping it")
                return CaseFile(summary=raw.strip() or "…", language=detect_language(run.goal), confidence="low")
        for o in resp.output or []:
            if getattr(o, "type", None) in ("function_call", "reasoning"):
                inp.append(agent._item_dict(o))
        # bookkeeping first, so the tools of this round are attached to the step the model just started
        work = []
        for fc in fcalls:
            try:
                args = json.loads(fc.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            if fc.name == "update_plan":
                inp.append({"type": "function_call_output", "call_id": fc.call_id,
                            "output": json.dumps(run.update_plan(args), ensure_ascii=False)})
            else:
                work.append((fc, args))
        step = run.current_step()

        def run_one(item):
            fc, args = item
            key = fc.name + json.dumps(args, sort_keys=True, default=str)
            if key in seen:
                return fc, args, {"error": "identical call already made in this investigation - use that result"}
            seen.add(key)
            try:
                return fc, args, run.run_tool(fc.name, args)
            except Exception as e:
                log.warning("tool %s failed: %s", fc.name, e)
                return fc, args, {"error": str(e)[:300]}

        base = len(run.calls)
        for k, (fc, args) in enumerate(work):
            run.emit("tool", {"index": base + k, "name": fc.name, "label": _label(fc.name, run.hub), "state": "running",
                              "step": step["id"] if step else None})
        if len(work) > 1:
            with ThreadPoolExecutor(max_workers=min(4, len(work))) as pool:
                outs = list(pool.map(run_one, work))
        else:
            outs = [run_one(w) for w in work]
        for fc, args, result in outs:
            idx = len(run.calls)
            run.calls.append({"index": idx, "name": fc.name, "args": args, "result": result})
            if step is not None:
                step["calls"].append(idx)
            failed = isinstance(result, dict) and bool(result.get("error"))
            ev = {"index": idx, "name": fc.name, "label": _label(fc.name, run.hub), "state": "failed" if failed else "done",
                  "step": step["id"] if step else None, "summary": brief(fc.name, result),
                  "external": fc.name.startswith(mcp_hub.PREFIX)}
            run.trace.append(ev)
            run.emit("tool", ev)
            inp.append({"type": "function_call_output", "call_id": fc.call_id,
                        "output": json.dumps({"tool_call_index": idx, **agent.model_view(fc.name, result)},
                                             default=str, ensure_ascii=False)[:20000]})
    raise RuntimeError("investigation did not finish")


# ------------------------------------------------------------------------------------------------ entry points
def investigate(goal: str, camera_id: str | None = None, *, token: str | None = None, trigger: str = "user",
                alert_id: int | None = None, on_event: Emit | None = None, hub: mcp_hub.Hub | None = None,
                voice: bool = True) -> dict:
    """Run one investigation to the end and return the case file (also stored in agent_runs).
    on_event(kind, data): run, status, plan, tool, action, text, error - for the live view (SSE)."""
    t0 = time.perf_counter()
    s = get_settings()
    goal = goal.strip()
    ref = f"inv:{uuid.uuid4().hex[:12]}"
    emit: Emit = on_event or (lambda kind, data: None)
    model = s.OPENAI_AGENT_MODEL
    hub = hub or mcp_hub.get_hub()
    run = _Run(goal, camera_id, token, ref, hub, emit)
    run.run_id = db.fetch_one("INSERT INTO agent_runs(ref, goal, camera_id, trigger, alert_id, model) VALUES "
                              "(%s,%s,%s,%s,%s,%s) RETURNING id", (ref, goal, camera_id, trigger, alert_id, model))["id"]
    emit("run", {"run_id": run.run_id})
    try:
        emit("status", "Planning the investigation…")
        ctx = agent.camera_context(camera_id) + "\n" + _external_catalog(hub) + "\nNazar tools: " + ", ".join(
            t["name"] for t in agent.TOOLS)
        plan, _ = get_ai().parse(model, [{"role": "developer", "content": ctx}, {"role": "user", "content": goal}], Plan,
                                 kind="plan", instructions=PLAN_SYSTEM, camera_id=camera_id, ref=ref,
                                 max_output_tokens=1500, reasoning=s.INVESTIGATOR_REASONING_EFFORT or None)
        run.set_plan(plan)
        db.execute("UPDATE agent_runs SET plan=%s WHERE id=%s", (Jsonb(run.steps), run.run_id))
        emit("status", "Working through the plan…")
        case = _execute(run, model)
    except Exception as e:
        log.exception("investigation %s failed", run.run_id)
        db.execute("UPDATE agent_runs SET status='error', error=%s, plan=%s, finished_at=now(), latency_ms=%s WHERE id=%s",
                   (str(e)[:500], Jsonb(run.steps), int((time.perf_counter() - t0) * 1000), run.run_id))
        raise
    for st in run.steps:  # whatever the model left open is closed honestly, not silently marked done
        if st["status"] in ("pending", "doing"):
            st["status"] = "done" if st["status"] == "doing" and st["calls"] else "skipped"
    emit("plan", run.steps)
    emit("text", case.summary)
    answer = agent.AgentAnswer(reply_text=case.summary, language=case.language, show_track_ids=case.show_track_ids,
                               count_ref=case.count_ref, followups=case.followups, charts=case.charts,
                               confidence=case.confidence)
    parts = agent.assemble(answer, run.calls, token)
    findings = [{"title": f.title, "detail": f.detail, "level": finding_level(f.call_indexes, run.calls),
                 "calls": [i for i in f.call_indexes if 0 <= i < len(run.calls)]} for f in case.findings[:8]]
    audio_url = None
    if voice:
        # voice on demand: a case file is read first; the summary is synthesized only when the owner presses play
        name = agent.defer_tts(ref, case.summary, case.language)
        audio_url = f"{s.API_BASE_URL.rstrip('/')}/api/ask/audio/{name}" + (f"?token={token}" if token else "")
    latency = int((time.perf_counter() - t0) * 1000)
    cost = float(db.fetch_val("SELECT COALESCE(sum(cost_usd),0) FROM usage WHERE ref=%s", (ref,)) or 0)
    used = sorted({c["name"].split("__")[1] for c in run.calls if c["name"].startswith(mcp_hub.PREFIX)})
    resp = {"query_id": 0, "run_id": run.run_id, "goal": goal, "transcript": None, "language": case.language,
            "reply_text": case.summary, "audio_url": audio_url, **parts, "followups": case.followups[:3],
            "clarify": None, "plan": run.steps, "findings": findings, "recommendations": case.recommendations[:4],
            "actions": run.actions, "trace": run.trace, "external_servers": used, "confidence": case.confidence,
            "tool_calls": len(run.calls), "cost_usd": round(cost, 6), "cost_inr": round(cost * s.USD_INR, 4),
            "latency_ms": latency, "model": model, "trigger": trigger}
    stored = {k: v for k, v in resp.items() if k != "audio_url"}
    plan_log = [{"index": c["index"], "name": c["name"], "args": c["args"]} for c in run.calls]
    # a queries row too: the receipts of a count (paged, reviewable) are served from it, like any Ask answer
    qid = db.fetch_one("INSERT INTO queries(camera_id, input_kind, transcript, language, plan, answer, latency_ms, "
                       "cost_usd, model) VALUES (%s,'investigate',%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                       (camera_id, goal, case.language, Jsonb(plan_log), Jsonb(stored), latency, cost, model))["id"]
    resp["query_id"] = stored["query_id"] = qid
    db.execute("UPDATE agent_runs SET status='done', plan=%s, result=%s, finished_at=now(), latency_ms=%s, cost_usd=%s, "
               "query_id=%s WHERE id=%s", (Jsonb(run.steps), Jsonb(stored), latency, cost, qid, run.run_id))
    return resp


def alert_goal(alert_id: int) -> tuple[str, str | None]:
    a = db.fetch_one("SELECT a.id, a.camera_id, a.track_id, a.t, a.message, a.meta, r.language FROM alerts a "
                     "LEFT JOIN rules r ON r.id=a.rule_id WHERE a.id=%s", (alert_id,))
    if not a:
        raise ValueError("alert not found")
    from ..core.timeutil import to_local

    meta = a.get("meta") or {}
    extra = "".join(f" {k.replace('_', ' ')} {meta[k]}." for k in ("actor_track_id", "object_track_id") if meta.get(k))
    goal = (f"Alert #{a['id']} fired on camera {a['camera_id']} at {to_local(a['t']).isoformat(timespec='seconds')}: "
            f"\"{a['message']}\" (track {a['track_id']}).{extra} Investigate it: what happened just before and after, "
            f"where else the same-looking person or object was seen, whether similar events happened in the last 24 "
            f"hours, and prepare an incident report if it looks real. Reply in this language: {a.get('language') or 'en'}.")
    return goal, a["camera_id"]


def decide_action(run_id: int, action_id: int, approve: bool, hub: mcp_hub.Hub | None = None) -> dict:
    """The owner's decision on a queued action. Claimed atomically, so a double tap cannot run it twice."""
    new = "running" if approve else "rejected"
    row = db.fetch_one("UPDATE agent_actions SET status=%s, decided_at=now() WHERE id=%s AND run_id=%s AND "
                       "status='pending' RETURNING id, tool, label, args, reason", (new, action_id, run_id))
    if not row:
        raise LookupError("no pending action with that id")
    result: dict | None = None
    status = "rejected"
    if approve:
        try:
            if row["tool"] == "activate_rule":
                n = db.execute("UPDATE rules SET active=true, activated_at=now() WHERE id=%s", (int(row["args"]["rule_id"]),))
                result = {"ok": bool(n), **({} if n else {"error": "rule not found"})}
            else:
                result = (hub or mcp_hub.get_hub()).call(row["tool"], row["args"])
        except Exception as e:
            result = {"error": str(e)[:300]}
        status = "failed" if result.get("error") else "done"
        db.execute("UPDATE agent_actions SET status=%s, result=%s WHERE id=%s", (status, Jsonb(result), action_id))
    return {"id": action_id, "tool": row["tool"], "label": row["label"], "args": row["args"], "reason": row["reason"],
            "status": status, "result": result}


def run_out(r: dict) -> dict:
    from ..core.timeutil import to_local

    return {"run_id": r["id"], "goal": r["goal"], "camera_id": r["camera_id"], "trigger": r["trigger"],
            "alert_id": r["alert_id"], "status": r["status"], "error": r["error"],
            "created_at": to_local(r["created_at"]).isoformat(), "latency_ms": r["latency_ms"],
            "cost_inr": round(float(r["cost_usd"] or 0) * get_settings().USD_INR, 4),
            "steps": len(r["plan"] or []), "pending_actions": int(r.get("pending_actions") or 0)}


def get_run(run_id: int, token: str | None = None) -> dict | None:
    r = db.fetch_one("SELECT * FROM agent_runs WHERE id=%s", (run_id,))
    if not r:
        return None
    actions = db.fetch_all("SELECT id, tool, label, args, reason, status, result FROM agent_actions WHERE run_id=%s "
                           "ORDER BY id", (run_id,))
    out = {**run_out({**r, "pending_actions": sum(1 for a in actions if a["status"] == "pending")}), "plan": r["plan"],
           "result": None}
    if r["result"]:
        out["result"] = {**r["result"], "actions": actions}
    return out
