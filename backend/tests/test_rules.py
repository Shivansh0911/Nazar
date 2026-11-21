from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from conftest import make_path
from nazar.core.rules import RuleSpec, evaluate_count, evaluate_track, human_sentence, validate_zone
from nazar.core.timeutil import dt_to_ms, tz

ZONES = [
    {"name": "counter", "label": "Counter", "polygon": [[0.4, 0.4], [0.8, 0.4], [0.8, 0.9], [0.4, 0.9]]},
    {"name": "desk_14", "label": "Desk 14", "polygon": [[0.1, 0.1], [0.3, 0.1], [0.3, 0.3], [0.1, 0.3]]},
]


def local_ms(h, m=0, day_offset=0):
    d = datetime(2026, 11, 20, h, m, tzinfo=tz()) + timedelta(days=day_offset)
    return dt_to_ms(d)


def walker(t0, xs, y=0.6, tid=1, cls="person"):
    return {"id": tid, "cls": cls, "active": False, "path": make_path([(x, y) for x in xs], t0=t0)}


def test_spec_validation():
    RuleSpec(camera_id="c", trigger="zone_enter", cls="person", zone="counter")
    with pytest.raises(ValidationError):
        RuleSpec(camera_id="c", trigger="dwell_over", cls="person", zone="counter")
    with pytest.raises(ValidationError):
        RuleSpec(camera_id="c", trigger="dwell_over", cls="person", zone="counter", dwell_s=3)
    with pytest.raises(ValidationError):
        RuleSpec(camera_id="c", trigger="count_over", cls="person", zone="counter")
    with pytest.raises(ValidationError):
        RuleSpec(camera_id="c", trigger="object_removed", cls="person", zone="counter")
    with pytest.raises(ValidationError):
        RuleSpec(camera_id="c", trigger="zone_enter", cls="dragon", zone="counter")
    s = RuleSpec.model_validate({"camera_id": "c", "trigger": "zone_enter", "cls": "person", "zone": "gate",
                                 "time_window": {"from": "23:00", "to": "6:00"}})
    assert s.window_dict() == {"from": "23:00", "to": "06:00"}
    assert not validate_zone(s, ZONES)
    assert validate_zone(RuleSpec(camera_id="c", trigger="zone_enter", cls="person", zone="anywhere"), ZONES)


def test_zone_enter_and_exit_hits():
    tr = walker(local_ms(14), [0.1 + i * 0.05 for i in range(20)])
    enter = RuleSpec(camera_id="c", trigger="zone_enter", cls="person", zone="counter")
    exit_ = RuleSpec(camera_id="c", trigger="zone_exit", cls="person", zone="counter")
    assert len(evaluate_track(enter, tr, ZONES)) == 1
    assert len(evaluate_track(exit_, tr, ZONES)) == 1
    # class mismatch
    assert evaluate_track(RuleSpec(camera_id="c", trigger="zone_enter", cls="car", zone="counter"), tr, ZONES) == []


def test_anywhere_zone():
    tr = walker(local_ms(14), [0.5] * 6)
    s = RuleSpec(camera_id="c", trigger="zone_enter", cls="person", zone="anywhere")
    assert len(evaluate_track(s, tr, ZONES)) == 1


def test_dwell_over_live_ongoing():
    tr = walker(local_ms(14), [0.5] * 100)  # 20 s inside, track still active
    tr["active"] = True
    s = RuleSpec(camera_id="c", trigger="dwell_over", cls="person", zone="counter", dwell_s=15)
    hits = evaluate_track(s, tr, ZONES)
    assert len(hits) == 1
    assert hits[0].t_ms == tr["path"][0][0] + 15000
    assert evaluate_track(RuleSpec(camera_id="c", trigger="dwell_over", cls="person", zone="counter", dwell_s=30),
                          tr, ZONES) == []


def test_time_window_wraps_midnight():
    s = RuleSpec(camera_id="c", trigger="zone_enter", cls="person", zone="counter",
                 time_window={"from": "22:00", "to": "07:00"})
    xs = [0.1, 0.1, 0.5, 0.5, 0.5]
    assert len(evaluate_track(s, walker(local_ms(23, 30), xs), ZONES)) == 1
    assert len(evaluate_track(s, walker(local_ms(2, 15), xs), ZONES)) == 1
    assert evaluate_track(s, walker(local_ms(14), xs), ZONES) == []
    assert evaluate_track(s, walker(local_ms(7, 1), xs), ZONES) == []


def _bag_track(t0, still_s=15, then="vanish", tid=10):
    n = int(still_s * 5)
    path = [[t0 + i * 200, 0.18, 0.18, 0.22, 0.24, 0.8] for i in range(n)]
    if then == "leave":
        for k in range(1, 8):
            path.append([t0 + (n + k) * 200, 0.18 + 0.06 * k, 0.18, 0.22 + 0.06 * k, 0.24, 0.8])
    return {"id": tid, "cls": "backpack", "active": then == "active", "path": path}


def _person_near(t_ms, tid=20, x=0.2):
    return {"id": tid, "cls": "person",
            "path": [[t_ms + d, x - 0.03, 0.1, x + 0.03, 0.3, 0.9] for d in range(-2000, 2001, 200)]}


def test_object_removed_with_actor():
    t0 = local_ms(2, 40)
    bag = _bag_track(t0)
    s = RuleSpec(camera_id="c", trigger="object_removed", cls="any_bag", zone="desk_14")
    removal = bag["path"][-1][0]
    hits = evaluate_track(s, bag, ZONES, others_near=[_person_near(removal)])
    assert len(hits) == 1
    h = hits[0]
    assert h.actor_track_id == 20 and h.track_id == 20 and h.object_track_id == 10
    assert h.t_ms == removal


def test_object_removed_without_actor_alerts_on_object():
    bag = _bag_track(local_ms(2, 40))
    s = RuleSpec(camera_id="c", trigger="object_removed", cls="any_bag", zone="desk_14")
    far_person = _person_near(bag["path"][-1][0], x=0.9)
    hits = evaluate_track(s, bag, ZONES, others_near=[far_person])
    assert len(hits) == 1 and hits[0].actor_track_id is None and hits[0].track_id == 10


def test_object_removed_by_leaving_zone():
    bag = _bag_track(local_ms(2, 40), then="leave")
    s = RuleSpec(camera_id="c", trigger="object_removed", cls="backpack", zone="desk_14")
    hits = evaluate_track(s, bag, ZONES, others_near=[])
    assert len(hits) == 1


def test_object_removed_requires_stationary_and_end():
    s = RuleSpec(camera_id="c", trigger="object_removed", cls="any_bag", zone="desk_14")
    assert evaluate_track(s, _bag_track(local_ms(2), still_s=6), ZONES) == []  # not stationary long enough
    assert evaluate_track(s, _bag_track(local_ms(2), then="active"), ZONES) == []  # still there
    assert evaluate_track(s, dict(_bag_track(local_ms(2)), cls="person"), ZONES) == []  # wrong class


def test_count_over_and_cooldown():
    t0 = local_ms(15)
    s = RuleSpec(camera_id="c", trigger="count_over", cls="person", zone="counter", count=2)
    # three people inside together for 10 s, then again 30 s later (within cooldown), then 2 min later
    def group(start, ids):
        return [{"id": i, "cls": "person", "path": make_path([(0.5, 0.6)] * 50, t0=start)} for i in ids]
    tracks = group(t0, [1, 2, 3]) + group(t0 + 30_000, [4, 5, 6]) + group(t0 + 120_000, [7, 8, 9])
    hits = evaluate_count(s, tracks, ZONES)
    assert [h.t_ms for h in hits] == [t0 // 1000 * 1000, (t0 + 120_000) // 1000 * 1000]
    assert hits[0].extra["n"] == 3
    # only two people -> never over 2
    assert evaluate_count(s, group(t0, [1, 2]), ZONES) == []


def test_human_sentence_fallback():
    s = RuleSpec(camera_id="c", trigger="object_removed", cls="any_bag", zone="desk_14",
                 time_window={"from": "22:00", "to": "07:00"})
    txt = human_sentence(s, zone_label="Desk 14")
    assert "Desk 14" in txt and "22:00" in txt and "voice note" in txt
