import numpy as np

from conftest import make_path
from nazar.worker.stitcher import find_merges

RED = list(np.r_[np.ones(38), np.zeros(38)] / np.sqrt(38))
BLUE = list(np.r_[np.zeros(38), np.ones(38)] / np.sqrt(38))


def tr(tid, t0, xs, app, cls="person", merged=None):
    return {"id": tid, "cls": cls, "path": make_path([(x, 0.6) for x in xs], t0=t0), "appearance": app,
            "merged_into": merged}


T0 = 1_700_000_000_000


def test_merges_broken_track():
    a = tr(1, T0, [0.1 + 0.01 * i for i in range(10)], RED)  # ends at x=0.19, t0+1800
    b = tr(2, T0 + 1800 + 800, [0.2 + 0.01 * i for i in range(10)], RED)  # starts 0.8 s later near the end
    assert find_merges([a, b]) == [(2, 1)]


def test_chain_merges_into_root():
    a = tr(1, T0, [0.1] * 10, RED)
    b = tr(2, T0 + 2600, [0.11] * 10, RED)
    c = tr(3, T0 + 5200, [0.12] * 10, RED)
    assert find_merges([c, a, b]) == [(2, 1), (3, 1)]


def test_no_merge_when_far_or_late_or_different():
    a = tr(1, T0, [0.1] * 10, RED)
    far = tr(2, T0 + 2400, [0.5] * 10, RED)
    late = tr(3, T0 + 1800 + 3000, [0.1] * 10, RED)
    diff = tr(4, T0 + 2400, [0.1] * 10, BLUE)
    car = tr(5, T0 + 2400, [0.1] * 10, RED, cls="car")
    assert find_merges([a, far]) == []
    assert find_merges([a, late]) == []
    assert find_merges([a, diff]) == []
    assert find_merges([a, car]) == []


def test_one_successor_per_track():
    a = tr(1, T0, [0.1] * 10, RED)
    b = tr(2, T0 + 2400, [0.1] * 10, RED)
    b2 = tr(3, T0 + 2500, [0.1] * 10, RED)
    merges = find_merges([a, b, b2])
    assert len(merges) == 1
