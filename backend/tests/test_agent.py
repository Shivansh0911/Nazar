"""Agent plumbing with the fake client: tool loop, server-side assembly, levels can't be injected."""
import json

import pytest

import fakes
from nazar.api import agent
from nazar.core import openai_client as oc


@pytest.fixture(autouse=True)
def no_usage(monkeypatch):
    monkeypatch.setattr(oc.usage, "record", lambda *a, **k: None)
    monkeypatch.setattr(agent.db, "fetch_one", lambda *a, **k: {"crop_keys": []})


SEARCH_RESULT = {"results": [
    {"track_id": 11, "camera_id": "c", "cls": "person", "t_start": "2026-11-20T22:01:00+05:30",
     "t_end": "2026-11-20T22:01:09+05:30", "zones": ["counter"], "caption": "man in red shirt", "level": "candidate",
     "score": 0.3, "why": "sim 0.30"},
    {"track_id": 12, "camera_id": "c", "cls": "person", "t_start": "2026-11-20T22:05:00+05:30",
     "t_end": "2026-11-20T22:05:09+05:30", "zones": [], "caption": "man in red shirt with bag", "level": "probable",
     "score": 1.4, "why": "upper=red ✓, sim 0.41"},
], "matched": 2}


def test_assemble_takes_levels_from_server_and_ignores_unknown_ids():
    calls = [{"index": 0, "name": "search_tracks", "args": {}, "result": SEARCH_RESULT},
             {"index": 1, "name": "count_events", "args": {}, "result": {
                 "value": 7, "label": "people seen", "level": "confirmed", "series": [{"t": "x", "n": 7}]}}]
    # the model lists a candidate first and an id no tool returned
    ans = agent.AgentAnswer(reply_text="Shayad yeh hai", language="hinglish", show_track_ids=[11, 999, 12],
                            count_ref=1, rule_id=None, followups=[])
    out = agent.assemble(ans, calls, token=None)
    assert [c["track_id"] for c in out["clips"]] == [12, 11]  # probable before candidate; 999 dropped
    assert {c["track_id"]: c["level"] for c in out["clips"]} == {12: "probable", 11: "candidate"}
    assert out["count"]["value"] == 7 and out["count"]["level"] == "confirmed"


def test_model_cannot_inject_levels_via_answer():
    # AgentAnswer has no level field at all; extra keys from the model are ignored
    a = agent.AgentAnswer.model_validate({"reply_text": "x", "language": "en", "show_track_ids": [11], "count_ref": None,
                                          "rule_id": None, "followups": [], "levels": {"11": "confirmed"}})
    out = agent.assemble(a, [{"index": 0, "name": "search_tracks", "args": {}, "result": SEARCH_RESULT}], None)
    assert out["clips"][0]["level"] == "candidate"


def test_run_agent_tool_loop(monkeypatch):
    seq = [
        fakes.response([fakes.function_call("search_tracks", {"time_from": "2026-11-20T20:00", "time_to": "2026-11-21T06:00",
                                                              "upper_color": "red", "text": "man in red shirt"}, "c1")]),
        fakes.response([fakes.message("{}")], text=json.dumps({
            "reply_text": "Laal shirt wala shayad 10:05 pe aaya tha.", "language": "hinglish", "show_track_ids": [12],
            "count_ref": None, "rule_id": None, "followups": ["Usse pehle kaun aaya?"]})),
    ]
    fake = fakes.FakeClient(create_fn=lambda kw: seq.pop(0))
    monkeypatch.setattr(agent, "get_ai", lambda: oc.NazarAI(client=fake))
    monkeypatch.setattr(agent, "camera_context", lambda cam: "Current local time: 2026-11-21T10:00")
    executed = []
    monkeypatch.setattr(agent, "_exec_tool", lambda name, args, ref, token: executed.append((name, args)) or SEARCH_RESULT)
    ans, calls = agent.run_agent("Laal shirt wala kab aaya?", None, ref="t", token=None)
    assert ans.show_track_ids == [12] and ans.language == "hinglish"
    assert executed[0][0] == "search_tracks" and executed[0][1]["upper_color"] == "red"
    second = fake.responses.create_calls[1]["input"]
    outputs = [i for i in second if isinstance(i, dict) and i.get("type") == "function_call_output"]
    assert outputs and outputs[0]["call_id"] == "c1" and json.loads(outputs[0]["output"])["tool_call_index"] == 0
    first = fake.responses.create_calls[0]
    assert first["instructions"] == agent.AGENT_SYSTEM  # stable system prompt first (prompt caching)
    assert all(t["strict"] for t in first["tools"])
    assert first["text"]["format"]["strict"] is True


def test_tool_schemas_are_strict_valid():
    for t in agent.TOOLS:
        p = t["parameters"]
        assert p["additionalProperties"] is False
        assert set(p["required"]) == set(p["properties"])
