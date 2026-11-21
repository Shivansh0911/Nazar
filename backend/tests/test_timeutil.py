from datetime import datetime, timedelta, timezone

import pytest

from nazar.core.timeutil import fmt_local, in_window, parse_hhmm, parse_local, tz


def L(h, m=0):
    return datetime(2026, 11, 20, h, m, tzinfo=tz())


def test_parse_hhmm():
    assert parse_hhmm("7").hour == 7
    assert parse_hhmm("23:05").minute == 5
    with pytest.raises(ValueError):
        parse_hhmm("25:00")


def test_window_normal_and_wrap():
    day = {"from": "09:00", "to": "17:00"}
    assert in_window(L(9), day) and in_window(L(16, 59), day) and not in_window(L(17), day)
    night = {"from": "22:00", "to": "07:00"}
    assert in_window(L(22), night) and in_window(L(3), night) and in_window(L(0), night)
    assert not in_window(L(7), night) and not in_window(L(12), night)
    assert in_window(L(12), None)


def test_window_uses_local_time_for_utc_input():
    t_utc = L(23, 30).astimezone(timezone.utc)  # 18:00 UTC
    assert in_window(t_utc, {"from": "22:00", "to": "07:00"})


def test_fmt_local():
    assert fmt_local(L(2, 41), "en") == "2:41 AM"
    assert fmt_local(L(2, 41), "hi") == "रात 2:41"
    assert fmt_local(L(14, 5), "en") == "2:05 PM"
    assert fmt_local(L(9, 0), "hinglish") == "subah 9:00"


def test_parse_local_relative():
    y = parse_local("yesterday 22:10")
    assert y.hour == 22 and y.minute == 10
    assert (datetime.now(tz()).date() - y.date()) == timedelta(days=1)
    iso = parse_local("2026-11-20T22:30")
    assert iso.tzinfo is not None and iso.hour == 22
