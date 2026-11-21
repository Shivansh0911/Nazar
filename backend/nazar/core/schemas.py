"""Pydantic models shared by worker and API (mirrored in web/lib/types.ts)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Color = Literal["black", "white", "grey", "red", "orange", "yellow", "green", "blue", "purple", "pink", "brown",
                "beige", "unknown"]
COLORS = list(Color.__args__)  # type: ignore[attr-defined]
LevelT = Literal["confirmed", "probable", "candidate"]


class TrackCaption(BaseModel):
    """Structured Output for track crops (vision model)."""
    caption: str = Field(description="<= 25 words, English, factual. No identity, ethnicity, religion, caste or age beyond child/adult.")
    upper_color: Color
    lower_color: Color
    headwear: Literal["none", "cap", "helmet", "turban", "scarf", "hood", "other", "unknown"]
    carrying: list[Literal["backpack", "handbag", "suitcase", "box", "parcel", "bottle", "phone", "laptop", "bag",
                           "umbrella", "nothing", "unknown"]]
    action: Literal["walking", "standing", "sitting", "running", "carrying", "picking_up", "putting_down", "riding",
                    "driving", "parked", "other"]
    vehicle_type: Literal["none", "car", "motorcycle", "scooter", "bicycle", "auto_rickshaw", "bus", "truck", "van",
                          "other"]
    vehicle_color: Color
    notable: str = Field(description="<= 10 words, or empty")
    quality: Literal["good", "poor"]


class VisionCheck(BaseModel):
    yes: bool
    reason: str


class ZoneIn(BaseModel):
    name: str
    label: str
    polygon: list[list[float]]


class ZoneSuggestions(BaseModel):
    zones: list[ZoneIn]


class SeriesPoint(BaseModel):
    t: datetime
    n: int


class CountResult(BaseModel):
    model_config = {"extra": "allow"}  # receipts, receipts_total, receipt_ids
    value: int
    label: str
    level: Literal["confirmed"] = "confirmed"
    series: list[SeriesPoint] = []
    bucket: str = "hour"


class ClipItem(BaseModel):
    model_config = {"extra": "allow"}  # kind, keyframe_id, verified
    track_id: int | None = None
    camera_id: str
    cls: str = "person"
    t_start: datetime
    t_end: datetime
    level: LevelT
    why: str = ""
    caption: str | None = None
    thumb_url: str | None = None
    score: float = 0.0
    zones: list[str] = []


class RuleReplay(BaseModel):
    window_from: datetime
    window_to: datetime
    count: int
    hits: list[dict] = []


class RuleDraft(BaseModel):
    ok: bool = True
    rule_id: int | None = None
    camera_id: str | None = None
    text: str = ""
    human: str = ""
    spec: dict | None = None
    replay: RuleReplay | None = None
    active: bool = False
    question: str | None = None
    missing_zone_label: str | None = None
    hit_thumbs: list[dict] = []


class AskResponse(BaseModel):
    model_config = {"extra": "allow"}  # v2 cards: tables, charts, images, notes, journey, sec_events, report, taught
    query_id: int
    transcript: str | None = None
    language: str = "en"
    reply_text: str
    audio_url: str | None = None
    count: CountResult | None = None
    clips: list[ClipItem] = []
    rule: RuleDraft | None = None
    gaps: list[dict] = []
    followups: list[str] = []
    cost_usd: float = 0.0
    cost_inr: float = 0.0
    latency_ms: int = 0
    first_text_ms: int | None = None
    model: str | None = None
    clarify: dict | None = None
    tables: list[dict] = []
    charts: list[dict] = []
    images: list[dict] = []
    notes: list[dict] = []
    journey: dict | None = None
    sec_events: list[dict] = []
    report: dict | None = None
    taught: dict | None = None


class AlertOut(BaseModel):
    id: int
    rule_id: int
    track_id: int
    camera_id: str
    t: datetime
    message: str
    human: str | None = None
    audio_url: str | None = None
    snapshot_url: str | None = None
    vision_confirmed: bool | None = None
    suppressed: bool = False
    ack: bool = False


class CameraOut(BaseModel):
    id: str
    name: str
    kind: str
    source_url: str
    zones: list[dict] = []
    settings: dict = {}
    width: int | None = None
    height: int | None = None
    active: bool = True
    live: bool = False
    last_heartbeat_age_s: float | None = None
    status_note: str | None = None
    today_count: int = 0
    coverage_from: datetime | None = None
    coverage_to: datetime | None = None
    edge_running: bool = False


class MetricsOut(BaseModel):
    total_usd: float
    total_inr: float
    by_kind: list[dict]
    by_model: list[dict]
    cost_per_camera_day_inr: float | None
    naive_per_camera_day_inr: float | None
    ratio: float | None
    footage_hours: float
    tracks_processed: int
    enrich_backlog: int
    ask_latency_p50_ms: float | None
    ask_latency_p90_ms: float | None
    query_count: int
    level_distribution: dict
    unknown_price_calls: int
    eval: dict | None = None
