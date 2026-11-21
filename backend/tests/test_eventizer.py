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


def _walk(points, t0=0, dt=200):
    # person boxes whose feet (anchor) follow the given points
    return [[t0 + i * dt, x - 0.02, y - 0.1, x + 0.02, y, 0.9] for i, (x, y) in enumerate(points)]


def test_line_crossing_in_and_out():
    from nazar.core.eventizer import eventize

    line = {"name": "door", "label": "Door", "type": "line", "polygon": [[0.2, 0.5], [0.8, 0.5]], "direction": "right"}
    # A->B points east; with y down, "right" of travel is below the line (y > 0.5) = inside
    down = _walk([(0.5, y) for y in (0.30, 0.35, 0.40, 0.45, 0.55, 0.60, 0.65, 0.70)])
    ev, zp = eventize(down, "person", [line])
    assert [e.type for e in ev] == ["cross_in"] and zp == ["door"]
    up = _walk([(0.5, y) for y in (0.70, 0.65, 0.60, 0.55, 0.45, 0.40, 0.35)])
    ev, _ = eventize(up, "person", [line])
    assert [e.type for e in ev] == ["cross_out"]


def test_line_crossing_outside_segment_and_jitter_ignored():
    from nazar.core.eventizer import eventize

    line = {"name": "door", "label": "Door", "type": "line", "polygon": [[0.2, 0.5], [0.4, 0.5]]}
    beside = _walk([(0.8, y) for y in (0.3, 0.4, 0.45, 0.55, 0.6, 0.7)])  # passes the extension, not the segment
    assert eventize(beside, "person", [line])[0] == []
    jitter = _walk([(0.3, y) for y in (0.45, 0.48, 0.52, 0.47, 0.49, 0.46)])  # one stray point across: hysteresis
    assert eventize(jitter, "person", [line])[0] == []
