"""Agent battery (acceptance G6): >= 25 questions through the streaming API. For every answer it checks structure,
re-runs the SQL behind every Confirmed number (count_events args from the stored plan, analytics SQL as nazar_ro),
checks the reply quotes the counted number, and records latency (first words, full) and cost.

    python scripts/eval_battery.py [--api http://localhost:8000] [--only 3,7]
Writes data/eval/battery.json (shown on the Insights page).
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from nazar.api import agent_tools  # noqa: E402
from nazar.api.analytics import run as run_sql  # noqa: E402
from nazar.core import db  # noqa: E402
from nazar.core.config import get_settings  # noqa: E402

DEVANAGARI = str.maketrans("०१२३४५६७८९", "0123456789")
Q = [
    # (question, expectation tag)
    ("Kal raat 10 baje ke baad shop counter pe kitne log aaye?", "count"),
    ("How many people came to the shop counter between 6 and 8 pm yesterday?", "count"),
    ("रात 2 बजे के बाद night stall पर कितने लोग आए?", "count"),
    ("Builders venue pe kitne log dikhe?", "count"),
    ("Lobby mein kitne log aaye?", "count"),
    ("Main road pe kitni motorcycles guzri?", "count"),
    ("Which camera was the busiest and at what hour?", "analysis"),
    ("Average time people spent on each camera?", "analysis"),
    ("Vehicles by type on the main road, per hour", "analysis"),
    ("Har camera pe kitne log 1 minute se zyada ruke?", "analysis"),
    ("Compare lobby people this morning vs yesterday evening", "compare"),
    ("Aaj subah lobby mein sabse zyada bheed kab thi?", "peak"),
    ("Show me a green backpack", "visual"),
    ("Laptop wala desk dikhao builders venue pe", "visual"),
    ("Show me a white car on the market street", "visual"),
    ("Show people carrying a bag in the lobby", "search"),
    ("Desk 14 se bag kisne uthaya?", "search"),
    ("Kuch ajeeb hua kal raat?", "security"),
    ("Any security events on the office desk camera?", "security"),
    ("Lobby mein log kahan sabse zyada ruke? Heatmap dikhao", "heatmap"),
    ("Abhi builders venue pe kya ho raha hai?", "look"),
    ("Jab bhi koi desk 14 se bag uthaye, mujhe batana", "rule"),
    ("Office desk ke bag wale incident ki report banao", "report"),
    ("Find this person's face in all cameras", "refuse"),
    ("kitne?", "clarify"),
    ("Night stall pe raat 9 baje ke baad kitne log aaye?", "count"),
    ("Market street pe kal shaam kitne log the?", "count"),
    # v3: the hackathon clip (camera "Builders venue")
    ("बिल्डर्स वेन्यू पर टीम डेस्क पर कितने लोग आए?", "count"),
    ("Builders venue pe sabse zyada log ek saath kab the?", "peak"),
    ("How long did people stay at the team desk on the Builders venue camera?", "analysis"),
    ("Show me someone with a green bag at the Builders venue", "visual"),
    ("Builders venue pe koi loitering ya ajeeb harkat hui?", "security"),
]


def ask(api: str, tok: str, q: str) -> tuple[dict | None, float | None, float, str | None]:
    t0 = time.perf_counter()
    first = None
    res = None
    err = None
    ev = None
    with httpx.stream("POST", f"{api}/api/ask/stream", json={"text": q}, headers={"X-Nazar-Token": tok}, timeout=240) as r:
        for line in r.iter_lines():
            if line.startswith("event: "):
                ev = line[7:]
            elif line.startswith("data: "):
                d = json.loads(line[6:])
                if ev == "text" and first is None:
                    first = time.perf_counter() - t0
                elif ev == "result":
                    res = d
                elif ev == "error":
                    err = str(d)
    return res, first, time.perf_counter() - t0, err


def check(tag: str, res: dict) -> list[str]:
    """Returns a list of problems (empty = pass)."""
    probs = []
    if not res.get("reply_text", "").strip():
        probs.append("empty reply")
    plan = db.fetch_one("SELECT plan FROM queries WHERE id=%s", (res["query_id"],))["plan"] if res.get("query_id") else []
    c = res.get("count")
    if c:
        calls = [p for p in plan if p["name"] == "count_events"]
        ok = False
        for p in calls:
            a = {k: v for k, v in p["args"].items() if v is not None}
            if agent_tools.count_events(a)["value"] == c["value"]:
                ok = True
        if calls and not ok:
            probs.append(f"count {c['value']} != SQL")
        if c.get("receipts_total") is not None and c["receipts_total"] != c["value"]:
            probs.append("receipts != count")
        nums = {int(n) for n in re.findall(r"\d+", res["reply_text"].translate(DEVANAGARI))}
        if c["value"] and c["value"] not in nums:  # a zero may be said as "koi nahi" / "no footage"
            probs.append(f"reply does not quote {c['value']}")
    for t in res.get("tables") or []:
        if t.get("sql"):
            again = run_sql(t["sql"])
            if again["row_count"] != t["row_count"]:
                probs.append("analytics rows differ on re-run")
    for cl in res.get("clips") or []:
        if cl["level"] not in ("confirmed", "probable", "candidate"):
            probs.append("bad level")
    lv = [cl["level"] for cl in res.get("clips") or []]
    order = {"confirmed": 0, "probable": 1, "candidate": 2}
    if lv != sorted(lv, key=lambda x: order[x]):
        probs.append("candidate ranked above stronger evidence")
    if tag == "count" and not c and not res.get("gaps"):
        probs.append("no count card")
    if tag in ("analysis",) and not res.get("tables"):
        probs.append("no analytics table")
    if tag in ("visual", "search") and not res.get("clips"):
        probs.append("no clips")
    if tag == "rule" and not res.get("rule"):
        probs.append("no rule draft")
    if tag == "report" and not res.get("report"):
        probs.append("no report")
    if tag == "heatmap" and not res.get("images"):
        probs.append("no heatmap")
    if tag == "refuse" and not re.search(r"face|chehr|चेहर|recogn", res["reply_text"], re.I):
        probs.append("did not refuse face search")
    if tag == "clarify" and not (res.get("clarify") or "?" in res["reply_text"]):
        probs.append("no clarifying question")
    return probs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--only")
    a = ap.parse_args()
    tok = httpx.post(f"{a.api}/api/auth", json={"passcode": get_settings().DEMO_PASSCODE}).json()["token"]
    sel = [int(x) for x in a.only.split(",")] if a.only else range(1, len(Q) + 1)
    rows = []
    for i in sel:
        q, tag = Q[i - 1]
        res, first, total, err = ask(a.api, tok, q)
        probs = [err] if err else (check(tag, res) if res else ["no result"])
        row = {"n": i, "q": q, "tag": tag, "ok": not probs, "problems": probs, "first_s": round(first, 2) if first else None,
               "total_s": round(total, 2), "cost_inr": res.get("cost_inr") if res else None, "model": res.get("model") if res else None,
               "reply": (res or {}).get("reply_text", "")[:200], "count": ((res or {}).get("count") or {}).get("value")}
        rows.append(row)
        print(f"{i:>2} {'PASS' if row['ok'] else 'FAIL'} {total:5.1f}s ₹{row['cost_inr']} {row['model']} | {q[:60]}"
              + (f"  <- {probs}" if probs else ""), flush=True)
    ok = sum(r["ok"] for r in rows)
    totals = [r["total_s"] for r in rows]
    firsts = [r["first_s"] for r in rows if r["first_s"]]
    costs = [r["cost_inr"] for r in rows if r["cost_inr"] is not None]

    def p(xs, q):
        xs = sorted(xs)
        return round(xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))], 2) if xs else None

    summary = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "passed": ok, "total": len(rows),
               "first_p50_s": p(firsts, 0.5), "first_p90_s": p(firsts, 0.9), "total_p50_s": p(totals, 0.5),
               "total_p90_s": p(totals, 0.9), "cost_p50_inr": p(costs, 0.5), "cost_p90_inr": p(costs, 0.9),
               "cost_mean_inr": round(statistics.mean(costs), 3) if costs else None, "rows": rows}
    out = get_settings().data_dir / "eval" / "battery.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n{ok}/{len(rows)} passed · first words p50 {summary['first_p50_s']} s · full p50 {summary['total_p50_s']} s "
          f"(p90 {summary['total_p90_s']} s) · cost p50 ₹{summary['cost_p50_inr']} (p90 ₹{summary['cost_p90_inr']})")
    return 0 if ok == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
