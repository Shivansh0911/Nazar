"""The investigator with the fake client: plan -> tools -> approvals queued -> case file with server-set levels."""
import json

import pytest

import fakes
from nazar.agentic import investigator as inv
from nazar.api import agent
from nazar.core import openai_client as oc


class FakeDB:
    def __init__(self):
        self.sql: list[tuple] = []
        self.pending = {7: {"id": 7, "tool": "mcp__chat__post_message", "label": "chat · post_message",
                            "args": {"channel": "guards", "text": "hi"}, "reason": None}}

    def fetch_one(self, sql, params=None):
        self.sql.append((sql, params))
        if "INSERT INTO agent_runs" in sql:
            return {"id": 41}
        if "INSERT INTO agent_actions" in sql:
            return {"id": 7}
        if "INSERT INTO queries" in sql:
            return {"id": 900}
        if "UPDATE agent_actions" in sql and "RETURNING" in sql:
            return self.pending.pop(params[1], None)
        return {"crop_keys": []}

    def fetch_all(self, sql, params=None):
        return []

    def fetch_val(self, sql, params=None):
        return 0.0123

    def execute(self, sql, params=None):
        self.sql.append((sql, params))
        return 1


class FakeHub:
    def __init__(self):
        self.called: list[tuple] = []

    def function_tools(self):
        return [{"type": "function", "name": "mcp__chat__post_message", "description": "[chat] post", "strict": False,
                 "parameters": {"type": "object", "properties": {}}},
                {"type": "function", "name": "mcp__web__lookup", "description": "[web] lookup", "strict": False,
                 "parameters": {"type": "object", "properties": {}}}]

    def read_only(self, fn):
        return fn == "mcp__web__lookup"

    def has(self, fn):
        return fn.startswith("mcp__chat__") or fn.startswith("mcp__web__")

    def label(self, fn):
        return fn.replace("mcp__", "").replace("__", " · ")

    def call(self, fn, args):
        self.called.append((fn, args))
        return {"text": "ok from " + fn}

    def status(self):
        return [{"name": "chat", "state": "connected", "description": "team chat",
                 "tools": [{"name": "post_message", "needs_approval": True}]}]


COUNT = {"value": 9, "label": "people on foot seen", "level": "confirmed", "series": [], "bucket": "hour",
         "_receipts": [], "time_from": "2026-11-23T22:00:00+05:30", "time_to": "2026-11-24T06:00:00+05:30"}
VISUAL = {"hits": [{"kind": "track", "id": 5, "track_id": 5, "camera_id": "c", "cls": "person", "t": "x", "level": "candidate",
                    "why": "sim 0.2", "t_start": "x", "t_end": "y", "sim": 0.2}], "matched": 1, "probable": 0}
NIGHT = {"time_from": "2026-11-23T22:00", "time_to": "2026-11-24T06:00"}


@pytest.fixture
def world(monkeypatch):
    fdb, hub = FakeDB(), FakeHub()
    monkeypatch.setattr(oc.usage, "record", lambda *a, **k: None)
    monkeypatch.setattr(inv, "db", fdb)
    monkeypatch.setattr(agent, "db", fdb)
    monkeypatch.setattr(agent, "camera_context", lambda cam: "Current local time: 2026-11-24T10:00")
    monkeypatch.setattr(agent, "_system", lambda: "SYSTEM")
    executed = []

    def exec_tool(name, args, ref, token):
        executed.append((name, args))
        return {"count_events": COUNT, "visual_search": VISUAL}.get(name, {"ok": True})

    monkeypatch.setattr(agent, "_exec_tool", exec_tool)
    return fdb, hub, executed


def _final(**over):
    d = {"summary": "Raat ko 9 log dikhe; guard group ko message aapki approval ka intezaar kar raha hai.",
         "language": "hinglish",
         "findings": [{"title": "9 people at night", "detail": "tracker count", "call_indexes": [0]},
                      {"title": "Someone with a red bag", "detail": "visual match", "call_indexes": [0, 1]},
                      {"title": "Probably a delivery", "detail": "my guess", "call_indexes": []},
                      {"title": "Weather was rainy", "detail": "web", "call_indexes": [2]}],
         "recommendations": ["Gate pe rule lagao"], "show_track_ids": [], "count_ref": 0, "charts": [],
         "followups": ["Clips dikhao"], "confidence": "high"}
    return json.dumps({**d, **over})


def test_plan_execute_queue_and_case_file(world, monkeypatch):
    fdb, hub, executed = world
    rounds = [
        fakes.response([
            fakes.function_call("update_plan", {"updates": [{"step": 1, "status": "doing", "finding": None}], "add_steps": []}, "u1"),
            fakes.function_call("count_events", {**NIGHT, "event": "present"}, "c1"),
            fakes.function_call("visual_search", {**NIGHT, "text": "red bag"}, "c2"),
        ]),
        fakes.response([
            fakes.function_call("update_plan", {"updates": [{"step": 1, "status": "done", "finding": "9 people seen"},
                                                            {"step": 2, "status": "doing", "finding": None}],
                                                "add_steps": [{"title": "Check the weather", "how": "web lookup"}]}, "u2"),
            fakes.function_call("mcp__web__lookup", {"q": "weather"}, "c3"),
            fakes.function_call("mcp__chat__post_message", {"channel": "guards", "text": "9 people seen (confirmed)"}, "c4"),
            fakes.function_call("activate_rule", {"rule_id": 3, "reason": "night entries"}, "c5"),
            fakes.function_call("count_events", {**NIGHT, "event": "present"}, "c6"),
        ]),
        fakes.response([fakes.message("{}")], text=_final()),
    ]
    plan = {"understanding": "Raat ki jaanch", "language": "hinglish", "steps": [
        {"title": "Raat ke log gino", "how": "count_events 22:00-06:00"}, {"title": "Guards ko batao", "how": "chat post"}]}
    fake = fakes.FakeClient(parse_fn=lambda kw: plan, create_fn=lambda kw: rounds.pop(0))
    monkeypatch.setattr(inv, "get_ai", lambda: oc.NazarAI(client=fake))
    events = []
    res = inv.investigate("Kal raat kya hua? Guards ko batao.", None, token=None, hub=hub, voice=False,
                          on_event=lambda k, d: events.append((k, json.loads(json.dumps(d, default=str)))))

    # the plan came from the model, progress from update_plan; an added step is kept and unfinished steps are not "done"
    assert [s["title"] for s in res["plan"]] == ["Raat ke log gino", "Guards ko batao", "Check the weather"]
    assert res["plan"][0]["status"] == "done" and res["plan"][0]["finding"] == "9 people seen"
    assert res["plan"][0]["calls"] == [0, 1]
    assert res["plan"][2]["status"] == "skipped"
    # read-only tools ran; the two actions that change something were queued, NOT run
    assert [e[0] for e in executed] == ["count_events", "visual_search"]
    assert hub.called == [("mcp__web__lookup", {"q": "weather"})]
    assert [(a["tool"], a["status"]) for a in res["actions"]] == [("mcp__chat__post_message", "pending"),
                                                                  ("activate_rule", "pending")]
    assert res["actions"][1]["args"] == {"rule_id": 3} and res["actions"][1]["reason"] == "night entries"
    assert not any("UPDATE rules" in s for s, _ in fdb.sql)
    # an identical repeat call is refused instead of run again
    assert res["trace"][-1]["state"] == "failed" and "identical" in res["trace"][-1]["summary"]
    # evidence levels are set by the server from the cited calls (weakest link); no citation -> unverified
    assert [f["level"] for f in res["findings"]] == ["confirmed", "candidate", "unverified", "external"]
    assert res["count"]["value"] == 9 and res["count"]["level"] == "confirmed" and res["query_id"] == 900
    assert res["run_id"] == 41 and res["external_servers"] == ["chat", "web"] and res["cost_usd"] == 0.0123
    kinds = [k for k, _ in events]
    assert kinds[0] == "run" and "plan" in kinds and "action" in kinds and kinds[-1] == "text"
    # the model saw the queued note and its own plan; non-strict MCP tools sit next to the strict Nazar tools
    first, third = fake.responses.create_calls[0], fake.responses.create_calls[2]
    assert first["instructions"].startswith("SYSTEM") and "INVESTIGATION MODE" in first["instructions"]
    assert "Your plan:" in first["input"][2]["content"]
    names = {t["name"] for t in first["tools"]}
    assert {"update_plan", "activate_rule", "mcp__chat__post_message", "count_events"} <= names
    outs = {i["call_id"]: json.loads(i["output"]) for i in third["input"]
            if isinstance(i, dict) and i.get("type") == "function_call_output"}
    assert outs["c4"]["queued"] is True and outs["c1"]["tool_call_index"] == 0 and "_receipts" not in outs["c1"]


def test_step_budget_forces_a_final_answer(world, monkeypatch):
    fdb, hub, executed = world
    monkeypatch.setattr(inv.get_settings(), "AGENT_MAX_STEPS", 2)
    n = {"i": 0}

    def create(kw):
        n["i"] += 1
        if kw.get("tools"):
            args = {"camera_id": "c", "time_from": "2026-11-2%dT00:00" % n["i"], "time_to": "2026-11-24T00:00"}
            return fakes.response([fakes.function_call("camera_gaps", args, "g%d" % n["i"])])
        return fakes.response([fakes.message("{}")], text=_final(findings=[], count_ref=None))

    plan = {"understanding": "x", "language": "en", "steps": [{"title": "a", "how": "b"}]}
    fake = fakes.FakeClient(parse_fn=lambda kw: plan, create_fn=create)
    monkeypatch.setattr(inv, "get_ai", lambda: oc.NazarAI(client=fake))
    res = inv.investigate("loop forever", None, token=None, hub=hub, voice=False)
    assert len(fake.responses.create_calls) == 3 and "tools" not in fake.responses.create_calls[-1]
    assert res["tool_calls"] == 2 and res["findings"] == []


def test_levels_weakest_link_and_never_from_failed_calls():
    calls = [{"index": 0, "name": "count_events", "result": {"value": 1}},
             {"index": 1, "name": "visual_search", "result": {"hits": [{"level": "probable"}, {"level": "candidate"}]}},
             {"index": 2, "name": "journey", "result": {"steps": [1]}},
             {"index": 3, "name": "count_events", "result": {"error": "no footage"}},
             {"index": 4, "name": "mcp__maps__geocode", "result": {"text": "x"}},
             {"index": 5, "name": "mcp__chat__post", "result": {"queued": True}}]
    assert inv.finding_level([0], calls) == "confirmed"
    assert inv.finding_level([0, 1], calls) == "probable"
    assert inv.finding_level([0, 1, 2], calls) == "candidate"
    assert inv.finding_level([3], calls) == "unverified" and inv.finding_level([99], calls) == "unverified"
    assert inv.finding_level([4], calls) == "external" and inv.finding_level([5], calls) == "unverified"
    assert inv.finding_level([0, 4], calls) == "confirmed"  # an outside source neither upgrades nor downgrades a tracker fact


def test_an_action_runs_only_on_approval_and_only_once(world):
    fdb, hub, _ = world
    out = inv.decide_action(41, 7, True, hub=hub)
    assert out["status"] == "done" and hub.called == [("mcp__chat__post_message", {"channel": "guards", "text": "hi"})]
    with pytest.raises(LookupError):  # the second tap finds nothing pending
        inv.decide_action(41, 7, True, hub=hub)
    assert len(hub.called) == 1
    fdb.pending[8] = {"id": 8, "tool": "activate_rule", "label": "Activate rule", "args": {"rule_id": 3}, "reason": None}
    assert inv.decide_action(41, 8, False, hub=hub)["status"] == "rejected"
    assert not any("UPDATE rules" in s for s, _ in fdb.sql)
