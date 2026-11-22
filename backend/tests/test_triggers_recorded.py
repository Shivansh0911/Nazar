"""Every rule trigger and security detector on RECORDED footage (the demo cameras in the dev database), using the same
pure evaluators the live engine uses. Nothing is written. Needs: python scripts/demo_setup.py (and the hackathon clip).
Running / fall have no demo clip with a real run or fall, so here they must stay silent on hundreds of calm tracks
(false-alarm check); their positive cases are covered by tests/test_security.py with synthetic paths."""
from datetime import datetime, timedelta, timezone

import pytest
import requests

from nazar.core import db
from nazar.core.replay import replay
from nazar.core.rules import RuleSpec
from nazar.core.timeutil import to_local
from nazar.worker import security as sec

pytestmark = pytest.mark.db


def _window(cam: str):
    w = db.fetch_one("SELECT min(t_start) AS a, max(t_end) AS b FROM tracks WHERE camera_id=%s", (cam,))
    if not w or not w["a"]:
        pytest.skip(f"no recorded footage for {cam} - run scripts/demo_setup.py")
    return w["a"] - timedelta(minutes=1), w["b"] + timedelta(minutes=1)


def _tracks(cam: str, cls: str | tuple = "person"):
    classes = [cls] if isinstance(cls, str) else list(cls)
    return db.fetch_all("SELECT id, camera_id, cls, path, active, t_start, t_end, crop_keys FROM tracks "
                        "WHERE camera_id=%s AND cls = ANY(%s) AND NOT active ORDER BY t_start", (cam, classes))


# --- rule triggers (replay = live evaluators on stored paths) ---------------------------------------------------
@pytest.mark.parametrize("trigger,extra", [("zone_enter", {}), ("zone_exit", {}), ("dwell_over", {"dwell_s": 5})])
def test_zone_triggers_fire_on_office_desk(trigger, extra):
    a, b = _window("office-desk")
    hits = replay(RuleSpec(camera_id="office-desk", trigger=trigger, cls="person", zone="desk_14", **extra), a, b)
    assert hits, f"{trigger} never fired on the office desk footage"
    assert all(a.timestamp() * 1000 <= h.t_ms <= b.timestamp() * 1000 for h in hits)


def test_object_removed_fires_with_the_person_who_took_it():
    a, b = _window("office-desk")
    hits = replay(RuleSpec(camera_id="office-desk", trigger="object_removed", cls="any_bag", zone="desk_14"), a, b)
    assert hits, "the ABODA bag pickup must replay as object_removed"
    assert any(h.actor_track_id for h in hits), "the taker (a person track) must be identified"


def test_count_over_fires_in_the_busy_lobby_and_not_at_a_huge_threshold():
    a, b = _window("lobby")
    assert replay(RuleSpec(camera_id="lobby", trigger="count_over", cls="person", zone="anywhere", count=5), a, b)
    assert not replay(RuleSpec(camera_id="lobby", trigger="count_over", cls="person", zone="anywhere", count=500), a, b)


def test_time_window_limits_replay_hits():
    a, b = _window("office-desk")
    all_hits = replay(RuleSpec(camera_id="office-desk", trigger="zone_enter", cls="person", zone="desk_14"), a, b)
    first = to_local(datetime.fromtimestamp(all_hits[0].t_ms / 1000, tz=timezone.utc))
    off = (first + timedelta(hours=3)).strftime("%H:%M")
    off2 = (first + timedelta(hours=4)).strftime("%H:%M")
    none = replay(RuleSpec(camera_id="office-desk", trigger="zone_enter", cls="person", zone="desk_14",
                           time_window={"from": off, "to": off2}), a, b)
    assert len(none) < len(all_hits)


# --- security detectors on recorded tracks ------------------------------------------------------------------------
def test_abandoned_bag_detected_on_aboda():
    persons = _tracks("office-desk")
    bags = _tracks("office-desk", tuple(sec.BAGS))
    assert bags, "the office desk clip has a bag track"
    assert any(sec.detect_abandoned(b, persons) is not None for b in bags)


def test_loitering_detected_at_the_venue():
    assert any(sec.detect_loitering(t["path"] or []) is not None for t in _tracks("builders-venue"))


def test_crowding_peak_in_the_lobby():
    per: dict[int, int] = {}
    for t in _tracks("lobby"):
        for s in {int(p[0] // 1000) for p in t["path"] or []}:
            per[s] = per.get(s, 0) + 1
    assert max(per.values()) > sec.CROWD_N


def test_after_hours_on_the_night_stall():
    starts = [to_local(t["t_start"]) for t in _tracks("night-market") if (t["t_end"] - t["t_start"]).total_seconds() >= 1.5]
    assert any(sec.in_window(s) for s in starts)
    day = [to_local(t["t_start"]) for t in _tracks("shop-counter")]
    assert not all(sec.in_window(s) for s in day)          # daytime footage is not "after hours"


def test_no_running_or_fall_false_alarms_on_calm_footage():
    calm = []
    for cam in ("office-desk", "shop-counter", "night-market", "builders-venue"):
        calm += _tracks(cam)
    assert len(calm) >= 50
    runs = sum(sec.detect_running(t["path"] or []) is not None for t in calm)
    falls = sum(sec.detect_fall(t["path"] or []) is not None for t in calm)
    assert runs <= len(calm) * 0.03 and falls <= len(calm) * 0.02, (runs, falls, len(calm))


# --- custom objects (open-vocabulary teach) - via the running API so YOLOE is loaded once ------------------------
def test_custom_object_replays_on_stored_frames():
    api = "http://localhost:8000"
    try:
        tok = requests.post(f"{api}/api/auth", json={"passcode": "nazar2026"}, timeout=5).json()["token"]
    except Exception:
        pytest.skip("API not running")
    h = {"X-Nazar-Token": tok}
    r = requests.post(f"{api}/api/custom-objects", json={"camera_id": "builders-venue", "name": "chair", "alert": False},
                      headers=h, timeout=300).json()
    try:
        assert r.get("ok") and r["replay"]["frames"] > 0
        assert r["replay"]["sightings"] >= 1, r
    finally:
        if r.get("object_id"):
            requests.delete(f"{api}/api/custom-objects/{r['object_id']}", headers=h, timeout=30)
