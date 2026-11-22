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


def test_visual_levels_only_from_a_recorded_ai_yes():
    from nazar.api.visual import level_for
    from nazar.core.config import get_settings

    hi = get_settings().VERIFY_MIN_SIM + 0.05
    assert level_for(hi, None) == "candidate"            # similarity alone is never more than a Candidate
    assert level_for(hi, "unclear") == "candidate"
    assert level_for(hi, "yes") == "probable"             # local similarity AND a recorded AI "yes"
    assert level_for(get_settings().VERIFY_MIN_SIM - 0.02, "yes") == "candidate"   # AI yes on a weak match: no promotion
    assert level_for(hi, "no") is None                    # AI "no" drops the hit
    assert "confirmed" not in {level_for(s, m) for s in (0.0, 0.5, 1.0) for m in (None, "yes", "no", "unclear")}
