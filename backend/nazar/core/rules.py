"""Watch rules: validated spec + pure evaluators used by BOTH replay and live evaluation."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .eventizer import eventize, zone_runs
from .geometry import box_gap, center, iou, point_in_polygon, polygon_for, anchor_point
from .timeutil import in_window, ms_to_dt, parse_hhmm

Trigger = Literal["zone_enter", "zone_exit", "dwell_over", "count_over", "object_removed"]
RuleCls = Literal["person", "car", "motorcycle", "bicycle", "bus", "truck", "backpack", "handbag", "suitcase",
                  "laptop", "cell phone", "bottle", "any_bag"]
BAGS = ("backpack", "handbag", "suitcase")
OBJECTS = {"backpack", "handbag", "suitcase", "laptop", "cell phone", "bottle"}

STATIONARY_S = 10.0
STATIONARY_MOVE = 0.03
ACTOR_WINDOW_MS = 3000
ACTOR_GAP = 0.1
COUNT_COOLDOWN_S = 60


class TimeWindow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_: str = Field(alias="from")
    to: str

    @field_validator("from_", "to")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        t = parse_hhmm(v)
        return f"{t.hour:02d}:{t.minute:02d}"

    def as_dict(self) -> dict:
        return {"from": self.from_, "to": self.to}


class RuleSpec(BaseModel):
    camera_id: str
    trigger: Trigger
    cls: RuleCls
    zone: str
    dwell_s: int | None = None
    count: int | None = None
    time_window: TimeWindow | None = None
    confirm_with_vision: str | None = None
    notify: Literal["voice_note"] = "voice_note"

    @model_validator(mode="after")
    def _required(self):
        if self.trigger == "dwell_over":
            if self.dwell_s is None or self.dwell_s < 5:
                raise ValueError("dwell_over needs dwell_s >= 5")
        if self.trigger == "count_over":
            if self.count is None or self.count < 1:
                raise ValueError("count_over needs count >= 1")
        if self.trigger == "object_removed" and self.cls not in OBJECTS and self.cls != "any_bag":
            raise ValueError("object_removed needs an object class (bag, laptop, phone, bottle)")
        if self.confirm_with_vision is not None and not self.confirm_with_vision.strip():
            self.confirm_with_vision = None
        return self

    def classes(self) -> set[str]:
        return set(BAGS) if self.cls == "any_bag" else {self.cls}

    def window_dict(self) -> dict | None:
        return self.time_window.as_dict() if self.time_window else None

    def dump(self) -> dict:
        d = self.model_dump(by_alias=True)
        if self.time_window:
            d["time_window"] = self.time_window.as_dict()
        return d


def validate_zone(spec: RuleSpec, zones: list[dict]) -> bool:
    return spec.zone == "anywhere" or any(z.get("name") == spec.zone for z in zones or [])


@dataclass
class Hit:
    track_id: int
    t_ms: int
    zone: str
    trigger: str
    actor_track_id: int | None = None
    object_track_id: int | None = None
    box: list | None = None
    extra: dict = field(default_factory=dict)

    @property
    def t(self):
        return ms_to_dt(self.t_ms)

    def as_dict(self) -> dict:
        d = {"track_id": self.track_id, "t": self.t.isoformat(), "zone": self.zone}
        if self.actor_track_id is not None:
            d["actor_track_id"] = self.actor_track_id
        if self.object_track_id is not None:
            d["object_track_id"] = self.object_track_id
        return d


def _zones_for(spec: RuleSpec, zones: list[dict]) -> list[dict]:
    poly = polygon_for(spec.zone, zones)
    return [{"name": spec.zone, "polygon": poly}] if poly else []


def _box_at(path: list, t_ms: int) -> list | None:
    best, bd = None, math.inf
    for p in path:
        d = abs(p[0] - t_ms)
        if d < bd:
            best, bd = p, d
    return list(best[1:5]) if best is not None else None


def _filter_window(spec: RuleSpec, hits: list[Hit]) -> list[Hit]:
    w = spec.window_dict()
    return [h for h in hits if in_window(h.t, w)]


def _find_actor(obj_box: list, t_ms: int, others_near: list[dict] | None) -> tuple[int | None, list | None]:
    best = None
    for o in others_near or []:
        if o.get("cls", "person") != "person":
            continue
        for p in o.get("path") or []:
            if abs(p[0] - t_ms) > ACTOR_WINDOW_MS:
                continue
            b = p[1:5]
            g = box_gap(obj_box, b)
            if iou(obj_box, b) > 0 or g <= ACTOR_GAP:
                score = abs(p[0] - t_ms) + g * 10000
                if best is None or score < best[0]:
                    best = (score, o["id"], list(b))
    return (best[1], best[2]) if best else (None, None)


def object_removed_hits(spec: RuleSpec, track: dict, zones: list[dict], others_near=None) -> list[Hit]:
    path = track.get("path") or []
    poly = polygon_for(spec.zone, zones)
    if not path or not poly:
        return []
    # (a) stationary inside the zone for >= 10 s
    stat_start = None  # (idx, center)
    stationary_until_idx = None
    for i, p in enumerate(path):
        c = center(p[1:5])
        inside = point_in_polygon(c[0], c[1], poly)
        if not inside:
            stat_start = None
            continue
        if stat_start is None or math.hypot(c[0] - stat_start[1][0], c[1] - stat_start[1][1]) >= STATIONARY_MOVE:
            stat_start = (i, c)
        if (p[0] - path[stat_start[0]][0]) / 1000.0 >= STATIONARY_S:
            stationary_until_idx = i
    if stationary_until_idx is None:
        return []
    # (b) then: exited the zone, or the track ended while last seen inside
    removal_ms = None
    obj_box = list(path[stationary_until_idx][1:5])
    for run in zone_runs(path, "_center_", poly, spec.zone):
        if run.closed and run.end_idx >= stationary_until_idx and run.start_idx <= stationary_until_idx:
            removal_ms = run.end_ms
            break
    if removal_ms is None and not track.get("active", False):
        last = path[-1]
        c = center(last[1:5])
        if point_in_polygon(c[0], c[1], poly):
            removal_ms = int(last[0])
            obj_box = list(last[1:5])
    if removal_ms is None:
        return []
    actor, actor_box = _find_actor(obj_box, removal_ms, others_near)
    hit = Hit(
        track_id=actor if actor is not None else int(track["id"]),
        t_ms=int(removal_ms),
        zone=spec.zone,
        trigger=spec.trigger,
        actor_track_id=actor,
        object_track_id=int(track["id"]),
        box=actor_box or obj_box,
    )
    return [hit]


def evaluate_track(spec: RuleSpec, track: dict, zones: list[dict], others_near: list[dict] | None = None) -> list[Hit]:
    """Per-track evaluation (everything except count_over). Pure function."""
    if spec.trigger == "count_over":
        return []
    if track.get("cls") not in spec.classes():
        return []
    path = track.get("path") or []
    if not path:
        return []
    if spec.trigger == "object_removed":
        return _filter_window(spec, object_removed_hits(spec, track, zones, others_near))
    zs = _zones_for(spec, zones)
    if not zs:
        return []
    hits: list[Hit] = []
    tid = int(track["id"])
    if spec.trigger in ("zone_enter", "zone_exit"):
        events, _ = eventize(path, track["cls"], zs)
        want = "enter" if spec.trigger == "zone_enter" else "exit"
        for e in events:
            if e.type == want:
                hits.append(Hit(tid, e.t_ms, spec.zone, spec.trigger, box=_box_at(path, e.t_ms)))
    elif spec.trigger == "dwell_over":
        for run in zone_runs(path, track["cls"], zs[0]["polygon"], spec.zone):
            if (run.end_ms - run.start_ms) / 1000.0 >= spec.dwell_s:
                t = run.start_ms + int(spec.dwell_s * 1000)
                hits.append(Hit(tid, t, spec.zone, spec.trigger, box=_box_at(path, t),
                                extra={"seconds": round((run.end_ms - run.start_ms) / 1000.0, 1)}))
    return _filter_window(spec, hits)


def presence_seconds(track: dict, poly) -> set[int]:
    out: set[int] = set()
    cls = track.get("cls", "person")
    for p in track.get("path") or []:
        x, y = anchor_point(cls, p[1:5])
        if point_in_polygon(x, y, poly):
            out.add(int(p[0] // 1000))
    return out


def evaluate_count(spec: RuleSpec, tracks_in_window: list[dict], zones: list[dict],
                   cooldown_s: int = COUNT_COOLDOWN_S, last_hit_ms: int | None = None) -> list[Hit]:
    """count_over on a 1-second grid: distinct tracks of cls inside zone at the same second > count."""
    if spec.trigger != "count_over":
        return []
    poly = polygon_for(spec.zone, zones)
    if not poly:
        return []
    per_sec: dict[int, list[int]] = {}
    for tr in tracks_in_window:
        if tr.get("cls") not in spec.classes():
            continue
        for s in presence_seconds(tr, poly):
            per_sec.setdefault(s, []).append(int(tr["id"]))
    hits: list[Hit] = []
    prev_over = False
    last = last_hit_ms
    for s in sorted(per_sec):
        ids = per_sec[s]
        over = len(set(ids)) > (spec.count or 0)
        contiguous = (s - 1) in per_sec and len(set(per_sec[s - 1])) > (spec.count or 0)
        if over and not (prev_over and contiguous):
            t = s * 1000
            if last is None or (t - last) >= cooldown_s * 1000:
                hits.append(Hit(min(ids), t, spec.zone, spec.trigger, extra={"n": len(set(ids)), "track_ids": sorted(set(ids))}))
                last = t
        prev_over = over
    return _filter_window(spec, hits)


CLS_WORDS = {"any_bag": "a bag", "person": "someone", "cell phone": "a phone"}
TRIGGER_EN = {
    "zone_enter": "enters",
    "zone_exit": "leaves",
}


def human_sentence(spec: RuleSpec, language: str = "en", zone_label: str | None = None) -> str:
    """Deterministic English fallback (the compiler model normally writes the owner's language)."""
    who = CLS_WORDS.get(spec.cls, f"a {spec.cls}")
    where = "anywhere in view" if spec.zone == "anywhere" else (zone_label or spec.zone.replace("_", " "))
    if spec.trigger in TRIGGER_EN:
        s = f"When {who} {TRIGGER_EN[spec.trigger]} {where}"
    elif spec.trigger == "dwell_over":
        s = f"When {who} stays at {where} for more than {spec.dwell_s} seconds"
    elif spec.trigger == "count_over":
        s = f"When more than {spec.count} {spec.cls if spec.cls != 'person' else 'people'} are at {where} together"
    else:
        s = f"When {who} is taken away from {where}"
    if spec.time_window:
        s += f" between {spec.time_window.from_} and {spec.time_window.to}"
    if spec.confirm_with_vision:
        s += f" (checked by AI: {spec.confirm_with_vision})"
    return s + ", send me a voice note."
