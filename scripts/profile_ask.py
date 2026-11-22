"""Where does answer time go? Runs common questions in-process with timers around every model round and tool call.

    python scripts/profile_ask.py [--out data/eval/latency_profile.json]
"""
import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")

from nazar.api import agent  # noqa: E402
from nazar.core.config import get_settings  # noqa: E402
from nazar.core.openai_client import get_ai  # noqa: E402

QUESTIONS = [
    "Builders venue pe kitne log dikhe?",
    "Kal raat 10 baje ke baad shop counter pe kitne log aaye?",
    "How many people came to the shop counter between 6 and 8 pm yesterday?",
    "Desk 14 se bag kisne uthaya?",
    "Which camera was busiest and at what hour?",
    "रात 2 बजे के बाद night stall पर कितने लोग आए?",
]

ap = argparse.ArgumentParser()
ap.add_argument("--out", default=str(Path(get_settings().data_dir) / "eval" / "latency_profile.json"))
ap.add_argument("--tag", default="current")
a = ap.parse_args()

ai = get_ai()
rounds: list[dict] = []
tools: list[dict] = []
_step, _exec = ai.agent_step_stream, agent._exec_tool


def step(*args, **kw):
    t = time.perf_counter()
    first = {}
    cb = kw.get("on_delta")
    if cb:
        def wrapped(d):
            first.setdefault("t", time.perf_counter() - t)
            cb(d)
        kw["on_delta"] = wrapped
    try:
        return _step(*args, **kw)
    finally:
        rounds.append({"model": kw.get("model"), "s": round(time.perf_counter() - t, 2),
                       "first_delta_s": round(first.get("t", 0), 2), "tools_offered": kw.get("tools") is not None})


def exec_tool(name, args, ref, token):
    t = time.perf_counter()
    try:
        return _exec(name, args, ref, token)
    finally:
        tools.append({"tool": name, "s": round(time.perf_counter() - t, 2)})


ai.agent_step_stream = step
agent._exec_tool = exec_tool
results = []
for q in QUESTIONS:
    rounds.clear()
    tools.clear()
    first = {}
    t0 = time.perf_counter()

    def on_event(kind, data, t0=t0):
        if kind == "text":
            first.setdefault("t", time.perf_counter() - t0)

    agent._cache.clear()
    ans = agent.ask(q, None, token=None, on_event=on_event)
    total = time.perf_counter() - t0
    r = {"q": q, "total_s": round(total, 2), "first_words_s": round(first.get("t", total), 2), "rounds": list(rounds),
         "tools": list(tools), "model": ans.get("model")}
    results.append(r)
    print(f"{r['total_s']:5.1f}s total | first words {r['first_words_s']:4.1f}s | "
          + " + ".join(f"{x['model'].split('-')[-1]} {x['s']}s" for x in r["rounds"]) + " | tools "
          + ", ".join(f"{x['tool']} {x['s']}s" for x in r["tools"]) + f" | {q[:50]}")

tot = [r["total_s"] for r in results]
fw = [r["first_words_s"] for r in results]
summary = {"tag": a.tag, "at": time.strftime("%Y-%m-%d %H:%M"), "n": len(results),
           "total_p50": statistics.median(tot), "first_words_p50": statistics.median(fw),
           "total_max": max(tot), "first_words_max": max(fw), "results": results}
print(f"\np50 total {summary['total_p50']:.1f}s, first words {summary['first_words_p50']:.1f}s")
out = Path(a.out)
out.parent.mkdir(parents=True, exist_ok=True)
try:
    prev = json.loads(out.read_text(encoding="utf-8"))
except Exception:
    prev = {}
prev[a.tag] = summary
out.write_text(json.dumps(prev, indent=1, ensure_ascii=False), encoding="utf-8")
