"""Query agent (Responses API + strict function tools) and the rule compiler.

The model plans and words the reply. Facts (counts, clips, levels) come only from server-side tool results:
the server assembles AskResponse from those results, and the model cannot set or change an evidence level.
"""
from __future__ import annotations

import json
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
- Counts come ONLY from count_events (or peak_occupancy for "how crowded / sabse zyada bheed"). Use event "present"
  for "how many people came/were seen" on a camera, and event "enter" with a zone for "how many came to <zone>".
- Descriptions ("red shirt", "laal shirt", "carrying a box", "helmet wala") go to search_tracks with structured
  attributes (colours, carrying, headwear words in text, vehicle) AND a short English `text` describing the person.
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
- In the final JSON: show_track_ids = up to 6 track ids taken from search_tracks results that best answer the
  question (empty if none); count_ref = the index of the count_events/peak_occupancy call whose number you quote,
  else null; rule_id from create_rule, else null; followups = up to 3 short follow-up questions in the same language.
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
            "event": _nullable("string", enum=["enter", "exit", "dwell", "present"]),
            "time_from": {"type": "string"},
            "time_to": {"type": "string"},
            "bucket": _nullable("string", enum=["hour", "15min"]),
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
    },
    "required": ["reply_text", "language", "show_track_ids", "count_ref", "rule_id", "followups"],
    "additionalProperties": False,
}


class AgentAnswer(BaseModel):
    reply_text: str
    language: Literal["hi", "en", "hinglish"]
    show_track_ids: list[int] = []
    count_ref: int | None = None
    rule_id: int | None = None
    followups: list[str] = []


# ------------------------------------------------------------------------------------------------ context
def camera_context(selected: str | None) -> str:
    cov = {c["camera_id"]: c for c in agent_tools.coverage()}
    lines = []
    for r in db.fetch_all("SELECT id, name, kind, zones FROM cameras ORDER BY created_at"):
        zones = ", ".join(f"{z['name']} ({z.get('label', z['name'])})" for z in (r["zones"] or [])) or "no zones"
        c = cov.get(r["id"])
        span = f"{c['from'][:16]} to {c['to'][:16]}" if c else "no footage yet"
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
    last = db.fetch_val("SELECT max(t_end) FROM segments WHERE camera_id=%s", (camera_id,))
    if last is not None and last < t_from:
        first = db.fetch_val("SELECT min(t_start) FROM segments WHERE camera_id=%s", (camera_id,))
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
                            max_output_tokens=600)
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
        return agent_tools.search_tracks(a, ref=ref)
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
    return {"error": f"unknown tool {name}"}


def _item_dict(item: Any) -> dict:
    if hasattr(item, "model_dump"):
        d = item.model_dump(exclude_none=True)
    else:
        d = dict(item)
    if d.get("type") == "function_call":
        return {"type": "function_call", "call_id": d["call_id"], "name": d["name"], "arguments": d["arguments"]}
    return d


def run_agent(question: str, camera_id: str | None, *, ref: str, token: str | None) -> tuple[AgentAnswer, list[dict]]:
    ai = get_ai()
    model = get_settings().OPENAI_AGENT_MODEL
    inp: list[dict] = [{"role": "developer", "content": camera_context(camera_id)},
                       {"role": "user", "content": question}]
    calls: list[dict] = []
    text_fmt = {"format": {"type": "json_schema", "name": "agent_answer", "schema": ANSWER_SCHEMA, "strict": True}}
    for rnd in range(MAX_ROUNDS + 1):
        last = rnd == MAX_ROUNDS
        resp, _ = ai.agent_step(model=model, input=inp, tools=None if last else TOOLS, instructions=AGENT_SYSTEM,
                                text=text_fmt, ref=ref, camera_id=camera_id)
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
        for fc in fcalls:
            try:
                args = json.loads(fc.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            try:
                result = _exec_tool(fc.name, args, ref, token)
            except Exception as e:
                log.warning("tool %s failed: %s", fc.name, e)
                result = {"error": str(e)[:300]}
            idx = len(calls)
            calls.append({"index": idx, "name": fc.name, "args": args, "result": result})
            model_view = {k: v for k, v in result.items() if k != "_draft"} if isinstance(result, dict) else result
            inp.append({"type": "function_call_output", "call_id": fc.call_id,
                        "output": json.dumps({"tool_call_index": idx, **model_view}, default=str)[:20000]})
    raise RuntimeError("agent did not finish")


def assemble(answer: AgentAnswer, calls: list[dict], token: str | None) -> dict:
    """Build the response from SERVER tool results only. Levels are copied from the server, never from the model."""
    found: dict[int, dict] = {}
    for c in calls:
        if c["name"] == "search_tracks" and isinstance(c["result"], dict):
            for r in c["result"].get("results", []):
                found.setdefault(r["track_id"], r)
    clips = []
    for tid in answer.show_track_ids[:6]:
        r = found.get(int(tid))
        if not r:
            continue  # the model may only show tracks a tool actually returned
        keys = (db.fetch_one("SELECT crop_keys FROM tracks WHERE id=%s", (r["track_id"],)) or {}).get("crop_keys") or []
        clips.append({"track_id": r["track_id"], "camera_id": r["camera_id"], "cls": r["cls"], "t_start": r["t_start"],
                      "t_end": r["t_end"], "level": r["level"], "why": r["why"], "caption": r.get("caption"),
                      "thumb_url": storage.url(keys[0], token) if keys else None, "score": r.get("score", 0.0),
                      "zones": r.get("zones", [])})
    clips.sort(key=lambda c: LEVEL_ORDER[c["level"]])  # a Candidate is never placed above Probable/Confirmed
    count = None
    count_calls = [c for c in calls if c["name"] in ("count_events", "peak_occupancy") and "error" not in c["result"]]
    ref_call = next((c for c in count_calls if c["index"] == answer.count_ref), None)
    if ref_call is None and len(count_calls) == 1:
        ref_call = count_calls[0]
    if ref_call is not None:
        r = ref_call["result"]
        if ref_call["name"] == "count_events":
            count = {"value": r["value"], "label": r["label"], "level": "confirmed", "series": r["series"],
                     "bucket": r.get("bucket", "hour")}
        else:
            count = {"value": r["max"], "label": "most at the same time" + (f" ({r['at'][11:16]})" if r.get("at") else ""),
                     "level": "confirmed", "series": [], "bucket": "hour"}
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
    return {"clips": clips, "count": count, "rule": rule, "gaps": gaps}


def ask(question: str, camera_id: str | None, *, token: str | None, transcript: str | None = None,
        input_kind: str = "text", t_start: float | None = None, ref: str | None = None) -> dict:
    t0 = t_start or time.perf_counter()
    ref = ref or f"q:{uuid.uuid4().hex[:12]}"
    answer, calls = run_agent(question, camera_id, ref=ref, token=token)
    lang = answer.language
    audio: dict[str, Any] = {}

    def do_tts():
        try:
            p = get_ai().tts(answer.reply_text, lang, ref=ref)
            audio["key"] = storage.put(p, f"tts/{p.name}")
        except Exception as e:
            log.warning("TTS failed: %s", e)

    th = threading.Thread(target=do_tts, daemon=True)
    th.start()
    parts = assemble(answer, calls, token)
    th.join(timeout=20)
    latency = int((time.perf_counter() - t0) * 1000)
    cost = float(db.fetch_val("SELECT COALESCE(sum(cost_usd),0) FROM usage WHERE ref=%s", (ref,)) or 0)
    resp = {"query_id": 0, "transcript": transcript, "language": lang, "reply_text": answer.reply_text,
            "audio_url": storage.url(audio.get("key"), token), "count": parts["count"], "clips": parts["clips"],
            "rule": parts["rule"], "gaps": parts["gaps"], "followups": answer.followups[:3], "cost_usd": round(cost, 6),
            "latency_ms": latency}
    plan = [{"index": c["index"], "name": c["name"], "args": c["args"]} for c in calls]
    stored = {k: v for k, v in resp.items() if k != "audio_url"} | {"audio_key": audio.get("key")}
    qid = db.fetch_one("INSERT INTO queries(camera_id, input_kind, transcript, language, plan, answer, latency_ms, cost_usd) "
                       "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                       (camera_id, input_kind, transcript or question, lang, Jsonb(plan), Jsonb(stored), latency, cost))["id"]
    resp["query_id"] = qid
    return resp
