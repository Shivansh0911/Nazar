from nazar.core.riders import find_vehicle, on_vehicle, rider_share


def _path(box, n=10, t0=0, dt=200):
    return [[t0 + i * dt, *box] for i in range(n)]


BIKE = [0.40, 0.50, 0.60, 0.90]
RIDER = [0.43, 0.30, 0.57, 0.80]       # sits on the bike: overlaps it, centre above it
WALKER = [0.10, 0.40, 0.20, 0.90]      # beside the road, never on the bike


def test_on_vehicle():
    assert on_vehicle(RIDER, BIKE)
    assert not on_vehicle(WALKER, BIKE)
    # touching the edge only (centre outside the vehicle) is not riding
    assert not on_vehicle([0.55, 0.40, 0.75, 0.90], BIKE)


def test_rider_share_and_find():
    share, shared = rider_share(_path(RIDER), _path(BIKE))
    assert shared == 10 and share == 1.0
    assert find_vehicle(_path(RIDER), [{"id": 7, "path": _path(BIKE)}]) == 7
    assert find_vehicle(_path(WALKER), [{"id": 7, "path": _path(BIKE)}]) is None


def test_walks_past_a_parked_bike_is_not_a_rider():
    # 3 of 10 moments overlapping (40 % < 60 %) -> person on foot
    person = _path(WALKER, 7) + [[1400 + i * 200, *RIDER] for i in range(3)]
    assert find_vehicle(person, [{"id": 1, "path": _path(BIKE, 10)}]) is None


def test_no_shared_time_is_not_a_rider():
    assert find_vehicle(_path(RIDER, 10, t0=0), [{"id": 1, "path": _path(BIKE, 10, t0=60_000)}]) is None
