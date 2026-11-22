"""Telegram self-test (v3 P1.8b). If a chat is paired: sends it the latest alert (snapshot + voice note + clip) and the
digest through the real bot and prints the Telegram message ids. If not: prints the exact pairing steps.

    python scripts/telegram_selftest.py           -> data/eval/telegram_selftest.json
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from nazar.core import db  # noqa: E402
from nazar.core.config import get_settings  # noqa: E402


def main() -> int:
    s = get_settings()
    out = s.data_dir / "eval" / "telegram_selftest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    if not s.TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN is not set - nothing to test.")
        return 1
    chats = db.fetch_all("SELECT chat_id, name FROM telegram_chats ORDER BY paired_at DESC NULLS LAST") \
        if db.fetch_val("SELECT 1 FROM information_schema.columns WHERE table_name='telegram_chats' AND column_name='paired_at'") \
        else db.fetch_all("SELECT chat_id, name FROM telegram_chats")
    from telegram import Bot

    async def run() -> dict:
        bot = Bot(s.TELEGRAM_BOT_TOKEN)
        me = await bot.get_me()
        res = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "bot": f"@{me.username}", "chats": []}
        if not chats:
            res["paired"] = False
            return res
        import nazar.telegram.run as tg
        from nazar.worker.security import digest

        a = db.fetch_one("SELECT a.*, c.name AS cam FROM alerts a JOIN cameras c ON c.id=a.camera_id ORDER BY a.id DESC LIMIT 1")
        d = digest()
        for c in chats:
            ids = await tg.send_alert(bot, c["chat_id"], a) if a else []
            m = await bot.send_message(c["chat_id"], "☀️ (self-test) " + d["text"])
            res["chats"].append({"chat": c.get("name") or "paired chat", "alert_message_ids": ids, "digest_message_id": m.message_id})
        res["paired"] = True
        return res

    res = asyncio.run(run())
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    if not res["paired"]:
        print(f"Bot {res['bot']} is reachable, but no chat is paired yet. To pair (2 minutes):\n"
              "  1. Open the web app -> Settings -> Telegram -> 'Get pairing code' (6 digits, valid 10 minutes).\n"
              f"  2. In Telegram open {res['bot']} and send:  /pair <code>   -> it replies 'Jud gaya!'.\n"
              "  3. Run this script again: it sends you the latest alert (snapshot, voice note, clip) and the digest.")
        return 2
    for c in res["chats"]:
        print(f"sent to {c['chat']}: alert messages {c['alert_message_ids']}, digest message {c['digest_message_id']}")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
