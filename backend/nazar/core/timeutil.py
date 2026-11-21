"""IST/local time helpers."""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

from .config import get_settings


@lru_cache
def tz() -> ZoneInfo:
    try:
        return ZoneInfo(get_settings().TZ_NAME)
    except Exception:
        return ZoneInfo("Asia/Kolkata")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_local() -> datetime:
    return datetime.now(tz())


def to_local(t: datetime) -> datetime:
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(tz())


def parse_hhmm(s: str) -> time:
    s = s.strip()
    parts = s.split(":")
    h = int(parts[0])
    m = int(parts[1]) if len(parts) > 1 else 0
    if h == 24:
        h = 0
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError(f"bad time {s!r}")
    return time(h, m)


def in_window(t: datetime, window: dict | None) -> bool:
    """window = {"from": "22:00", "to": "07:00"} in local time; wraps midnight when from > to."""
    if not window:
        return True
    start = parse_hhmm(window["from"])
    end = parse_hhmm(window["to"])
    lt = to_local(t).time()
    if start == end:
        return True
    if start < end:
        return start <= lt < end
    return lt >= start or lt < end


def parse_local(s: str) -> datetime:
    """Parse an ISO string; naive values are local time. Also accepts 'yesterday HH:MM' / 'today HH:MM'."""
    s = s.strip()
    low = s.lower()
    for word, delta in (("yesterday", -1), ("today", 0), ("tomorrow", 1)):
        if low.startswith(word):
            hm = parse_hhmm(low[len(word):].strip() or "00:00")
            d = now_local().date() + timedelta(days=delta)
            return datetime.combine(d, hm, tzinfo=tz())
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz())
    return dt


def fmt_local(t: datetime, lang: str = "en") -> str:
    lt = to_local(t)
    h12 = lt.hour % 12 or 12
    hm = f"{h12}:{lt.minute:02d}"
    if lang == "hi":
        h = lt.hour
        if 4 <= h < 12:
            part = "सुबह"
        elif 12 <= h < 16:
            part = "दोपहर"
        elif 16 <= h < 20:
            part = "शाम"
        else:
            part = "रात"
        return f"{part} {hm}"
    if lang == "hinglish":
        h = lt.hour
        part = "subah" if 4 <= h < 12 else "dopahar" if 12 <= h < 16 else "shaam" if 16 <= h < 20 else "raat"
        return f"{part} {hm}"
    return f"{hm} {'AM' if lt.hour < 12 else 'PM'}"


def ms_to_dt(ms: float) -> datetime:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


def dt_to_ms(t: datetime) -> int:
    return int(round(t.timestamp() * 1000))
