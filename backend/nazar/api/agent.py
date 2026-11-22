"""Query agent (Responses API + strict function tools) and the rule compiler.

The model plans and words the reply. Facts (counts, clips, levels) come only from server-side tool results:
the server assembles AskResponse from those results, and the model cannot set or change an evidence level.
"""
from __future__ import annotations

import json
import re
import logging
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from psycopg.types.json import Jsonb
from pydantic import BaseModel, ValidationError

from ..core import db, storage
from ..core.config import get_settings
from ..core.levels import LEVEL_ORDER
from ..core.openai_client import detect_language, get_ai
from ..core.replay import replay
from ..core.rules import RuleSpec, human_sentence, validate_zone
from ..core.schemas import COLORS
from ..core.timeutil import now_local, to_local
from . import agent_tools

log = logging.getLogger("nazar.agent")
MAX_ROUNDS = 6

AGENT_SYSTEM = """You are Nazar, an assistant that answers questions about the owner's own CCTV footage (shops, homes,
offices in India). The owner writes or speaks Hindi, English or Hinglish.

Rules:
- Always use tools for facts. Never invent counts, times, people or clips.
- Be fast: call ALL the tools you need in ONE round (they run in parallel), then answer. Call camera_gaps in that same
  first round only when the asked time may be outside the cameras' data coverage shown below.
- Counts come ONLY from count_events (or peak_occupancy for "how crowded / sabse zyada bheed"). If the owner names
  only a camera or no place ("lobby mein kitne log aaye", "aaj kitne log aaye"), use event "present" with zone null.
  Use event "enter" with a zone ONLY when the owner names a place that matches a zone label ("counter pe", "gate pe").
- Descriptions of people, objects or vehicles ("red shirt", "laal shirt", "carrying a bag", "helmet wala", "green
  backpack", "who took the bag") go to visual_search FIRST with a short English visual phrase - it searches the
  local visual index, which covers every track and scene frame. Use search_tracks for descriptions only as a second
  try. For "who took / picked up X" also call list_events (object_removed).
- "Who came / kaun aaya / show me" without a description -> search_tracks without attributes (tracker facts).
- If the owner asks to be notified or alerted ("mujhe batana", "alert me", "jab bhi", "notify"), call create_rule
  with the owner's words. It is not activated until the owner taps Activate - say so briefly.
- Resolve relative times against the current local time given in the context. "kal raat" = yesterday 20:00 to
  today 06:00 unless specified; "aaj" = today 00:00 to now; "subah" = 05:00-11:00; "shaam" = 16:00-20:00;
  "raat 2 baje ke baad" = 02:00 onwards that night. If the asked time is outside the camera's data coverage,
  use the coverage window and say so.
- If nothing is found, say it plainly and call camera_gaps to mention when the camera had no footage.
- Reply in the user's language and script: Hindi question -> Hindi in Devanagari; Hinglish in Latin letters ->
  Hinglish; English -> English. 1-3 short spoken-style sentences. Times like "रात 2:41" / "raat 2:41" / "2:41 AM".
- Do not name evidence levels, except "pakka"/"confirmed" for tracker facts and "shayad"/"possible match" for
  uncertain matches. Never describe faces or guess identity, religion, caste or ethnicity.
- Visual descriptions of objects, vehicles or scenes that the tracker may not label ("red scooter", "gas cylinder",
  "was the shutter open", "yellow kurta with backpack") -> visual_search with a short ENGLISH visual phrase (translate
  Hindi/Hinglish). It searches the local visual index and AI-verifies the top hits.
- "Any analysis" (busiest hour, average time at counter, vehicles by type per hour, compare cameras, who stayed > 5
  min, day-over-day) -> analytics_query with ONE PostgreSQL SELECT over these read-only views only:
{views}
  Use local times as timestamptz literals with +05:30. For people counts use v_tracks WHERE counted AND cls='person'.
  Prefer count_events for simple "how many" questions (it also returns receipts).
- "Same person/bag elsewhere / kahan kahan gaya" -> journey(track_id). "What happened in this clip" -> describe_clip.
- "Right now / abhi" -> look_now (counts come from the tracker; set needs_vision only for non-countable questions).
- "Today vs yesterday / is hafte vs pichle" -> compare_periods. "Where do people spend time" -> heatmap.
- Security questions (loitering, abandoned bag, running, fall, snatching, "kuch ajeeb hua?") -> list_events.
- "Watch for X / X pe nazar rakho" for an object class the tracker does not know -> teach_object.
  "Report / FIR / incident report banao" -> make_report.
- Never search, match or describe faces. If asked to find a face, say Nazar does not do face recognition and offer
  clothing/appearance search instead.
- If the request is vague (no time, no place, several meanings), ask ONE short clarifying question and give 2-4
  tappable options in clarify instead of guessing; leave other fields empty.
- In the final JSON: show_track_ids = up to 6 track ids taken from search_tracks results that best answer the
  question (empty if none); count_ref = the index of the count_events/peak_occupancy call whose number you quote,
  else null; rule_id from create_rule, else null; followups = up to 3 short follow-up questions in the same language;
  charts = charts for analytics_query/compare results worth plotting (call_index of that tool call, x and y column
  names); confidence = "low" if you are unsure you answered correctly, else "high".
"""

COMPILER_SYSTEM = """You compile a shop owner's instruction (Hindi/English/Hinglish) into a watch rule for ONE camera.
Allowed triggers: zone_enter (someone/something enters a zone), zone_exit, dwell_over (stays longer than dwell_s
seconds, >= 5), count_over (more than `count` at the same time), object_removed (a bag/object that was lying in a
zone is taken away). Allowed cls: person, car, motorcycle, bicycle, bus, truck, backpack, handbag, suitcase,
laptop, cell phone, bottle, any_bag. zone must be one of the camera's zone names, or "anywhere" for the whole view.
Time windows use 24h local "HH:MM" and may wrap midnight. Examples:
- "Jab bhi koi desk 14 se bag uthaye, mujhe batana" -> object_removed, any_bag, zone desk_14
- "Raat 11 ke baad gate pe koi aaye toh batao" -> zone_enter, person, gate, window 23:00-06:00
- "Counter pe 5 se zyada log ho jaayein toh" -> count_over, person, counter, count 5
- "Agar koi gate pe 2 minute se zyada ruke" -> dwell_over, person, gate, dwell_s 120
- "Parcel ke paas koi jaaye" -> zone_enter person in the zone that holds the parcel, if such a zone exists; else ask.
If the place the owner names has no matching zone, return ok=false, missing_zone_label = the place in the owner's
words, and a short question in the owner's language asking them to draw it (e.g. "Desk 14 ka area camera pe draw kar
dijiye"). confirm_with_vision: only when the owner asks for something the tracker cannot check (e.g. "sirf agar
woh helmet pehna ho") - a short English yes/no statement, else null.
human: ONE sentence in the owner's language and script describing the rule, ending with sending a voice note.
"""


# ------------------------------------------------------------------------------------------------ tool schemas
def _nullable(t: str, **extra) -> dict:
    d = {"type": [t, "null"], **extra}
    if "enum" in d:
        d["enum"] = list(d["enum"]) + [None]
    return d


CLS_ENUM = ["person", "car", "motorcycle", "bicycle", "bus", "truck", "backpack", "handbag", "suitcase", "laptop",
            "cell phone", "bottle", "any_bag"]
CARRY_ENUM = ["backpack", "handbag", "suitcase", "box", "parcel", "bottle", "phone", "laptop", "bag", "umbrella"]
VEHICLE_ENUM = ["car", "motorcycle", "scooter", "bicycle", "auto_rickshaw", "bus", "truck", "van"]
ACTION_ENUM = ["walking", "standing", "sitting", "running", "carrying", "picking_up", "putting_down", "riding",
               "driving", "parked"]
COLOR_ENUM = [c for c in COLORS if c != "unknown"]


def _fn(name: str, desc: str, props: dict) -> dict:
    return {"type": "function", "name": name, "description": desc, "strict": True,
            "parameters": {"type": "object", "properties": props, "required": list(props),
                           "additionalProperties": False}}


TOOLS = [
    _fn("search_tracks", "Find tracked people/vehicles/objects by time, camera, zone and description. Returns tracks "
        "with server-assigned evidence levels.", {
            "camera_ids": {"type": ["array", "null"], "items": {"type": "string"}},
            "time_from": {"type": "string", "description": "ISO local time"},
            "time_to": {"type": "string", "description": "ISO local time"},
            "cls": {"type": ["array", "null"], "items": {"type": "string", "enum": CLS_ENUM}},
            "zones": {"type": ["array", "null"], "items": {"type": "string"}},
            "upper_color": _nullable("string", enum=COLOR_ENUM),
            "lower_color": _nullable("string", enum=COLOR_ENUM),
            "carrying": {"type": ["array", "null"], "items": {"type": "string", "enum": CARRY_ENUM}},
            "vehicle_type": _nullable("string", enum=VEHICLE_ENUM),
            "vehicle_color": _nullable("string", enum=COLOR_ENUM),
            "action": _nullable("string", enum=ACTION_ENUM),
            "text": _nullable("string", description="short English description for semantic search"),
            "limit": _nullable("integer"),
        }),
    _fn("count_events", "Count distinct tracks (SQL facts). event=present counts everyone seen (zone optional); "
        "enter/exit/dwell need a zone.", {
            "camera_id": _nullable("string"),
            "zone": _nullable("string"),
            "cls": _nullable("string", enum=CLS_ENUM),
            "event": _nullable("string", enum=["enter", "exit", "dwell", "present", "cross_in", "cross_out"]),
            "time_from": {"type": "string"},
            "time_to": {"type": "string"},
            "bucket": _nullable("string", enum=["10s", "1min", "5min", "15min", "hour", "day"]),
        }),
    _fn("peak_occupancy", "Maximum number of tracks present at the same time, and when.", {
        "camera_id": {"type": "string"},
        "zone": _nullable("string"),
        "cls": _nullable("string", enum=CLS_ENUM),
        "time_from": {"type": "string"},
        "time_to": {"type": "string"},
    }),
    _fn("camera_gaps", "Periods with no stored footage (camera offline) in a window.", {
        "camera_id": {"type": "string"},
        "time_from": {"type": "string"},
        "time_to": {"type": "string"},
    }),
    _fn("create_rule", "Compile the owner's alert request into a watch rule, replay it on past footage and save it "
        "INACTIVE (the owner activates it).", {
            "camera_id": {"type": "string"},
            "text": {"type": "string", "description": "the owner's own words"},
        }),
    _fn("analytics_query", "Run ONE read-only SELECT over the semantic views (database facts).", {
        "sql": {"type": "string"},
        "title": {"type": "string", "description": "short title for the result, owner's language"},
    }),
    _fn("visual_search", "Search the local visual index (crops + scene frames) by an English visual phrase; top hits "
        "are AI-verified. Use for objects/vehicles/clothing/scene states.", {
            "text": {"type": "string", "description": "short English visual phrase, e.g. 'red scooter'"},
            "camera_ids": {"type": ["array", "null"], "items": {"type": "string"}},
            "time_from": {"type": "string"},
            "time_to": {"type": "string"},
            "cls": {"type": ["array", "null"], "items": {"type": "string"}},
            "limit": _nullable("integer"),
        }),
    _fn("journey", "Where else the same-looking person/bag/vehicle was seen (other cameras/times), by appearance only.", {
        "track_id": {"type": "integer"},
        "hours": _nullable("number"),
    }),
    _fn("describe_clip", "Describe what happens in a moment (AI-generated, from blurred frames).", {
        "track_id": _nullable("integer"),
        "camera_id": _nullable("string"),
        "time": _nullable("string", description="ISO local time when no track_id"),
    }),
    _fn("look_now", "What a camera sees right now: tracker counts + optional vision answer on the latest frame.", {
        "camera_id": {"type": "string"},
        "question": _nullable("string"),
        "needs_vision": {"type": "boolean"},
    }),
    _fn("compare_periods", "Compare a count between two periods (SQL facts).", {
        "camera_id": _nullable("string"),
        "zone": _nullable("string"),
        "cls": _nullable("string", enum=CLS_ENUM),
        "event": _nullable("string", enum=["enter", "exit", "dwell", "present", "cross_in", "cross_out"]),
        "a_from": {"type": "string"}, "a_to": {"type": "string"}, "a_label": {"type": "string"},
        "b_from": {"type": "string"}, "b_to": {"type": "string"}, "b_label": {"type": "string"},
    }),
    _fn("heatmap", "Where people/vehicles spent time on a camera (image).", {
        "camera_id": {"type": "string"},
        "cls": _nullable("string", enum=CLS_ENUM),
        "time_from": {"type": "string"},
        "time_to": {"type": "string"},
    }),
    _fn("list_events", "Security events (loitering, abandoned_object, object_removed, running, fall, crowding, "
        "after_hours, possible_snatch, wrong_way) and unusual-activity hours.", {
            "camera_id": _nullable("string"),
            "time_from": {"type": "string"},
            "time_to": {"type": "string"},
            "types": {"type": ["array", "null"], "items": {"type": "string"}},
        }),
    _fn("teach_object", "Start detecting a new kind of object on a camera from words (open-vocabulary).", {
        "camera_id": {"type": "string"},
        "name": {"type": "string", "description": "short English object name, e.g. 'gas cylinder'"},
        "alert": {"type": "boolean", "description": "true if the owner wants to be alerted when it appears"},
    }),
    _fn("make_report", "Create a police-ready incident PDF for an alert, security event or tracks.", {
        "title": {"type": "string"},
        "alert_id": _nullable("integer"),
        "sec_event_id": _nullable("integer"),
        "track_ids": {"type": ["array", "null"], "items": {"type": "integer"}},
        "language": {"type": "string", "enum": ["en", "hi"]},
    }),
]

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "reply_text": {"type": "string"},
        "language": {"type": "string", "enum": ["hi", "en", "hinglish"]},
        "show_track_ids": {"type": "array", "items": {"type": "integer"}},
        "count_ref": {"type": ["integer", "null"]},
        "rule_id": {"type": ["integer", "null"]},
        "followups": {"type": "array", "items": {"type": "string"}},
        "charts": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["type", "title", "call_index", "x", "y", "unit"],
            "properties": {"type": {"type": "string", "enum": ["bar", "line", "pie", "table"]},
                           "title": {"type": "string"}, "call_index": {"type": "integer"},
                           "x": {"type": "string"}, "y": {"type": "string"}, "unit": {"type": "string"}}}},
        "confidence": {"type": "string", "enum": ["high", "low"]},
        "clarify": {"type": ["object", "null"], "additionalProperties": False, "required": ["question", "options"],
                    "properties": {"question": {"type": "string"},
                                   "options": {"type": "array", "items": {"type": "string"}}}},
    },
    "required": ["reply_text", "language", "show_track_ids", "count_ref", "rule_id", "followups", "charts",
                 "confidence", "clarify"],
    "additionalProperties": False,
}


class AgentAnswer(BaseModel):
    reply_text: str
    language: Literal["hi", "en", "hinglish"]
    show_track_ids: list[int] = []
    count_ref: int | None = None
    rule_id: int | None = None
    followups: list[str] = []
    charts: list[dict] = []
    confidence: Literal["high", "low"] = "high"
    clarify: dict | None = None


# ------------------------------------------------------------------------------------------------ context
def camera_context(selected: str | None) -> str:
    cov = {c["camera_id"]: c for c in agent_tools.coverage()}
    lines = []
    for r in db.fetch_all("SELECT id, name, kind, zones FROM cameras ORDER BY created_at"):
        zones = ", ".join(f"{z['name']} ({z.get('label', z['name'])})" for z in (r["zones"] or [])) or "no zones"
        c = cov.get(r["id"])
        if c:  # round the end UP to the minute: a window ending at "02:05" must not cut off footage from 02:05:25
            end = datetime.fromisoformat(c["to"])
            end = (end + timedelta(minutes=1)).replace(second=0, microsecond=0) if end.second or end.microsecond else end
            span = f"{c['from'][:16]} to {end.isoformat()[:16]}"
        else:
            span = "no footage yet"
        lines.append(f"- {r['id']}: \"{r['name']}\"; zones: {zones}; data coverage: {span}")
    now = now_local()
    sel = f"The owner selected camera '{selected}' in the app; use it unless they name another." if selected else \
        "The owner is asking about all cameras; pick the camera(s) that fit the question."
    return (f"Current local time: {now.isoformat(timespec='minutes')} ({now:%A}), timezone Asia/Kolkata.\n"
            f"Cameras:\n" + "\n".join(lines) + f"\n{sel}")


# ------------------------------------------------------------------------------------------------ rule compiler
class CompiledRule(BaseModel):
    ok: bool
    trigger: Literal["zone_enter", "zone_exit", "dwell_over", "count_over", "object_removed"] | None
    cls: Literal["person", "car", "motorcycle", "bicycle", "bus", "truck", "backpack", "handbag", "suitcase",
                 "laptop", "cell phone", "bottle", "any_bag"] | None
    zone: str | None
    dwell_s: int | None
    count: int | None
    window_from: str | None
    window_to: str | None
    confirm_with_vision: str | None
    human: str | None
    missing_zone_label: str | None
    question: str | None


def _replay_window(camera_id: str) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    t_to, t_from = now, now - timedelta(hours=24)
    last = db.fetch_val("SELECT max(t_end) FROM coverage WHERE camera_id=%s", (camera_id,))
    if last is not None and last < t_from:
        first = db.fetch_val("SELECT min(t_start) FROM coverage WHERE camera_id=%s", (camera_id,))
        t_to = last + timedelta(seconds=1)
        t_from = max(first, t_to - timedelta(hours=24))
    return t_from, t_to


def compile_rule(text: str, camera_id: str, language: str | None = None, *, ref: str | None = None,
                 token: str | None = None) -> dict:
    cam = db.fetch_one("SELECT id, name, zones FROM cameras WHERE id=%s", (camera_id,))
    if not cam:
        return {"ok": False, "camera_id": camera_id, "text": text, "question": f"Camera {camera_id} not found."}
    lang = language or detect_language(text)
    zones = cam["zones"] or []
    zone_lines = "\n".join(f"- {z['name']}: {z.get('label', z['name'])}" for z in zones) or "- (no zones drawn yet)"
    user = (f"Camera: {cam['id']} (\"{cam['name']}\")\nZones:\n{zone_lines}\nOwner language: {lang}\n"
            f"Owner's instruction: {text}")
    res, _ = get_ai().parse(get_settings().OPENAI_AGENT_MODEL, [{"role": "user", "content": user}], CompiledRule,
                            kind="compile", instructions=COMPILER_SYSTEM, camera_id=camera_id, ref=ref or "compile",
                            max_output_tokens=1200, reasoning=get_settings().AGENT_REASONING_EFFORT or None)
    base = {"camera_id": camera_id, "text": text, "active": False}
    if not res.ok or not res.trigger or not res.cls:
        return {**base, "ok": False, "question": res.question or "Which area should I watch? Please draw it as a zone.",
                "missing_zone_label": res.missing_zone_label}
    spec_d: dict[str, Any] = {"camera_id": camera_id, "trigger": res.trigger, "cls": res.cls, "zone": res.zone or "anywhere",
                              "dwell_s": res.dwell_s, "count": res.count, "confirm_with_vision": res.confirm_with_vision}
    if res.window_from and res.window_to:
        spec_d["time_window"] = {"from": res.window_from, "to": res.window_to}
    try:
        spec = RuleSpec.model_validate(spec_d)
    except ValidationError as e:
        msg = e.errors()[0].get("msg", "invalid rule")
        return {**base, "ok": False, "question": f"I could not build that rule ({msg}). Please rephrase."}
    if not validate_zone(spec, zones):
        label = res.missing_zone_label or spec.zone.replace("_", " ")
        q = res.question or (f"{label} ka area camera pe draw kar dijiye." if lang != "en"
                             else f"Please draw the '{label}' area on the camera first.")
        return {**base, "ok": False, "missing_zone_label": label, "question": q}
    zl = next((z.get("label") for z in zones if z["name"] == spec.zone), None)
    human = (res.human or "").strip() or human_sentence(spec, lang, zl)
    w0, w1 = _replay_window(camera_id)
    hits = replay(spec, w0, w1)
    replay_d = {"window_from": to_local(w0).isoformat(), "window_to": to_local(w1).isoformat(), "count": len(hits),
                "hits": [h.as_dict() for h in hits[:20]]}
    rid = db.fetch_one("INSERT INTO rules(camera_id, text, spec, human, active, replay, language) VALUES "
                       "(%s,%s,%s,%s,false,%s,%s) RETURNING id",
                       (camera_id, text, Jsonb(spec.dump()), human, Jsonb(replay_d), lang))["id"]
    return {**base, "ok": True, "rule_id": rid, "human": human, "spec": spec.dump(), "replay": replay_d,
            "hit_thumbs": hit_thumbs(replay_d["hits"][:4], token)}


def hit_thumbs(hits: list[dict], token: str | None) -> list[dict]:
    out = []
    for h in hits:
        tid = h.get("object_track_id") if h.get("actor_track_id") is None and h.get("object_track_id") else h["track_id"]
        r = db.fetch_one("SELECT crop_keys FROM tracks WHERE id=%s", (h["track_id"],))
        keys = (r or {}).get("crop_keys") or []
        out.append({"track_id": h["track_id"], "t": h["t"], "thumb_url": storage.url(keys[0], token) if keys else None,
                    "object_track_id": h.get("object_track_id"), "clip_track_id": tid})
    return out


# ------------------------------------------------------------------------------------------------ the agent
def _exec_tool(name: str, args: dict, ref: str, token: str | None) -> dict:
    a = {k: v for k, v in args.items() if v is not None}
    if name == "search_tracks":
        r = agent_tools.search_tracks(a, ref=ref)
        attr_keys = ("upper_color", "lower_color", "carrying", "vehicle_type", "vehicle_color", "action", "text")
        if not r.get("results") and any(a.get(k) for k in attr_keys):
            # most tracks are not described (captions are on demand): fall back to the local visual index
            from . import agent_tools2 as t2

            words = [a.get("text") or ""] + [f"{a[k]}" for k in ("upper_color", "lower_color", "vehicle_color", "vehicle_type", "action") if a.get(k)]
            words += [f"carrying {c}" for c in a.get("carrying") or []]
            phrase = " ".join(w for w in words if w).strip()[:120]
            cls = [c for c in (a.get("cls") or []) if c not in ("person",)] or None
            v = t2.visual_search_tool({"text": phrase, "time_from": a["time_from"], "time_to": a["time_to"],
                                       "camera_ids": a.get("camera_ids"), "cls": cls, "limit": a.get("limit") or 8}, ref)
            return {**r, "visual_fallback": True, "visual_hits": v.get("hits", []), "_visual": v,
                    "note": f"no described tracks; searched the visual index for '{phrase}' instead: {len(v.get('hits', []))} hits"}
        return r
    if name == "count_events":
        return agent_tools.count_events(a)
    if name == "peak_occupancy":
        return agent_tools.peak_occupancy(a)
    if name == "camera_gaps":
        return agent_tools.camera_gaps(a)
    if name == "create_rule":
        d = compile_rule(a.get("text", ""), a.get("camera_id", ""), ref=ref, token=token)
        return {k: d.get(k) for k in ("ok", "rule_id", "human", "question", "missing_zone_label")} | {
            "replay_count": (d.get("replay") or {}).get("count"), "_draft": d}
    from . import agent_tools2 as t2

    if name == "analytics_query":
        from .analytics import UnsafeSQL, run

        try:
            r = run(a.get("sql", ""))
        except UnsafeSQL as e:
            return {"error": f"rejected: {e}"}
        return {**r, "title": a.get("title"), "rows": r["rows"][:200], "_all_rows": r["rows"]}
    if name == "visual_search":
        return t2.visual_search_tool(a, ref)
    if name == "journey":
        return t2.journey_tool(a)
    if name == "describe_clip":
        return t2.describe_clip(a, ref)
    if name == "look_now":
        return t2.look_now(a, ref)
    if name == "compare_periods":
        return t2.compare_periods(a)
    if name == "heatmap":
        return t2.heatmap(a)
    if name == "list_events":
        return t2.list_events(a)
    if name == "teach_object":
        from .teach import teach_from_text

        return teach_from_text(a.get("camera_id", ""), a.get("name", ""), alert=bool(a.get("alert")), ref=ref)
    if name == "make_report":
        from .reports import create_report

        return create_report(title=a.get("title") or "Incident", alert_id=a.get("alert_id"),
                             sec_event_id=a.get("sec_event_id"), track_ids=a.get("track_ids"),
                             language=a.get("language") or "en", token=token)
    return {"error": f"unknown tool {name}"}


def _item_dict(item: Any) -> dict:
    if hasattr(item, "model_dump"):
        d = item.model_dump(exclude_none=True)
    else:
        d = dict(item)
    if d.get("type") == "function_call":
        return {"type": "function_call", "call_id": d["call_id"], "name": d["name"], "arguments": d["arguments"]}
    return d


def _system() -> str:
    from .analytics import describe_views

    return AGENT_SYSTEM.replace("{views}", describe_views())


class _ReplyStream:
    """Extracts the growing value of "reply_text" from streamed JSON and forwards new characters."""

    def __init__(self, emit):
        self.buf = ""
        self.sent = 0
        self.emit = emit

    def feed(self, delta: str) -> None:
        self.buf += delta
        m = re.search(r'"reply_text"\s*:\s*"', self.buf)
        if not m:
            return
        out = []
        i = m.end()
        while i < len(self.buf):
            ch = self.buf[i]
            if ch == '"':
                break
            if ch == "\\":
                if i + 1 >= len(self.buf):
                    break
                nxt = self.buf[i + 1]
                if nxt == "u":
                    if i + 6 > len(self.buf):
                        break
                    try:
                        out.append(chr(int(self.buf[i + 2:i + 6], 16)))
                    except ValueError:
                        pass
                    i += 6
                    continue
                out.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\", "/": "/"}.get(nxt, nxt))
                i += 2
                continue
            out.append(ch)
            i += 1
        text = "".join(out)
        if len(text) > self.sent:
            self.emit(text[self.sent:])
            self.sent = len(text)


STATUS = {"count_events": "Counting from the tracker…", "search_tracks": "Searching tracks…",
          "visual_search": "Searching the visual index and checking the best matches…",
          "analytics_query": "Running the analysis…", "journey": "Following it across cameras…",
          "describe_clip": "Looking at the clip…", "look_now": "Looking at the camera now…",
          "compare_periods": "Comparing periods…", "heatmap": "Drawing the heatmap…",
          "list_events": "Checking security events…", "create_rule": "Building the rule and replaying it…",
          "teach_object": "Teaching the camera a new object…", "make_report": "Preparing the incident report…",
          "peak_occupancy": "Finding the busiest moment…", "camera_gaps": "Checking camera coverage…"}


FAST_COUNT_REPLY = True
# "how many" in the languages we test; other questions that happen to use count_events keep the full agent path
COUNT_Q = re.compile(r"kitn|how many|number of|कितन|எத்தனை|ఎంత|কত|કેટલ|ಎಷ್ಟು", re.I)
_NOUN = {"person": ("people", "log", "लोग"), "car": ("cars", "gaadiyan", "गाड़ियाँ"), "motorcycle": ("motorcycles", "bikes", "बाइक"),
         "bicycle": ("bicycles", "cycles", "साइकिलें"), "truck": ("trucks", "trucks", "ट्रक"), "bus": ("buses", "buses", "बसें"),
         "any_bag": ("bags", "bags", "बैग"), "bag": ("bags", "bags", "बैग")}
_VERB = {"present": ("seen", "dikhe", "दिखे"), "enter": ("came in", "aaye", "आए"), "exit": ("left", "gaye", "गए"),
         "dwell": ("stayed 10 s+", "ruke", "रुके"), "cross_in": ("came in through the line", "andar aaye", "अंदर आए"),
         "cross_out": ("went out through the line", "bahar gaye", "बाहर गए")}


def _when(a: str, b: str) -> str:
    x, y = datetime.fromisoformat(a), datetime.fromisoformat(b)
    if x.date() == y.date() or (y - x).total_seconds() < 86400:
        return f"{x:%d %b}, {x:%H:%M}–{y:%H:%M}"
    return f"{x:%d %b %H:%M} – {y:%d %b %H:%M}"


def count_reply(question: str, res: dict) -> "AgentAnswer":
    """A count answer written by the server from the SQL result (numbers never come from a model)."""
    lang = detect_language(question)
    li = {"en": 0, "hinglish": 1, "hi": 2}[lang]
    n = res["value"]
    noun = _NOUN.get(res.get("cls") or "person", (res.get("cls"), res.get("cls"), res.get("cls")))[li]
    if (res.get("cls") or "person") == "person":
        noun = ("people on foot", "log (paidal)", "पैदल लोग")[li]
    verb = _VERB.get(res.get("event") or "present", _VERB["present"])[li]
    names = {c["id"]: c["name"] for c in db.fetch_all("SELECT id, name FROM cameras")}
    cam = names.get(res.get("camera_id")) or res.get("camera_id") or ("all cameras", "sabhi cameras", "सभी कैमरों")[li]
    zone = f" ({res['zone']})" if res.get("zone") else ""
    when = _when(res["time_from"], res["time_to"])
    text = [f"{n} {noun} {verb} at {cam}{zone}, {when} — confirmed by the tracker; each one is in the receipts.",
            f"{cam}{zone} par {when} ke beech {n} {noun} {verb} — tracker se confirmed, har ek receipts mein hai.",
            f"{cam}{zone} पर {when} के बीच {n} {noun} {verb} — ट्रैकर से पुष्ट, हर एक रसीदों में है।"][li]
    if res.get("riders"):
        text += [f" ({res['riders']} motorcycle/bicycle riders counted separately.)",
                 f" ({res['riders']} bike/cycle sawaar alag gine gaye.)",
                 f" ({res['riders']} बाइक/साइकिल सवार अलग गिने गए।)"][li]
    follow = [["Show me the clips", "Which hour was busiest?"], ["Clips dikhao", "Sabse busy ghanta kaunsa tha?"],
              ["क्लिप दिखाओ", "सबसे व्यस्त घंटा कौन सा था?"]][li]
    return AgentAnswer(reply_text=text, language=lang, count_ref=0, followups=follow)


def run_agent(question: str, camera_id: str | None, *, ref: str, token: str | None, model: str | None = None,
              on_event=None) -> tuple[AgentAnswer, list[dict]]:
    ai = get_ai()
    model = model or get_settings().OPENAI_AGENT_MODEL
    inp: list[dict] = [{"role": "developer", "content": camera_context(camera_id)},
                       {"role": "user", "content": question}]
    calls: list[dict] = []
    text_fmt = {"format": {"type": "json_schema", "name": "agent_answer", "schema": ANSWER_SCHEMA, "strict": True}}
    emit = (lambda kind, data: on_event(kind, data)) if on_event else (lambda kind, data: None)
    for rnd in range(MAX_ROUNDS + 1):
        last = rnd == MAX_ROUNDS
        rs = _ReplyStream(lambda t: emit("text", t))
        resp, _ = ai.agent_step_stream(model=model, input=inp, tools=None if last else TOOLS, instructions=_system(),
                                       text=text_fmt, ref=ref, camera_id=camera_id,
                                       reasoning=get_settings().AGENT_REASONING_EFFORT or None,
                                       on_delta=rs.feed if on_event else None)
        fcalls = [o for o in (resp.output or []) if getattr(o, "type", None) == "function_call"]
        if not fcalls:
            raw = getattr(resp, "output_text", "") or ""
            try:
                return AgentAnswer.model_validate(json.loads(raw)), calls
            except Exception:
                log.warning("agent returned non-JSON final text; wrapping it")
                return AgentAnswer(reply_text=raw.strip() or "…", language=detect_language(question)), calls
        for o in resp.output or []:
            if getattr(o, "type", None) in ("function_call", "reasoning"):
                inp.append(_item_dict(o))

        def run_one(fc):
            try:
                args = json.loads(fc.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            try:
                result = _exec_tool(fc.name, args, ref, token)
            except Exception as e:
                log.warning("tool %s failed: %s", fc.name, e)
                result = {"error": str(e)[:300]}
            return fc, args, result

        for fc in fcalls:
            emit("status", STATUS.get(fc.name, "Working…"))
        if len(fcalls) > 1:  # parallel tool calls
            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(max_workers=min(4, len(fcalls))) as pool:
                outs = list(pool.map(run_one, fcalls))
        else:
            outs = [run_one(fcalls[0])]
        if rnd == 0 and len(outs) == 1 and outs[0][0].name == "count_events" and FAST_COUNT_REPLY and COUNT_Q.search(question):
            res = outs[0][2]
            if isinstance(res, dict) and not res.get("error") and (res.get("value") or 0) > 0:
                # v3 latency: the count is already the answer (from SQL) - write it server-side, skip a model round
                calls.append({"index": 0, "name": "count_events", "args": outs[0][1], "result": res})
                ans = count_reply(question, res)
                emit("text", ans.reply_text)
                return ans, calls
        for fc, args, result in outs:
            idx = len(calls)
            calls.append({"index": idx, "name": fc.name, "args": args, "result": result})
            model_view = {k: v for k, v in result.items() if not k.startswith("_")} if isinstance(result, dict) else result
            if isinstance(model_view, dict) and model_view.get("visual_hits") is not None:
                model_view = {**model_view, "visual_hits": [{k: h.get(k) for k in ("kind", "id", "track_id", "camera_id",
                                                                                 "cls", "t", "level", "why")}
                                                            for h in model_view["visual_hits"]]}
            if isinstance(model_view, dict) and fc.name == "visual_search":
                model_view = {**model_view, "hits": [{k: h.get(k) for k in ("kind", "id", "track_id", "camera_id", "cls",
                                                                              "t", "level", "why")}
                                                     for h in model_view.get("hits", [])]}
            inp.append({"type": "function_call_output", "call_id": fc.call_id,
                        "output": json.dumps({"tool_call_index": idx, **model_view}, default=str)[:20000]})
    raise RuntimeError("agent did not finish")


def _thumbs(track_ids: list[int], token: str | None) -> dict[int, str | None]:
    if not track_ids:
        return {}
    rows = db.fetch_all("SELECT id, crop_keys FROM tracks WHERE id = ANY(%s)", (list(track_ids),))
    return {r["id"]: storage.url((r["crop_keys"] or [None])[0], token) for r in rows}


def assemble(answer: AgentAnswer, calls: list[dict], token: str | None) -> dict:
    """Build the response from SERVER tool results only. Levels are copied from the server, never from the model."""
    found: dict[int, dict] = {}
    for c in calls:
        if c["name"] == "search_tracks" and isinstance(c["result"], dict):
            for r in c["result"].get("results", []):
                found.setdefault(r["track_id"], r)
    clips = []
    shown = [int(t) for t in answer.show_track_ids[:6] if int(t) in found]
    thumbs = _thumbs(shown, token)
    for tid in shown:
        r = found[tid]
        clips.append({"track_id": r["track_id"], "camera_id": r["camera_id"], "cls": r["cls"], "t_start": r["t_start"],
                      "t_end": r["t_end"], "level": r["level"], "why": r["why"], "caption": r.get("caption"),
                      "thumb_url": thumbs.get(tid), "score": r.get("score", 0.0), "zones": r.get("zones", []),
                      "kind": "track"})
    # visual search hits (tracks + scene keyframes); verified "no" hits were already dropped by the server
    for c in calls:
        vres = c["result"].get("_visual") if c["name"] == "search_tracks" and isinstance(c["result"], dict) else None
        if (c["name"] == "visual_search" and isinstance(c["result"], dict)) or vres:
            for h in (vres or c["result"]).get("hits", [])[:8]:
                if any(x.get("kind") == h["kind"] and (x.get("track_id") == h.get("track_id") if h["kind"] == "track"
                                                     else x.get("keyframe_id") == h["id"]) for x in clips):
                    continue
                clips.append({"track_id": h.get("track_id"), "keyframe_id": h["id"] if h["kind"] == "keyframe" else None,
                              "camera_id": h["camera_id"], "cls": h["cls"], "t_start": h["t_start"], "t_end": h["t_end"],
                              "level": h["level"], "why": h["why"], "caption": h.get("caption"),
                              "thumb_url": storage.url(h.get("thumb_key"), token), "score": h["sim"],
                              "zones": h.get("zones", []), "kind": h["kind"], "verified": h.get("verified")})
    clips.sort(key=lambda c: LEVEL_ORDER[c["level"]])  # a Candidate is never placed above Probable/Confirmed
    clips = clips[:10]
    count = None
    count_calls = [c for c in calls if c["name"] in ("count_events", "peak_occupancy") and "error" not in c["result"]]
    ref_call = next((c for c in count_calls if c["index"] == answer.count_ref), None)
    if ref_call is None and len(count_calls) == 1:
        ref_call = count_calls[0]
    if ref_call is not None:
        r = ref_call["result"]
        if ref_call["name"] == "count_events":
            rec = r.get("_receipts") or []
            th = _thumbs([x["track_id"] for x in rec[:48]], token)
            count = {"value": r["value"], "label": r["label"], "level": "confirmed", "series": r["series"],
                     "bucket": r.get("bucket", "hour"),
                     "receipts": [{**x, "thumb_url": th.get(x["track_id"]), "level": "confirmed"} for x in rec[:48]],
                     "receipts_total": len(rec), "receipt_ids": [x["track_id"] for x in rec[:2000]],
                     "receipt_times": [x["t"] for x in rec[:2000]]}
        else:
            rec = r.get("_receipts") or []
            th = _thumbs([x["track_id"] for x in rec[:48]], token)
            count = {"value": r["max"], "label": "most at the same time" + (f" ({r['at'][11:16]})" if r.get("at") else ""),
                     "level": "confirmed", "series": [], "bucket": "hour",
                     "receipts": [{**x, "thumb_url": th.get(x["track_id"]), "level": "confirmed"} for x in rec[:48]],
                     "receipts_total": len(rec), "receipt_ids": [x["track_id"] for x in rec[:2000]],
                     "receipt_times": [x["t"] for x in rec[:2000]]}
    rule = None
    for c in calls:
        if c["name"] == "create_rule" and isinstance(c["result"], dict) and c["result"].get("_draft"):
            d = c["result"]["_draft"]
            if answer.rule_id is None or d.get("rule_id") == answer.rule_id or rule is None:
                rule = d
    gaps: list[dict] = []
    for c in calls:
        if c["name"] == "camera_gaps" and isinstance(c["result"], dict):
            for g in c["result"].get("gaps", []):
                gaps.append({"camera_id": c["result"]["camera_id"], **g})
    # analytics tables + charts (data from the tool result, never from the model)
    tables, charts, images, notes = [], [], [], []
    by_index = {c["index"]: c for c in calls}
    for c in calls:
        r = c["result"] if isinstance(c["result"], dict) else {}
        if c["name"] == "analytics_query" and "rows" in r:
            tables.append({"title": r.get("title") or "Result", "columns": r["columns"], "rows": r["_all_rows"][:200],
                           "row_count": r["row_count"], "sql": r["sql"], "level": "confirmed", "call_index": c["index"]})
        elif c["name"] == "compare_periods" and "a" in r:
            tables.append({"title": r["label"], "columns": ["period", "value"],
                           "rows": [{"period": r["a"]["label"], "value": r["a"]["value"]},
                                    {"period": r["b"]["label"], "value": r["b"]["value"]}],
                           "row_count": 2, "sql": None, "level": "confirmed", "call_index": c["index"],
                           "change_pct": r.get("change_pct")})
        elif c["name"] in ("heatmap", "look_now") and r.get("image_key"):
            images.append({"url": storage.url(r["image_key"], token), "kind": c["name"], "camera_id": r.get("camera_id"),
                           "caption": r.get("vision_answer") or (f"{r.get('tracks', 0)} tracks" if c["name"] == "heatmap" else None)})
        elif c["name"] == "describe_clip" and r.get("description"):
            notes.append({"kind": "description", "text": r["description"], "ai_generated": True, "level": "candidate",
                          "camera_id": r.get("camera_id"), "from": r.get("from"), "to": r.get("to")})
    for ch in answer.charts[:3]:
        src = by_index.get(int(ch.get("call_index", -1)))
        if not src:
            continue
        t = next((t for t in tables if t["call_index"] == src["index"]), None)
        if not t or ch.get("x") not in t["columns"] or ch.get("y") not in t["columns"]:
            continue
        charts.append({"type": ch["type"], "title": ch["title"], "x": ch["x"], "y": ch["y"], "unit": ch.get("unit", ""),
                       "data": [{"x": row[ch["x"]], "y": row[ch["y"]]} for row in t["rows"][:100]]})
    journey_out = None
    for c in calls:
        if c["name"] == "journey" and isinstance(c["result"], dict) and c["result"].get("steps"):
            from .visual import with_urls

            j = dict(c["result"])
            j["steps"] = with_urls([dict(s) for s in j["steps"]], token)
            journey_out = j
    sec = []
    for c in calls:
        if c["name"] == "list_events" and isinstance(c["result"], dict):
            sec.extend(c["result"].get("events", []))
    report = next((c["result"] for c in calls if c["name"] == "make_report" and isinstance(c["result"], dict)
                   and c["result"].get("pdf_url")), None)
    taught = next((c["result"] for c in calls if c["name"] == "teach_object" and isinstance(c["result"], dict)
                   and c["result"].get("ok")), None)
    return {"clips": clips, "count": count, "rule": rule, "gaps": gaps, "tables": tables, "charts": charts,
            "images": images, "notes": notes, "journey": journey_out, "sec_events": sec, "report": report,
            "taught": taught}


def tts_name(ref: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", ref) + ".mp3"


_cache: dict[tuple, tuple[float, dict]] = {}
_cache_lock = threading.Lock()
CACHE_S = 60.0
ESCALATE_TOOLS = {"create_rule", "make_report", "teach_object"}


def _route(question: str, on_event, ref: str, camera_id: str | None, token: str | None):
    """Cheap model first; escalate to the agent model when it is unsure, fails, or the task changes state."""
    s = get_settings()
    fast = s.OPENAI_AGENT_FAST_MODEL or s.OPENAI_AGENT_MODEL
    if fast and fast != s.OPENAI_AGENT_MODEL:
        try:
            ans, calls = run_agent(question, camera_id, ref=ref, token=token, model=fast, on_event=on_event)
            errored = any(isinstance(c["result"], dict) and c["result"].get("error") for c in calls)
            if ans.confidence == "high" and not errored:
                return ans, calls, fast
            log.info("escalating to %s (confidence=%s, tool error=%s)", s.OPENAI_AGENT_MODEL, ans.confidence, errored)
            if on_event:
                on_event("reset", "")
        except Exception as e:
            log.warning("fast model failed (%s); escalating", e)
            if on_event:
                on_event("reset", "")
    ans, calls = run_agent(question, camera_id, ref=ref, token=token, model=s.OPENAI_AGENT_MODEL, on_event=on_event)
    return ans, calls, s.OPENAI_AGENT_MODEL


def ask(question: str, camera_id: str | None, *, token: str | None, transcript: str | None = None,
        input_kind: str = "text", t_start: float | None = None, ref: str | None = None,
        wait_audio: bool = False, on_event=None) -> dict:
    """Answer a question. The voice reply is synthesized in the background: the text answer returns as soon as the
    agent is done and `audio_url` points at /api/ask/audio/<name>, which waits until the mp3 is ready.
    on_event(kind, data) receives 'status', 'text' (reply deltas), 'reset' while the agent works (SSE)."""
    t0 = t_start or time.perf_counter()
    ref = ref or f"q:{uuid.uuid4().hex[:12]}"
    ckey = (" ".join(question.lower().split()), camera_id)
    with _cache_lock:
        hit = _cache.get(ckey)
    if hit and time.time() - hit[0] < CACHE_S and input_kind == "text":
        resp = dict(hit[1])
        resp["cached"] = True
        resp["latency_ms"] = int((time.perf_counter() - t0) * 1000)
        if on_event:
            on_event("text", resp["reply_text"])
        return resp
    first_text: dict[str, float] = {}

    def ev(kind, data):
        if kind == "text" and "t" not in first_text:
            first_text["t"] = time.perf_counter()
        if on_event:
            on_event(kind, data)

    answer, calls, model_used = _route(question, ev, ref, camera_id, token)
    lang = answer.language
    name = tts_name(ref)
    key = f"tts/{name}"
    qid_box: dict[str, int] = {}
    qid_ready = threading.Event()

    def do_tts():
        try:
            get_ai().tts(answer.reply_text, lang, out_path=storage.local_path(key), ref=ref)
            storage.put(storage.local_path(key), key)
        except Exception as e:
            log.warning("TTS failed: %s", e)
            try:
                storage.local_path(key + ".failed").write_text(str(e)[:200])
            except Exception:
                pass
            return
        if qid_ready.wait(timeout=60):
            try:
                total = float(db.fetch_val("SELECT COALESCE(sum(cost_usd),0) FROM usage WHERE ref=%s", (ref,)) or 0)
                db.execute("UPDATE queries SET cost_usd=%s, answer = answer || jsonb_build_object('audio_key', %s::text) "
                           "WHERE id=%s", (total, key, qid_box["id"]))
            except Exception as e:
                log.warning("could not update query audio: %s", e)

    th = threading.Thread(target=do_tts, daemon=True)
    th.start()  # TTS starts the moment the text is complete
    parts = assemble(answer, calls, token)
    if wait_audio:
        th.join(timeout=30)
    latency = int((time.perf_counter() - t0) * 1000)
    first_ms = int((first_text["t"] - t0) * 1000) if "t" in first_text else latency
    cost = float(db.fetch_val("SELECT COALESCE(sum(cost_usd),0) FROM usage WHERE ref=%s", (ref,)) or 0)
    base = get_settings().API_BASE_URL.rstrip("/")
    audio_url = f"{base}/api/ask/audio/{name}" + (f"?token={token}" if token else "")
    resp = {"query_id": 0, "transcript": transcript, "language": lang, "reply_text": answer.reply_text,
            "audio_url": audio_url, **parts, "followups": answer.followups[:3], "clarify": answer.clarify,
            "cost_usd": round(cost, 6), "cost_inr": round(cost * get_settings().USD_INR, 4), "latency_ms": latency,
            "first_text_ms": first_ms, "model": model_used}
    plan = [{"index": c["index"], "name": c["name"], "args": c["args"]} for c in calls]
    stored = {k: v for k, v in resp.items() if k != "audio_url"}
    qid = db.fetch_one("INSERT INTO queries(camera_id, input_kind, transcript, language, plan, answer, latency_ms, "
                       "cost_usd, model, first_text_ms) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                       (camera_id, input_kind, transcript or question, lang, Jsonb(plan), Jsonb(stored), latency, cost,
                        model_used, first_ms))["id"]
    qid_box["id"] = qid
    qid_ready.set()
    resp["query_id"] = qid
    if not parts.get("rule") and not parts.get("report") and not parts.get("taught"):
        with _cache_lock:
            _cache[ckey] = (time.time(), resp)
    return resp
