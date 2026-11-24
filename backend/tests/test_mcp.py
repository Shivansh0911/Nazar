"""MCP both ways: the hub (Nazar as a client of a real stdio server) and Nazar's own MCP server."""
import asyncio
from pathlib import Path

import pytest

from nazar.agentic import hub as H

TOY = str(Path(__file__).with_name("toy_mcp_server.py"))


def test_expand_fills_variables_and_reports_missing():
    missing: list[str] = []
    out = H.expand({"env": {"A": "${HAVE}", "B": "x-${NOPE}"}, "args": ["--k=${HAVE}"]}, {"HAVE": "1"}, missing)
    assert out == {"env": {"A": "1", "B": "x-"}, "args": ["--k=1"]} and missing == ["NOPE"]


def test_tool_names_fit_the_function_name_rules():
    n = H.tool_fn_name("my server.v2", "do/thing" + "x" * 80)
    assert n.startswith("mcp__my_server_v2__do_thing") and len(n) <= 64


@pytest.fixture(scope="module")
def hub():
    h = H.Hub({"toy": {"command": "python", "args": [TOY], "description": "test tools"},
               "off": {"command": "python", "args": [TOY], "enabled": False},
               "nokey": {"command": "python", "args": [TOY], "env": {"K": "${NAZAR_TEST_VAR_THAT_IS_NOT_SET}"}},
               "broken": {"command": "nazar-no-such-binary-xyz"}}, connect_timeout=40).start()
    yield h
    h.close()


def test_hub_connects_lists_and_calls(hub):
    st = {s["name"]: s for s in hub.status()}
    assert st["toy"]["state"] == "connected", st["toy"]
    assert st["off"]["state"] == "disabled"
    assert st["nokey"]["state"] == "needs_config" and st["nokey"]["missing"] == ["NAZAR_TEST_VAR_THAT_IS_NOT_SET"]
    assert st["broken"]["state"] == "error" and st["broken"]["error"]
    tools = {t["name"]: t for t in hub.function_tools()}
    assert set(tools) == {"mcp__toy__echo", "mcp__toy__post_message"}
    assert tools["mcp__toy__echo"]["strict"] is False and tools["mcp__toy__echo"]["parameters"]["type"] == "object"
    assert "approval" in tools["mcp__toy__post_message"]["description"]
    assert hub.call("mcp__toy__echo", {"text": "namaste"}) == {"text": "echo:namaste"}
    assert "error" in hub.call("mcp__toy__nope", {})


def test_only_tools_marked_read_only_run_without_approval(hub):
    assert hub.read_only("mcp__toy__echo") is True
    assert hub.read_only("mcp__toy__post_message") is False  # no readOnlyHint -> the owner decides
    assert hub.read_only("mcp__toy__unknown") is False
    hub.servers["toy"].cfg["auto_approve"] = ["post_message"]
    try:
        assert hub.read_only("mcp__toy__post_message") is True  # the owner's config may allow it
    finally:
        hub.servers["toy"].cfg.pop("auto_approve")


def test_nazar_mcp_server_lists_its_tools_with_honest_annotations():
    from mcp import Client

    from nazar.agentic import server

    async def go():
        async with Client(server.app) as c:
            return (await c.list_tools()).tools

    tools = {t.name: t for t in asyncio.run(go())}
    assert {"list_cameras", "count", "search_footage", "security_events", "journey", "analytics_sql", "track_image",
            "ask_nazar", "investigate", "draft_watch_rule", "incident_report"} <= set(tools)
    assert tools["count"].annotations.read_only_hint is True
    for name in ("draft_watch_rule", "incident_report", "investigate"):  # these create something: never auto-approved
        assert tools[name].annotations.read_only_hint is False
    assert set(tools["count"].input_schema["required"]) == {"time_from", "time_to"}
