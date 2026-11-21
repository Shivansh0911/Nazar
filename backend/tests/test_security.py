"""Security heuristics on synthetic paths (5 Hz, normalized boxes)."""
from datetime import datetime

from nazar.worker import security as sec


def person(points, t0=0, h=0.3, w=0.1, dt=200):
    return [[t0 + i * dt, x - w / 2, y - h, x + w / 2, y, 0.9] for i, (x, y) in enumerate(points)]


def test_running_vs_walking():
    walk = person([(0.1 + i * 0.01, 0.8) for i in range(20)])  # 0.05/s per 0.3 bh -> ~0.17 bh/s
    run = person([(0.1 + i * 0.2, 0.8) for i in range(10)])  # 1.0 /s / 0.3 = 3.3 bh/s
    assert sec.detect_running(walk) is None
    assert sec.detect_running(run) is not None
    assert sec.detect_running(run, cls="car") is None


def test_fall_needs_upright_then_lying():
    upright = [[i * 200, 0.45, 0.4, 0.55, 0.8, 0.9] for i in range(5)]  # h/w = 4
    lying = [[1000 + i * 200, 0.35, 0.7, 0.65, 0.8, 0.9] for i in range(15)]  # w/h = 3, 3 s
    assert sec.detect_fall(upright + lying) is not None
    assert sec.detect_fall(lying) is None  # never seen upright (e.g. a person lying on a bench)


def test_loitering():
    stay = person([(0.5 + (i % 3) * 0.005, 0.8) for i in range(5 * 100)])  # 100 s in one spot
    passby = person([(0.1 + i * 0.002, 0.8) for i in range(5 * 100)])
    assert sec.detect_loitering(stay) is not None
    assert sec.detect_loitering(passby) is None


def test_abandoned_bag_only_when_alone():
    bag = {"cls": "backpack", "path": [[i * 200, 0.4, 0.6, 0.45, 0.66, 0.8] for i in range(5 * 60)]}  # 60 s still
    owner_leaves = {"cls": "person", "path": person([(0.43, 0.66)] * 25)}  # near the bag only the first 5 s
    owner_stays = {"cls": "person", "path": person([(0.43, 0.66)] * 300)}
    assert sec.detect_abandoned(bag, [owner_leaves]) is not None
    assert sec.detect_abandoned(bag, [owner_stays]) is None


def test_snatch_brief_contact_then_speed_away():
    victim = {"path": person([(0.5, 0.8)] * 30)}
    approach = [(0.2 + i * 0.03, 0.8) for i in range(10)]  # walks in to x~0.47 (touching)
    flee = [(0.5 + i * 0.25, 0.8) for i in range(1, 6)]
    thief = {"path": person(approach + flee)}
    assert sec.detect_snatch(thief, victim) is not None
    chat = {"path": person([(0.5, 0.8)] * 30)}  # standing together for 6 s: not a snatch
    assert sec.detect_snatch(chat, victim) is None


def test_after_hours_window_wraps_midnight():
    assert sec.in_window(datetime(2026, 11, 21, 23, 30))
    assert sec.in_window(datetime(2026, 11, 22, 2, 0))
    assert not sec.in_window(datetime(2026, 11, 22, 12, 0))
