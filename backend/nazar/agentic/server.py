"""Nazar as an MCP *server*: any MCP client (Claude Desktop, Claude Code, Cursor, ChatGPT, another agent) can ask
the cameras.

    python -m nazar.agentic.server            # stdio (what desktop clients launch)
    python -m nazar.agentic.server --http     # Streamable HTTP on http://127.0.0.1:8020/mcp

Same rules as the app: counts are SQL facts with receipts, evidence levels are set by server code, every image that
leaves is the stored face-blurred one, and nothing here activates a rule or sends anything on its own.
The search / count / events tools cost no AI call; `ask_nazar`, `describe_moment` and `investigate` call OpenAI.
"""
from __future__ import annotations

import json
import sys
import uuid
from typing import Any

from mcp.server.mcpserver import Image, MCPServer
from mcp.types import ToolAnnotations

INSTRUCTIONS = """Nazar turns the owner's CCTV into something you can query. Start with list_cameras: it gives camera
ids, zones and the time span that has footage. Times are local ISO strings (Asia/Kolkata), e.g. 2026-11-22T21:00.
Every result carries an evidence level decided by Nazar: confirmed = tracker/database fact, probable = similarity
plus an independent check, candidate = similarity or heuristic only. Report levels honestly; never present a
candidate as a fact. Nazar does no face recognition: describe people by clothing and objects only. Images returned
by Nazar are already face-blurred."""

READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)

app = MCPServer("nazar", title="Nazar CCTV", instructions=INSTRUCTIONS, version="0.2.0")


def _ref() -> str:
    return f"mcp:{uuid.uuid4().hex[:10]}"


def _clean(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items() if not k.startswith("_")}
    if isinstance(v, list):
        return [_clean(x) for x in v]
    return v


def _run(name: str, args: dict) -> str:
    from ..api import agent

    try:
        res = agent._exec_tool(name, args, _ref(), None)
    except Exception as e:
        res = {"error": f"{type(e).__name__}: {str(e)[:300]}"}
    return json.dumps(_clean(agent.model_view(name, res)), default=str, ensure_ascii=False)[:30000]


@app.tool(annotations=READ)
def list_cameras() -> str:
    """Cameras with their zones and the time span that has footage. Call this first."""
    from ..api import agent

    return agent.camera_context(None)


@app.tool(annotations=READ)
def count(time_from: str, time_to: str, camera_id: str | None = None, cls: str = "person", event: str = "present",
          zone: str | None = None, bucket: str | None = None) -> str:
    """Count distinct tracked people/vehicles/objects (a confirmed SQL fact, with a time series).
    event: present (seen at all) | enter | exit | dwell | cross_in | cross_out (the last five need a zone).
    cls: person, car, motorcycle, bicycle, bus, truck, backpack, handbag, suitcase, laptop, cell phone, bottle, any_bag.
    bucket: 10s | 1min | 5min | 15min | hour | day."""
    return _run("count_events", {"time_from": time_from, "time_to": time_to, "camera_id": camera_id, "cls": cls,
                                 "event": event, "zone": zone, "bucket": bucket})


@app.tool(annotations=READ)
def peak_occupancy(camera_id: str, time_from: str, time_to: str, zone: str | None = None, cls: str = "person") -> str:
    """The most people/objects present at the same moment in a window, and when (confirmed)."""
    return _run("peak_occupancy", {"camera_id": camera_id, "time_from": time_from, "time_to": time_to, "zone": zone, "cls": cls})


@app.tool(annotations=READ)
def search_footage(text: str, time_from: str, time_to: str, camera_ids: list[str] | None = None, limit: int = 8,
                   ai_verify: bool = False) -> str:
    """Find moments by a short ENGLISH visual phrase ("red scooter", "person carrying a green backpack", "shutter
    open") in the local visual index. Hits are candidates; ai_verify=true spends one small AI call to check the top
    hits, which can raise them to probable."""
    return _run("visual_search", {"text": text, "time_from": time_from, "time_to": time_to, "camera_ids": camera_ids,
                                  "limit": limit, "verify": ai_verify})


@app.tool(annotations=READ)
def list_tracks(time_from: str, time_to: str, camera_ids: list[str] | None = None, cls: list[str] | None = None,
                zones: list[str] | None = None, limit: int = 12) -> str:
    """Who/what the tracker saw in a window (confirmed tracker facts), oldest first, optionally by class and zone."""
    return _run("search_tracks", {"time_from": time_from, "time_to": time_to, "camera_ids": camera_ids, "cls": cls,
                                  "zones": zones, "limit": limit})


@app.tool(annotations=READ)
def security_events(time_from: str, time_to: str, camera_id: str | None = None, types: list[str] | None = None) -> str:
    """Security events in a window: loitering, abandoned_object, object_removed, running, fall, crowding, after_hours,
    possible_snatch, wrong_way - each with its evidence level - plus unusually busy hours."""
    return _run("list_events", {"time_from": time_from, "time_to": time_to, "camera_id": camera_id, "types": types})


@app.tool(annotations=READ)
def camera_gaps(camera_id: str, time_from: str, time_to: str) -> str:
    """When a camera had no footage (offline) in a window. Check this before saying 'nothing happened'."""
    return _run("camera_gaps", {"camera_id": camera_id, "time_from": time_from, "time_to": time_to})


@app.tool(annotations=READ)
def journey(track_id: int, hours: float = 24) -> str:
    """Where else the same-looking person, bag or vehicle was seen (other cameras/times). Appearance only - clothes
    and objects, never faces - so every step is a candidate."""
    return _run("journey", {"track_id": track_id, "hours": hours})


@app.tool(annotations=READ)
def analytics_views() -> str:
    """The read-only SQL views (columns and meaning) that analytics_sql can query."""
    from ..api.analytics import describe_views

    return describe_views()


@app.tool(annotations=READ)
def analytics_sql(sql: str) -> str:
    """Run ONE read-only PostgreSQL SELECT over the views from analytics_views (validated, read-only role, 5 s
    timeout). Use timestamptz literals with +05:30. For people counts: v_tracks WHERE counted AND cls='person'."""
    return _run("analytics_query", {"sql": sql, "title": "MCP query"})


@app.tool(annotations=READ)
def compare_periods(a_from: str, a_to: str, b_from: str, b_to: str, camera_id: str | None = None, cls: str = "person",
                    event: str = "present", zone: str | None = None) -> str:
    """Compare a count between two periods (confirmed), e.g. today vs yesterday."""
    return _run("compare_periods", {"a_from": a_from, "a_to": a_to, "a_label": "A", "b_from": b_from, "b_to": b_to,
                                    "b_label": "B", "camera_id": camera_id, "cls": cls, "event": event, "zone": zone})


@app.tool(annotations=READ)
def track_image(track_id: int) -> Image:
    """The stored face-blurred crop of a track (a person, vehicle or object the tracker followed)."""
    from ..core import db, storage

    r = db.fetch_one("SELECT crop_keys FROM tracks WHERE id=%s", (track_id,))
    keys = (r or {}).get("crop_keys") or []
    if not keys or not storage.local_path(keys[0]).exists():
        raise ValueError("no stored crop for that track")
    return Image(data=storage.local_path(keys[0]).read_bytes(), format="jpeg")


@app.tool(annotations=READ)
def camera_frame(camera_id: str) -> Image:
    """The latest face-blurred frame of a camera (live if the camera is running, else the last stored keyframe)."""
    import time

    from ..core import db, storage

    snap = storage.local_path(f"live/{camera_id}.jpg")
    if snap.exists() and time.time() - snap.stat().st_mtime < 30:
        return Image(data=snap.read_bytes(), format="jpeg")
    kf = db.fetch_one("SELECT key FROM keyframes WHERE camera_id=%s ORDER BY t DESC LIMIT 1", (camera_id,))
    if not kf or not storage.local_path(kf["key"]).exists():
        raise ValueError("no frame stored for that camera")
    return Image(data=storage.local_path(kf["key"]).read_bytes(), format="jpeg")


@app.tool(annotations=READ)
def describe_moment(track_id: int | None = None, camera_id: str | None = None, time: str | None = None) -> str:
    """An AI description of what happens around a track, or around a time on a camera (from blurred frames; a
    candidate, not a fact). Costs one small AI call."""
    return _run("describe_clip", {"track_id": track_id, "camera_id": camera_id, "time": time})


@app.tool(annotations=READ)
def ask_nazar(question: str, camera_id: str | None = None) -> str:
    """Ask Nazar's own agent a question in Hindi, English or Hinglish and get its answer with the evidence summary.
    Use the specific tools when you can; this one costs an AI call."""
    from ..api import agent

    res = agent.ask(question, camera_id, token=None, input_kind="mcp", ref=_ref(), wait_audio=False)
    keep = {k: res.get(k) for k in ("reply_text", "language", "gaps", "tables", "sec_events", "followups", "cost_inr")}
    if res.get("count"):
        keep["count"] = {k: res["count"].get(k) for k in ("value", "label", "level", "series", "receipts_total")}
    keep["clips"] = [{k: c.get(k) for k in ("track_id", "camera_id", "cls", "t_start", "t_end", "level", "why")}
                     for c in res.get("clips", [])]
    return json.dumps(keep, default=str, ensure_ascii=False)


@app.tool(annotations=WRITE)
def draft_watch_rule(camera_id: str, text: str) -> str:
    """Turn the owner's words ("Jab bhi koi desk 14 se bag uthaye, mujhe batana") into a watch rule, replay it on past
    footage and save it INACTIVE. Only the owner can switch it on, in the Nazar app."""
    return _run("create_rule", {"camera_id": camera_id, "text": text})


@app.tool(annotations=WRITE)
def incident_report(title: str, track_ids: list[int] | None = None, alert_id: int | None = None,
                    sec_event_id: int | None = None, language: str = "en") -> str:
    """Create a police-ready incident PDF (blurred stills, timeline, SHA-256 hashes) for tracks, an alert or a
    security event. language: en | hi."""
    return _run("make_report", {"title": title, "track_ids": track_ids, "alert_id": alert_id,
                                "sec_event_id": sec_event_id, "language": language})


@app.tool(annotations=WRITE)
def investigate(goal: str, camera_id: str | None = None) -> str:
    """Hand Nazar's investigator a goal. It plans, runs its tools step by step and returns a case file: summary,
    findings with evidence levels, recommendations, and any actions waiting for the owner's approval in the app.
    Takes 20-90 s and several AI calls."""
    from . import investigator

    res = investigator.investigate(goal, camera_id, token=None, trigger="mcp", voice=False)
    keep = {k: res.get(k) for k in ("run_id", "reply_text", "findings", "recommendations", "confidence", "cost_inr")}
    keep["plan"] = [{k: s.get(k) for k in ("id", "title", "status", "finding")} for s in res.get("plan", [])]
    keep["pending_actions"] = [{k: a.get(k) for k in ("id", "label", "args", "reason")} for a in res.get("actions", [])]
    return json.dumps(keep, default=str, ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    import logging

    argv = sys.argv[1:] if argv is None else argv
    # stdio transport: stdout belongs to the protocol, so every log line goes to stderr
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if "--http" in argv:
        port = int(argv[argv.index("--port") + 1]) if "--port" in argv else 8020
        app.run("streamable-http", host="127.0.0.1", port=port)
    else:
        app.run("stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
