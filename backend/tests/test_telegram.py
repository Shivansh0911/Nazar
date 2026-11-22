"""Telegram bot offline tests (v3 P1.8a): the real handlers, driven with constructed Update/Context objects that record
every reply, against the dev database and the real agent. No Telegram network calls. Text/voice/report need OpenAI."""
import asyncio
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from nazar.core import db

pytestmark = pytest.mark.db
ROOT = Path(__file__).resolve().parents[2]
CHAT = -987654321


class Rec:
    """Records every reply the bot makes."""

    def __init__(self):
        self.calls: list[tuple[str, object]] = []
        self._id = 100

    def _add(self, kind, payload):
        self.calls.append((kind, payload))
        self._id += 1
        return SimpleNamespace(message_id=self._id)

    def kinds(self):
        return [k for k, _ in self.calls]

    def texts(self):
        return " | ".join(str(p) for k, p in self.calls if k == "text")


def make_update(rec: Rec, *, text=None, voice_path=None, photo_bytes=None, caption=None):
    async def reply_text(t, **kw):
        return rec._add("text", t)

    async def reply_photo(p, **kw):
        return rec._add("photo", p)

    async def reply_voice(v, **kw):
        return rec._add("voice", v)

    async def reply_video(f, **kw):
        return rec._add("video", f.read() if hasattr(f, "read") else f)

    async def reply_document(f, **kw):
        return rec._add("document", f.read() if hasattr(f, "read") else f)

    async def reply_media_group(m, **kw):
        return rec._add("media_group", m)

    async def send_action(a):
        return None

    voice = None
    if voice_path:
        async def download_to_drive(path):
            Path(path).write_bytes(Path(voice_path).read_bytes())

        async def get_file_v():
            return SimpleNamespace(download_to_drive=download_to_drive)

        voice = SimpleNamespace(get_file=get_file_v)
    photo = None
    if photo_bytes:
        async def download_as_bytearray():
            return bytearray(photo_bytes)

        async def get_file_p():
            return SimpleNamespace(download_as_bytearray=download_as_bytearray)

        photo = [SimpleNamespace(get_file=get_file_p)]
    msg = SimpleNamespace(text=text, caption=caption, voice=voice, audio=None, photo=photo, reply_text=reply_text,
                          reply_photo=reply_photo, reply_voice=reply_voice, reply_video=reply_video,
                          reply_document=reply_document, reply_media_group=reply_media_group)
    return SimpleNamespace(message=msg, effective_message=msg, effective_chat=SimpleNamespace(id=CHAT, send_action=send_action),
                           effective_user=SimpleNamespace(full_name="pytest"), callback_query=None)


@pytest.fixture(scope="module")
def bot():
    import nazar.telegram.run as tg

    db.execute("DELETE FROM telegram_chats WHERE chat_id=%s", (CHAT,))
    yield tg
    db.execute("DELETE FROM telegram_chats WHERE chat_id=%s", (CHAT,))


def run(coro):
    return asyncio.run(coro)


def _pair_code(code="424242"):
    from psycopg.types.json import Jsonb

    db.execute("INSERT INTO kv(k, v) VALUES ('tg_pair', %s) ON CONFLICT (k) DO UPDATE SET v=EXCLUDED.v",
               (Jsonb({"code": code, "exp": time.time() + 600}),))
    return code


def test_unpaired_chat_is_asked_to_pair(bot):
    rec = Rec()
    run(bot.cameras(make_update(rec), SimpleNamespace(args=[])))
    assert "/pair" in rec.texts()


def test_pairing_wrong_then_right_code(bot):
    _pair_code("424242")
    rec = Rec()
    run(bot.pair(make_update(rec), SimpleNamespace(args=["000000"])))
    assert "galat" in rec.texts()
    run(bot.pair(make_update(rec), SimpleNamespace(args=["424242"])))
    assert "Jud gaya" in rec.texts()
    assert db.fetch_one("SELECT 1 FROM telegram_chats WHERE chat_id=%s", (CHAT,))
    # a code works once
    run(bot.pair(make_update(rec), SimpleNamespace(args=["424242"])))
    assert rec.texts().count("galat") == 2


def test_start_and_cameras(bot):
    bot._rate.clear()
    rec = Rec()
    run(bot.start(make_update(rec), SimpleNamespace(args=[])))
    run(bot.cameras(make_update(rec), SimpleNamespace(args=[])))
    assert "/pair" in rec.calls[0][1] and "Office desk" in rec.texts()


def test_today_digest(bot):
    bot._rate.clear()
    rec = Rec()
    run(bot.today(make_update(rec), SimpleNamespace(args=[])))
    assert rec.kinds() == ["text"] and len(rec.calls[0][1]) > 20


def test_photo_search_sends_candidates(bot):
    bot._rate.clear()
    rec = Rec()
    photo = (ROOT / "demo" / "bag_photo.jpg").read_bytes()
    run(bot.on_photo(make_update(rec, photo_bytes=photo, caption="lost bag (pytest)"), SimpleNamespace(args=[])))
    assert "milte-julte" in rec.texts() or "nahi mila" in rec.texts()
    assert db.fetch_one("SELECT 1 FROM photo_searches WHERE purpose='lost bag (pytest)'")


def test_rate_limit(bot):
    bot._rate.clear()
    rec = Rec()
    for _ in range(bot.RATE_PER_MIN + 1):
        run(bot.cameras(make_update(rec), SimpleNamespace(args=[])))
    assert "ruk jaiye" in rec.texts()
    bot._rate.clear()


class FakeBot:
    def __init__(self, rec):
        self.rec = rec

    async def send_photo(self, cid, p, caption=None):
        return self.rec._add("photo", caption)

    async def send_message(self, cid, t):
        return self.rec._add("text", t)

    async def send_voice(self, cid, v):
        return self.rec._add("voice", v)

    async def send_video(self, cid, f, caption=None):
        return self.rec._add("video", caption)


def test_alert_push_sends_snapshot_voice_and_clip(bot):
    a = db.fetch_one("SELECT a.*, c.name AS cam FROM alerts a JOIN cameras c ON c.id=a.camera_id "
                     "WHERE a.snapshot_key IS NOT NULL ORDER BY a.id DESC LIMIT 1")
    if not a:
        pytest.skip("no alert yet - run scripts/live_alert_test.py")
    rec = Rec()
    ids = run(bot.send_alert(FakeBot(rec), CHAT, a))
    assert rec.kinds()[0] == "photo" and "🚨" in rec.calls[0][1]
    assert "voice" in rec.kinds() and len(ids) == len(rec.calls)
    voice = next(p for k, p in rec.calls if k == "voice")
    assert voice[:4] == b"OggS"


@pytest.mark.live
def test_text_question_gets_text_voice_and_clip(bot):
    bot._rate.clear()
    rec = Rec()
    run(bot.on_text(make_update(rec, text="Builders venue pe kitne log dikhe?"), SimpleNamespace(args=[])))
    assert "Confirmed" in rec.texts()
    assert "voice" in rec.kinds()
    assert any(k == "video" and p[4:8] == b"ftyp" for k, p in rec.calls)


@pytest.mark.live
def test_voice_note_ogg(bot, tmp_path):
    bot._rate.clear()
    ogg = tmp_path / "q.ogg"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(ROOT / "demo" / "q_hi.wav"), "-c:a", "libopus", str(ogg)], check=True)
    rec = Rec()
    run(bot.on_voice(make_update(rec, voice_path=ogg), SimpleNamespace(args=[])))
    assert rec.calls[0][0] == "text" and "🎙️" in rec.calls[0][1]          # transcript echoed first
    assert "Confirmed" in rec.texts() and "voice" in rec.kinds()


@pytest.mark.live
def test_report_command_sends_pdf(bot):
    if not db.fetch_val("SELECT max(id) FROM alerts"):
        pytest.skip("no alert yet")
    bot._rate.clear()
    rec = Rec()
    run(bot.report(make_update(rec), SimpleNamespace(args=[])))
    docs = [p for k, p in rec.calls if k == "document"]
    assert docs and docs[0][:4] == b"%PDF"
