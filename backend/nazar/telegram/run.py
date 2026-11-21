"""Telegram bot (W8): talk to your CCTV in a messenger.   python -m nazar.telegram.run

Long polling (works on a laptop, no public URL). Pair from the web app: Settings -> code -> send /pair <code>.
Text or voice-note questions -> answer text + voice note (OGG/Opus) + up to 3 clips + a chart PNG + follow-up buttons.
Photo message = search by photo (caption = purpose, kept in the audit log). Alerts are pushed with snapshot, clip and
voice note; the morning digest at DIGEST_TIME. Everything sent is face-blurred.
"""
from __future__ import annotations

import asyncio
import io
import logging
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from ..core import db, storage
from ..core.config import ffmpeg_bin, get_settings
from ..core.logging import setup_logging
from ..core.timeutil import now_local, to_local

log = logging.getLogger("nazar.telegram")
RATE_PER_MIN = 10
MAX_VIDEO_MB = 18
_rate: dict[int, list[float]] = {}


# ---- helpers (sync; run in a thread) ------------------------------------------------------------------------------
def paired(chat_id: int) -> bool:
    allowed = {int(x) for x in get_settings().TELEGRAM_ALLOWED_CHAT_IDS.split(",") if x.strip().lstrip("-").isdigit()}
    return chat_id in allowed or db.fetch_one("SELECT 1 FROM telegram_chats WHERE chat_id=%s", (chat_id,)) is not None


def try_pair(chat_id: int, code: str, name: str | None) -> bool:
    row = db.fetch_one("SELECT v FROM kv WHERE k='tg_pair'")
    v = (row or {}).get("v") or {}
    if not v or v.get("code") != code.strip() or time.time() > float(v.get("exp", 0)):
        return False
    db.execute("INSERT INTO telegram_chats(chat_id, name) VALUES (%s,%s) ON CONFLICT (chat_id) DO UPDATE SET name=EXCLUDED.name",
               (chat_id, name))
    db.execute("DELETE FROM kv WHERE k='tg_pair'")
    return True


def to_ogg(mp3: Path) -> bytes | None:
    """Telegram voice notes must be OGG/Opus."""
    try:
        r = subprocess.run([ffmpeg_bin(), "-v", "error", "-i", str(mp3), "-c:a", "libopus", "-b:a", "32k", "-f", "ogg", "-"],
                           capture_output=True, timeout=60)
        return r.stdout if r.returncode == 0 and r.stdout else None
    except Exception:
        return None


def chart_png(series: list[dict], title: str) -> bytes | None:
    if len(series) < 2:
        return None
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    xs = [to_local(datetime.fromisoformat(p["t"])).strftime("%H:%M") for p in series]
    ys = [p["n"] for p in series]
    fig, ax = plt.subplots(figsize=(6, 2.6), dpi=130)
    fig.patch.set_facecolor("#0A0F1F")
    ax.set_facecolor("#0A0F1F")
    ax.bar(range(len(ys)), ys, color="#2F6BFF")
    step = max(1, len(xs) // 8)
    ax.set_xticks(range(0, len(xs), step), xs[::step], color="#8B96AD", fontsize=7)
    ax.tick_params(colors="#8B96AD", labelsize=7)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_title(title, color="#E7EBF3", fontsize=9, loc="left")
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()


def clip_file(track_id: int) -> Path | None:
    from ..api.clips import NoFootage, cut, track_window

    tr = db.fetch_one("SELECT id, camera_id, t_start, t_end FROM tracks WHERE id=%s", (track_id,))
    if not tr:
        return None
    try:
        c = cut(tr["camera_id"], *track_window(tr, max_s=20))
    except NoFootage:
        return None
    p = storage.local_path(c["key"])
    return p if p.exists() and p.stat().st_size < MAX_VIDEO_MB * 1024 * 1024 else None


def answer(text: str, ref: str) -> dict:
    from ..api.agent import ask

    return ask(text, None, token=None, input_kind="telegram", ref=ref, wait_audio=True)


# ---- bot ------------------------------------------------------------------------------------------------------------
def main() -> int:
    setup_logging("nazar.telegram")
    for noisy in ("apscheduler", "httpx", "telegram.ext"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    s = get_settings()
    if not s.TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN is not set - the Telegram bot is disabled (everything else works). "
              "Create a bot with @BotFather and put the token in .env.")
        return 0
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Update
    from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler,
                              filters)

    def limited(chat_id: int) -> bool:
        now = time.time()
        q = [t for t in _rate.get(chat_id, []) if now - t < 60]
        _rate[chat_id] = q + [now]
        return len(q) >= RATE_PER_MIN

    async def guard(update: Update) -> bool:
        cid = update.effective_chat.id
        if not await asyncio.to_thread(paired, cid):
            await update.effective_message.reply_text(
                "Namaste! Is chat ko Nazar se jodne ke liye web app mein Settings → Telegram pe code lijiye aur yahan bhejiye: "
                "/pair 123456\n(Open Nazar Settings to get your pairing code.)")
            return False
        if limited(cid):
            await update.effective_message.reply_text("Thoda ruk jaiye — a lot of questions in one minute. Try again shortly.")
            return False
        return True

    async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "Nazar — apne CCTV se kuch bhi poochiye.\n• Text ya voice note bhejiye: \"kal raat counter pe kitne log aaye?\"\n"
            "• Photo bhejiye (bag, jacket, gaadi) → har camera pe dhundhega\n• /cameras  /today  /report <alert id>\n"
            "Pehle Settings se code lekar /pair <code> bhejiye.")

    async def pair(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        code = (ctx.args or [""])[0]
        u = update.effective_user
        ok = await asyncio.to_thread(try_pair, update.effective_chat.id, code, (u.full_name if u else None))
        await update.message.reply_text("Jud gaya! ✅ Alerts aur jawab ab yahan aayenge." if ok else
                                        "Code galat ya purana hai. Settings se naya code lijiye.")

    async def cameras(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await guard(update):
            return
        rows = await asyncio.to_thread(db.fetch_all, "SELECT id, name, kind FROM cameras ORDER BY name")
        await update.message.reply_text("\n".join(f"• {r['name']} ({r['kind']})" for r in rows) or "No cameras yet.")

    async def send_answer(update: Update, res: dict):
        msg = update.effective_message
        kb = None
        if res.get("followups"):
            kb = InlineKeyboardMarkup([[InlineKeyboardButton(f[:60], callback_data=f"q:{f[:56]}")] for f in res["followups"][:3]])
        cnt = res.get("count")
        head = res["reply_text"]
        if cnt:
            head += f"\n\n{cnt['value']} · {cnt['label']} (Confirmed, from tracker records)"
        await msg.reply_text(head, reply_markup=kb)
        if cnt and cnt.get("series"):
            png = await asyncio.to_thread(chart_png, cnt["series"], cnt["label"])
            if png:
                await msg.reply_photo(png)
        audio = storage.local_path(f"tts/{res['audio_url'].rsplit('/', 1)[-1].split('?')[0]}") if res.get("audio_url") else None
        if audio and audio.exists():
            ogg = await asyncio.to_thread(to_ogg, audio)
            if ogg:
                await msg.reply_voice(ogg)
        tids = [c["track_id"] for c in res.get("clips", []) if c.get("track_id")][:3]
        if not tids and cnt and cnt.get("receipt_ids"):
            tids = cnt["receipt_ids"][:2]
        for tid in tids:
            p = await asyncio.to_thread(clip_file, tid)
            lvl = next((c["level"] for c in res.get("clips", []) if c.get("track_id") == tid), "confirmed")
            if p:
                with open(p, "rb") as f:
                    await msg.reply_video(f, caption=f"{lvl.capitalize()} · faces blurred", supports_streaming=True)
        if res.get("report", {}) and res["report"].get("pdf_key"):
            with open(storage.local_path(res["report"]["pdf_key"]), "rb") as f:
                await msg.reply_document(f, filename=f"nazar_report_{res['report']['report_id']}.pdf")

    async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE, text: str | None = None):
        if not await guard(update):
            return
        q = text or update.effective_message.text
        await update.effective_chat.send_action("typing")
        try:
            res = await asyncio.to_thread(answer, q, f"tg:{uuid.uuid4().hex[:10]}")
        except Exception as e:
            log.exception("answer failed")
            await update.effective_message.reply_text(f"Maaf kijiye, jawab nahi bana: {str(e)[:120]}")
            return
        await send_answer(update, res)

    async def on_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await guard(update):
            return
        from ..api import voice

        f = await (update.message.voice or update.message.audio).get_file()
        path = storage.local_path(f"uploads/voice/tg_{uuid.uuid4().hex}.ogg")
        path.parent.mkdir(parents=True, exist_ok=True)
        await f.download_to_drive(str(path))
        ref = f"tg:{uuid.uuid4().hex[:10]}"
        text, _lang, _s = await asyncio.to_thread(voice.transcribe, path, None, ref)
        if not text.strip():
            await update.message.reply_text("Awaaz saaf nahi aayi — phir se bhejiye.")
            return
        await update.message.reply_text(f"🎙️ “{text}”")
        await on_text(update, ctx, text)

    async def on_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await guard(update):
            return
        from ..api import visual
        from ..api.routes_visual import _blur_photo
        from psycopg.types.json import Jsonb

        f = await update.message.photo[-1].get_file()
        data = bytes(await f.download_as_bytearray())
        purpose = (update.message.caption or "").strip()[:300] or None
        try:
            jpeg, face_only = await asyncio.to_thread(_blur_photo, data, None)
        except Exception:
            await update.message.reply_text("Photo padh nahi paaya.")
            return
        if face_only:
            await update.message.reply_text("Nazar chehre se kisi ko nahi dhundhta (no face recognition). Kapde, bag ya gaadi ki photo bhejiye.")
            return
        key = f"photo_searches/tg_{uuid.uuid4().hex}.jpg"
        storage.put_bytes(jpeg, key)
        now = datetime.now().astimezone()
        hits = await asyncio.to_thread(lambda: visual.search(visual.query_vector(image_jpeg=jpeg), t_from=now - timedelta(days=7),
                                                             t_to=now, limit=6, mode="photo"))
        await asyncio.to_thread(db.execute, "INSERT INTO photo_searches(purpose, image_key, params, result_count) VALUES (%s,%s,%s,%s)",
                                (purpose, key, Jsonb({"via": "telegram"}), len(hits)))
        if not hits:
            await update.message.reply_text("Kahin milta-julta nahi mila.")
            return
        media = []
        for h in hits[:4]:
            p = storage.local_path(h["thumb_key"]) if h.get("thumb_key") else None
            if p and p.exists():
                media.append(InputMediaPhoto(p.read_bytes(), caption=f"{h['camera_id']} · {to_local(datetime.fromisoformat(h['t'])):%d %b %H:%M} · "
                                                                    f"{h['level']} (sim {h['sim']:.2f})"))
        await update.message.reply_text(f"{len(hits)} milte-julte pal mile (Candidate — clothes/objects only, no faces). Top:")
        if media:
            await update.message.reply_media_group(media)

    async def report(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await guard(update):
            return
        try:
            aid = int((ctx.args or ["0"])[0])
        except ValueError:
            aid = 0
        if not aid:
            aid = (await asyncio.to_thread(db.fetch_val, "SELECT max(id) FROM alerts")) or 0
        if not aid:
            await update.message.reply_text("Koi alert nahi mila.")
            return
        from ..api.reports import create_report

        await update.message.reply_text("Report bana raha hoon…")
        r = await asyncio.to_thread(lambda: create_report(title=f"Alert #{aid}", alert_id=aid, language="en"))
        with open(storage.local_path(r["pdf_key"]), "rb") as f:
            await update.message.reply_document(f, filename=f"nazar_report_{r['report_id']}.pdf",
                                                caption=f"Manifest SHA-256 {r['manifest_sha256'][:16]}…")

    async def today(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await guard(update):
            return
        from ..worker.security import digest

        d = await asyncio.to_thread(digest)
        await update.message.reply_text(d["text"])

    async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        if q.data.startswith("q:"):
            await on_text(update, ctx, q.data[2:])

    # ---- pushes: alerts + digest ----------------------------------------------------------------------------------
    state = {"last_alert": None, "digest_day": None}

    async def push(ctx: ContextTypes.DEFAULT_TYPE):
        if state["last_alert"] is None:
            state["last_alert"] = await asyncio.to_thread(db.fetch_val, "SELECT COALESCE(max(id),0) FROM alerts")
        rows = await asyncio.to_thread(db.fetch_all, "SELECT a.*, c.name AS cam FROM alerts a JOIN cameras c ON c.id=a.camera_id "
                                       "WHERE a.id > %s AND (a.vision_confirmed IS DISTINCT FROM false) ORDER BY a.id", (state["last_alert"],))
        chats = await asyncio.to_thread(db.fetch_all, "SELECT chat_id FROM telegram_chats WHERE alerts")
        for a in rows:
            state["last_alert"] = a["id"]
            if (datetime.now().astimezone() - a["created_at"]).total_seconds() > 600:
                continue
            for c in chats:
                cid = c["chat_id"]
                try:
                    cap = f"🚨 {a['cam']}: {a['message']}"
                    snap = storage.local_path(a["snapshot_key"]) if a["snapshot_key"] else None
                    if snap and snap.exists():
                        await ctx.bot.send_photo(cid, snap.read_bytes(), caption=cap)
                    else:
                        await ctx.bot.send_message(cid, cap)
                    if a["audio_key"] and storage.local_path(a["audio_key"]).exists():
                        ogg = await asyncio.to_thread(to_ogg, storage.local_path(a["audio_key"]))
                        if ogg:
                            await ctx.bot.send_voice(cid, ogg)
                    p = await asyncio.to_thread(clip_file, (a["meta"] or {}).get("actor_track_id") or a["track_id"])
                    if p:
                        with open(p, "rb") as f:
                            await ctx.bot.send_video(cid, f, caption="Clip (faces blurred) · /report " + str(a["id"]))
                except Exception as e:
                    log.warning("push to %s failed: %s", cid, e)
        # morning digest
        now = now_local()
        hh, mm = (get_settings().DIGEST_TIME or "08:00").split(":")
        if now.strftime("%H:%M") >= f"{int(hh):02d}:{int(mm):02d}" and state["digest_day"] != now.date():
            state["digest_day"] = now.date()
            if now.hour < int(hh) + 2:
                from ..worker.security import digest

                d = await asyncio.to_thread(digest)
                for c in chats:
                    try:
                        await ctx.bot.send_message(c["chat_id"], "☀️ " + d["text"])
                    except Exception as e:
                        log.warning("digest to %s failed: %s", c["chat_id"], e)

    app = Application.builder().token(s.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("pair", pair))
    app.add_handler(CommandHandler("cameras", cameras))
    app.add_handler(CommandHandler("today", today))
    app.add_handler(CommandHandler("report", report))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    if app.job_queue is not None:
        app.job_queue.run_repeating(push, interval=3, first=3)
    else:
        log.warning("job queue unavailable (pip install 'python-telegram-bot[job-queue]'); alerts will not be pushed")
    log.info("telegram bot running (long polling)")
    app.run_polling(drop_pending_updates=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
