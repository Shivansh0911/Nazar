import pytest

from nazar.core.levels import assign_level, sort_key

P, C = 0.35, 0.25


@pytest.mark.parametrize("kw,expected", [
    (dict(structural_only=True, sim=None, attr_requested=0, attr_matched=0), "confirmed"),
    (dict(structural_only=True, sim=0.0, attr_requested=2, attr_matched=0), "confirmed"),
    (dict(structural_only=False, sim=0.40, attr_requested=2, attr_matched=2), "probable"),
    (dict(structural_only=False, sim=None, attr_requested=1, attr_matched=1), "probable"),
    (dict(structural_only=False, sim=0.30, attr_requested=2, attr_matched=2), "candidate"),  # attrs agree, sim too low
    (dict(structural_only=False, sim=0.50, attr_requested=0, attr_matched=0), "probable"),
    (dict(structural_only=False, sim=0.44, attr_requested=0, attr_matched=0), "candidate"),
    (dict(structural_only=False, sim=0.40, attr_requested=2, attr_matched=1), "candidate"),
    (dict(structural_only=False, sim=0.10, attr_requested=2, attr_matched=1), "candidate"),
    (dict(structural_only=False, sim=0.10, attr_requested=2, attr_matched=0), None),
    (dict(structural_only=False, sim=None, attr_requested=0, attr_matched=0), None),
])
def test_level_table(kw, expected):
    assert assign_level(**kw, probable_sim=P, candidate_sim=C) == expected


def test_sort_order_candidates_last():
    items = [("candidate", 0.9), ("probable", 0.4), ("confirmed", 0.0), ("probable", 0.6)]
    items.sort(key=lambda x: sort_key(*x))
    assert [i[0] for i in items] == ["confirmed", "probable", "probable", "candidate"]
    assert items[1][1] == 0.6
