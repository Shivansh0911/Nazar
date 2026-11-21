"""End-to-end live checks (acceptance G4 + G12): a rule fires on a camera playing as LIVE.

    python scripts/live_alert_test.py            # bag rule on office-desk (object_removed, ~2 min into the loop)
    python scripts/live_alert_test.py --teach    # teach "laptop" on builders-venue (YOLOE) + alert rule, live
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from nazar.core import db  # noqa: E402
from nazar.core.config import get_settings  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--api", default="http://localhost:8000")
ap.add_argument("--teach", action="store_true")
ap.add_argument("--timeout", type=float, default=300)
a = ap.parse_args()
H = {"X-Nazar-Token": httpx.post(f"{a.api}/api/auth", json={"passcode": get_settings().DEMO_PASSCODE}).json()["token"]}
c = httpx.Client(base_url=a.api, headers=H, timeout=180)

if a.teach:
    cam = "builders-venue"
    r = c.post("/api/custom-objects", json={"camera_id": cam, "name": "laptop", "alert": True}).json()
    print("taught:", r.get("message"))
    rule_id = r["rule_id"]
else:
    cam = "office-desk"
    r = c.post("/api/rules/compile", json={"text": "Jab bhi koi desk 14 se bag uthaye, mujhe batana", "camera_id": cam}).json()
    print("rule:", r.get("human"), "| replay hits:", (r.get("replay") or {}).get("count"))
    rule_id = r["rule_id"]
c.post(f"/api/rules/{rule_id}/activate")
before = db.fetch_val("SELECT COALESCE(max(id), 0) FROM alerts")
print("starting live edge:", c.post(f"/api/cameras/{cam}/start").json().get("status"))
t0 = time.time()
alert = None
while time.time() - t0 < a.timeout:
    alert = db.fetch_one("SELECT * FROM alerts WHERE id > %s AND rule_id=%s ORDER BY id LIMIT 1", (before, rule_id))
    if alert:
        break
    time.sleep(2)
c.post(f"/api/cameras/{cam}/stop")
c.post(f"/api/rules/{rule_id}/deactivate")
if not alert:
    print(f"FAIL: no alert within {a.timeout:.0f} s")
    sys.exit(1)
time.sleep(6)  # snapshot / voice note are attached right after the row is created
alert = db.fetch_one("SELECT * FROM alerts WHERE id=%s", (alert["id"],))
lag = (alert["created_at"] - alert["t"]).total_seconds()
print(f"PASS: alert #{alert['id']} after {time.time() - t0:.0f} s of live play; event->alert {lag:.1f} s")
print(f"  message: {alert['message']}")
print(f"  snapshot={bool(alert['snapshot_key'])} voice={bool(alert['audio_key'])} vision_confirmed={alert['vision_confirmed']}")
