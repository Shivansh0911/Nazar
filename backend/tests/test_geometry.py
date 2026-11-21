import numpy as np

from nazar.core.appearance import DIM, cosine, fingerprint
from nazar.core.geometry import anchor_point, box_distance, box_gap, iou, point_in_polygon

SQUARE = [[0.2, 0.2], [0.6, 0.2], [0.6, 0.6], [0.2, 0.6]]


def test_point_in_polygon_square():
    assert point_in_polygon(0.4, 0.4, SQUARE)
    assert not point_in_polygon(0.7, 0.4, SQUARE)
    assert not point_in_polygon(0.1, 0.1, SQUARE)


def test_point_in_polygon_concave():
    # L shape: the notch at top-right is outside
    L = [[0, 0], [0.5, 0], [0.5, 0.5], [1, 0.5], [1, 1], [0, 1]]
    assert point_in_polygon(0.25, 0.25, L)
    assert not point_in_polygon(0.75, 0.25, L)
    assert point_in_polygon(0.75, 0.75, L)


def test_degenerate_polygon():
    assert not point_in_polygon(0.5, 0.5, [[0, 0], [1, 1]])


def test_anchor_feet_vs_center():
    box = [0.1, 0.2, 0.3, 0.8]
    assert anchor_point("person", box) == (0.2, 0.8)
    assert anchor_point("car", box) == (0.2, 0.8)
    assert anchor_point("backpack", box) == (0.2, 0.5)


def test_iou_and_distance():
    a = [0, 0, 0.5, 0.5]
    assert iou(a, a) == 1.0
    assert iou(a, [0.6, 0.6, 1, 1]) == 0.0
    assert abs(iou(a, [0.25, 0, 0.75, 0.5]) - (0.125 / 0.375)) < 1e-9
    assert abs(box_distance(a, [0.5, 0, 1.0, 0.5]) - 0.5) < 1e-9
    assert box_gap(a, [0.6, 0, 1, 0.5]) > 0.09
    assert box_gap(a, [0.4, 0.4, 1, 1]) == 0.0


def _crop(color, seed=0):
    rng = np.random.default_rng(seed)
    img = np.zeros((128, 64, 3), np.uint8)
    img[:] = color
    img[64:] = (40, 40, 40)
    img += rng.integers(0, 10, img.shape, dtype=np.uint8)
    return img


def test_appearance_shape_and_determinism():
    c = _crop((0, 0, 200))
    v1 = fingerprint(c, "person")
    v2 = fingerprint(c.copy(), "person")
    assert v1.shape == (DIM,) and DIM == 76
    assert np.allclose(v1, v2)
    assert abs(np.linalg.norm(v1) - 1.0) < 1e-5


def test_appearance_separates_colors():
    red1, red2, blue = _crop((0, 0, 200), 1), _crop((0, 0, 210), 2), _crop((200, 0, 0), 3)
    s_same = cosine(fingerprint(red1), fingerprint(red2))
    s_diff = cosine(fingerprint(red1), fingerprint(blue))
    assert s_same > 0.95
    assert s_diff < s_same - 0.1


def test_appearance_empty():
    assert np.all(fingerprint(np.zeros((0, 0, 3), np.uint8)) == 0)
