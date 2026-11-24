"""Nazar toolbox: a small MCP server that ships with Nazar, so the investigator has useful outside tools with no
extra install.  Run by the hub from mcp.servers.json:  python -m nazar.agentic.toolbox

Read-only (run on their own):  weather, find_place, list_case_notes, read_case_note, configured_channels
Need the owner's approval:     send_telegram (paired chats only), send_webhook (Slack / Discord / any incoming
                               webhook), save_case_note (a file in Nazar's export folder)
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import date, datetime, timedelta

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

READ = ToolAnnotations(read_only_hint=True, open_world_hint=True)
SEND = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=True)
app = MCPServer("nazar-toolbox", title="Nazar toolbox", version="0.1.0")
UA = {"User-Agent": "nazar-toolbox/0.1"}
WMO = {0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "fog", 51: "light drizzle",
       53: "drizzle", 55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain", 71: "light snow", 73: "snow",
       75: "heavy snow", 80: "rain showers", 81: "rain showers", 82: "violent rain showers", 95: "thunderstorm",
       96: "thunderstorm with hail", 99: "thunderstorm with hail"}


def _env(name: str) -> str:
    """A setting from the environment or the repo .env (the hub does not pass Nazar's environment to servers)."""
    v = os.environ.get(name, "").strip()
    if v:
        return v
    try:
        from dotenv import dotenv_values

        from ..core.config import ENV_FILE

        return (dotenv_values(ENV_FILE).get(name) or "").strip()
    except Exception:
        return ""


def _geocode(place: str) -> dict | None:
    r = httpx.get("https://geocoding-api.open-meteo.com/v1/search", params={"name": place, "count": 1, "language": "en"},
                  headers=UA, timeout=15)
    r.raise_for_status()
    res = (r.json().get("results") or [None])[0]
    if not res:
        return None
    return {"name": ", ".join(x for x in (res.get("name"), res.get("admin1"), res.get("country")) if x),
            "latitude": res["latitude"], "longitude": res["longitude"], "timezone": res.get("timezone")}


@app.tool(annotations=READ)
def find_place(place: str) -> dict:
    """Look up a town or city: full name, latitude, longitude, timezone (Open-Meteo geocoding, no key)."""
    return _geocode(place) or {"error": f"no place found for '{place}'"}


@app.tool(annotations=READ)
def weather(place: str, day: str | None = None) -> dict:
    """Hourly weather (temperature, rain in mm, conditions) for a town on a day (YYYY-MM-DD, default today), from
    Open-Meteo. Covers the last ~90 days and the next 7. Use it to explain footage: rain, fog or darkness change how
    many people come and what the camera can see."""
    loc = _geocode(place)
    if not loc:
        return {"error": f"no place found for '{place}'"}
    try:
        d = date.fromisoformat(day) if day else date.today()
    except ValueError:
        return {"error": "day must be YYYY-MM-DD"}
    back = (date.today() - d).days
    if back > 92 or back < -7:
        return {"error": "only the last ~90 days and the next 7 are available"}
    r = httpx.get("https://api.open-meteo.com/v1/forecast", headers=UA, timeout=20, params={
        "latitude": loc["latitude"], "longitude": loc["longitude"], "timezone": "auto",
        "hourly": "temperature_2m,precipitation,weather_code,visibility", "daily": "sunrise,sunset",
        "start_date": d.isoformat(), "end_date": d.isoformat()})
    r.raise_for_status()
    j = r.json()
    h = j.get("hourly") or {}
    hours = [{"time": t[11:16], "temp_c": h["temperature_2m"][i], "rain_mm": h["precipitation"][i],
              "sky": WMO.get(h["weather_code"][i], str(h["weather_code"][i])),
              "visibility_m": (h.get("visibility") or [None] * len(h["time"]))[i]}
             for i, t in enumerate(h.get("time") or [])]
    daily = j.get("daily") or {}
    return {"place": loc["name"], "day": d.isoformat(), "timezone": j.get("timezone"),
            "sunrise": (daily.get("sunrise") or [""])[0][11:16], "sunset": (daily.get("sunset") or [""])[0][11:16],
            "rain_total_mm": round(sum(x["rain_mm"] or 0 for x in hours), 1), "hours": hours}


@app.tool(annotations=SEND)
def send_telegram(text: str) -> dict:
    """Send a text message to the owner's paired Telegram chats (the ones paired in Nazar's settings - no other chat
    can be addressed). Say how sure each fact is."""
    token = _env("TELEGRAM_BOT_TOKEN")
    if not token:
        return {"error": "TELEGRAM_BOT_TOKEN is not set"}
    from ..core import db

    chats = [r["chat_id"] for r in db.fetch_all("SELECT chat_id FROM telegram_chats")]
    if not chats:
        return {"error": "no paired Telegram chat - pair one in Settings first"}
    sent = 0
    for chat in chats:
        r = httpx.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=20,
                       json={"chat_id": chat, "text": text[:4000], "disable_web_page_preview": True})
        sent += 1 if r.status_code == 200 else 0
    return {"sent_to": sent, "chats": len(chats)}


WEBHOOKS = {"slack": "SLACK_WEBHOOK_URL", "discord": "DISCORD_WEBHOOK_URL", "custom": "NAZAR_WEBHOOK_URL"}


@app.tool(annotations=SEND)
def send_webhook(target: str, text: str) -> dict:
    """Post a text message to a channel the owner configured: target = slack | discord | custom (incoming-webhook URLs
    from .env: SLACK_WEBHOOK_URL, DISCORD_WEBHOOK_URL, NAZAR_WEBHOOK_URL). Say how sure each fact is."""
    env = WEBHOOKS.get(target)
    if not env:
        return {"error": "target must be slack, discord or custom"}
    url = _env(env)
    if not url.startswith("https://"):
        return {"error": f"{env} is not set"}
    body = {"content": text[:1900]} if target == "discord" else {"text": text[:3500]}
    r = httpx.post(url, json=body, timeout=20)
    return {"ok": r.status_code < 300, "status": r.status_code}


def _notes_dir():
    from ..core.config import get_settings

    d = get_settings().data_dir / "exports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _note_path(name: str):
    import re

    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", name.strip())[:80].strip("._") or "note"
    return _notes_dir() / (stem if stem.endswith((".md", ".txt")) else stem + ".md")


@app.tool(annotations=READ)
def list_case_notes() -> dict:
    """Notes and case summaries saved in Nazar's export folder (newest first)."""
    files = sorted((p for p in _notes_dir().iterdir() if p.suffix in (".md", ".txt")), key=lambda p: -p.stat().st_mtime)
    return {"folder": str(_notes_dir()), "notes": [{"name": p.name, "bytes": p.stat().st_size,
                                                    "modified": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="minutes")}
                                                   for p in files[:50]]}


@app.tool(annotations=READ)
def read_case_note(name: str) -> dict:
    """Read one saved note from the export folder."""
    p = _note_path(name)
    if not p.exists():
        return {"error": f"no note named {p.name}"}
    return {"name": p.name, "text": p.read_text(encoding="utf-8")[:20000]}


@app.tool(annotations=SEND)
def save_case_note(name: str, text: str) -> dict:
    """Save a text/Markdown note (a case summary, a shift handover) in Nazar's export folder on the owner's machine.
    Never overwrites: an existing name gets a number added."""
    p = _note_path(name)
    n = 2
    while p.exists():
        p = p.with_name(f"{p.stem.rsplit('-', 1)[0] if n > 2 else p.stem}-{n}{p.suffix}")
        n += 1
    p.write_text(text[:200000], encoding="utf-8")
    return {"saved": str(p), "bytes": p.stat().st_size}


@app.tool(annotations=READ)
def configured_channels() -> dict:
    """Which outgoing channels are set up (Telegram bot, Slack / Discord / custom webhook). No secrets are returned."""
    return {"telegram": bool(_env("TELEGRAM_BOT_TOKEN")),
            **{k: _env(v).startswith("https://") for k, v in WEBHOOKS.items()},
            "now": datetime.now().astimezone().isoformat(timespec="minutes"),
            "yesterday": (date.today() - timedelta(days=1)).isoformat()}


if __name__ == "__main__":
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    app.run("stdio")
