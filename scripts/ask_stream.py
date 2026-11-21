"""Ask through the streaming endpoint and print timings:  python scripts/ask_stream.py "question" [--camera id]"""
from __future__ import annotations

import argparse
import json
import sys
import time

import httpx

ap = argparse.ArgumentParser()
ap.add_argument("questions", nargs="+")
ap.add_argument("--camera")
ap.add_argument("--api", default="http://localhost:8000")
ap.add_argument("--passcode", default="nazar2026")
ap.add_argument("--json", action="store_true", help="print the full result JSON")
a = ap.parse_args()
tok = httpx.post(f"{a.api}/api/auth", json={"passcode": a.passcode}).json()["token"]
H = {"X-Nazar-Token": tok}
for q in a.questions:
    t0 = time.perf_counter()
    first = None
    text = ""
    res = None
    with httpx.stream("POST", f"{a.api}/api/ask/stream", json={"text": q, "camera_id": a.camera}, headers=H,
                      timeout=180) as r:
        ev = None
        for line in r.iter_lines():
            if line.startswith("event: "):
                ev = line[7:]
            elif line.startswith("data: "):
                d = json.loads(line[6:])
                if ev == "text":
                    first = first or time.perf_counter() - t0
                    text += d
                elif ev == "reset":
                    text = ""
                elif ev == "status":
                    print(f"  [{time.perf_counter() - t0:5.1f}s] {d}")
                elif ev == "result":
                    res = d
                elif ev == "error":
                    print("  ERROR", d)
    total = time.perf_counter() - t0
    print(f"Q: {q}\nA: {text}\n   first text {first or 0:.1f}s, done {total:.1f}s", end="")
    if res:
        c = res.get("count")
        print(f", model {res.get('model')}, cost Rs {res.get('cost_inr')}")
        if c:
            print(f"   count {c['value']} ({c['label']}), {len(c.get('series', []))} bars of {c.get('bucket')}, "
                  f"receipts {c.get('receipts_total')}")
        for t in res.get("tables", []):
            print(f"   table '{t['title']}' {t['row_count']} rows: {t['rows'][:3]}\n   sql: {t['sql'][:200]}")
        for ch in res.get("charts", []):
            print(f"   chart {ch['type']} '{ch['title']}' {len(ch['data'])} points")
        for cl in res.get("clips", [])[:6]:
            print(f"   clip {cl.get('kind')} {cl.get('camera_id')} {cl.get('cls')} {cl['level']} - {cl.get('why')}")
        for im in res.get("images", []):
            print(f"   image {im['kind']}: {im.get('caption')}")
        for n in res.get("notes", []):
            print(f"   note: {n['text']}")
        if res.get("journey"):
            print(f"   journey: {res['journey'].get('summary')} ({len(res['journey']['steps'])} steps)")
        if res.get("clarify"):
            print(f"   clarify: {res['clarify']}")
        if a.json:
            print(json.dumps(res, indent=1, ensure_ascii=False)[:4000])
    print()
sys.exit(0)
