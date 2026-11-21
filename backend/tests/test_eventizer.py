from conftest import make_path

from nazar.core.eventizer import eventize

ZONE = {"name": "counter", "label": "Counter", "polygon": [[0.4, 0.4], [0.8, 0.4], [0.8, 0.9], [0.4, 0.9]]}
GATE = {"name": "gate", "label": "Gate", "polygon": [[0.0, 0.4], [0.2, 0.4], [0.2, 0.9], [0.0, 0.9]]}


def types(events):
    return [(e.type, e.zone) for e in events]


def test_enter_and_exit():
    pts = [(0.12 + i * 0.05, 0.6) for i in range(20)]  # walks left->right through counter (x 0.4..0.8)
    ev, zp = eventize(make_path(pts), "person", [ZONE])
    assert types(ev) == [("enter", "counter"), ("exit", "counter")]
    assert zp == ["counter"]
    # enter at the first inside point (x=0.42 -> index 6), exit at the first outside point (x=0.82 -> index 14)
    t0 = 1_700_000_000_000
    assert ev[0].t_ms == t0 + 6 * 200
    assert ev[1].t_ms == t0 + 14 * 200


def test_track_ends_inside_no_exit():
    pts = [(0.1 + i * 0.05, 0.6) for i in range(12)]  # ends at x=0.65, inside
    ev, _ = eventize(make_path(pts), "person", [ZONE])
    assert types(ev) == [("enter", "counter")]


def test_boundary_jitter_does_not_flap():
    # feet alternate around the zone edge x=0.4: single-point excursions must not create events
    xs = [0.3, 0.3, 0.41, 0.39, 0.41, 0.39, 0.41, 0.39, 0.3, 0.3]
    ev, zp = eventize(make_path([(x, 0.6) for x in xs]), "person", [ZONE])
    assert ev == [] and zp == []
    # once inside, single outside jitter points don't produce exit/enter pairs
    xs = [0.3, 0.3, 0.5, 0.5, 0.39, 0.5, 0.39, 0.5, 0.5, 0.39, 0.5, 0.3, 0.3]
    ev, _ = eventize(make_path([(x, 0.6) for x in xs]), "person", [ZONE])
    assert types(ev) == [("enter", "counter"), ("exit", "counter")]


def test_dwell_event_completed_and_ongoing():
    inside = [(0.5, 0.6)] * 60  # 60 points * 200 ms = 12 s inside
    pts = [(0.1, 0.6)] * 3 + inside + [(0.1, 0.6)] * 3
    ev, _ = eventize(make_path(pts), "person", [ZONE])
    assert types(ev) == [("enter", "counter"), ("dwell", "counter"), ("exit", "counter")]
    dwell = ev[1]
    assert 11.5 <= dwell.meta["seconds"] <= 12.5 and dwell.meta["ongoing"] is False
    ev2, _ = eventize(make_path([(0.1, 0.6)] * 3 + inside), "person", [ZONE])
    assert [e.type for e in ev2] == ["enter", "dwell"]
    assert ev2[1].meta["ongoing"] is True


def test_short_stay_no_dwell():
    pts = [(0.1, 0.6)] * 3 + [(0.5, 0.6)] * 20 + [(0.1, 0.6)] * 3  # 4 s
    ev, _ = eventize(make_path(pts), "person", [ZONE])
    assert "dwell" not in [e.type for e in ev]


def test_multiple_zones_zone_path_order():
    pts = [(0.1, 0.6)] * 5 + [(0.3, 0.6)] * 3 + [(0.6, 0.6)] * 5
    ev, zp = eventize(make_path(pts), "person", [ZONE, GATE])
    assert zp == ["gate", "counter"]
    assert types(ev) == [("enter", "gate"), ("exit", "gate"), ("enter", "counter")]


def test_feet_anchor_used_for_person():
    # box center is inside but feet are below the zone -> not inside
    path = [[1_700_000_000_000 + i * 200, 0.5, 0.5, 0.55, 0.95, 0.9] for i in range(10)]
    ev, _ = eventize(path, "person", [ZONE])
    assert ev == []
    ev_obj, _ = eventize(path, "backpack", [ZONE])  # objects use the center (0.525, 0.725) -> inside
    assert [e.type for e in ev_obj] == ["enter"]


def test_empty_inputs():
    assert eventize([], "person", [ZONE]) == ([], [])
    assert eventize(make_path([(0.5, 0.6)] * 5), "person", []) == ([], [])
