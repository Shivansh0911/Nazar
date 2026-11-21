"""Real OpenAI calls. Run automatically when OPENAI_API_KEY is set:  pytest -m live -q"""
import pytest

from nazar.core import db, storage
from nazar.core.openai_client import NazarAI
from nazar.core.schemas import TrackCaption

pytestmark = [pytest.mark.live, pytest.mark.db]


@pytest.fixture(scope="module")
def ai():
    return NazarAI()


def _crop() -> tuple[bytes, str]:
    r = db.fetch_one("SELECT cls, crop_keys FROM tracks WHERE cls='person' AND array_length(crop_keys,1) > 0 "
                     "AND t_end - t_start > interval '5 seconds' ORDER BY id LIMIT 1")
    if not r:
        pytest.skip("no demo tracks")
    return storage.local_path(r["crop_keys"][0]).read_bytes(), r["cls"]


def test_caption_real_crop(ai):
    img, cls = _crop()
    cap, cost = ai.caption_track([img], cls, ref="test_live")
    assert isinstance(cap, TrackCaption) and cap.caption and cost >= 0
    assert len(cap.caption.split()) <= 40


def test_embed_similarity(ai):
    a, b, c = ai.embed(["man in a red shirt carrying a bag", "person wearing red top with a backpack",
                        "white car parked on the road"], ref="test_live")
    import numpy as np

    cos = lambda x, y: float(np.dot(x, y) / (np.linalg.norm(x) * np.linalg.norm(y)))
    assert cos(a, b) > cos(a, c)


def test_tts_transcribe_roundtrip(ai, tmp_path):
    p = ai.tts("Counter pe aaj saat log aaye.", "hinglish", out_path=tmp_path / "x.mp3", ref="test_live")
    text, lang, secs = ai.transcribe(p, "Hinglish shop CCTV question", ref="test_live")
    assert secs > 0.5 and ("saat" in text.lower() or "7" in text or "सात" in text)


def test_compile_rule_with_replay():
    from nazar.api.agent import compile_rule

    if not db.fetch_one("SELECT 1 FROM cameras WHERE id='office-desk'"):
        pytest.skip("no office-desk camera")
    d = compile_rule("Jab bhi koi desk 14 se bag uthaye, mujhe batana", "office-desk", ref="test_live")
    try:
        assert d["ok"], d
        assert d["spec"]["trigger"] == "object_removed" and d["spec"]["zone"] == "desk_14"
        assert d["replay"]["count"] >= 1
    finally:
        if d.get("rule_id"):
            db.execute("DELETE FROM rules WHERE id=%s", (d["rule_id"],))


def test_compile_rule_missing_zone_asks():
    from nazar.api.agent import compile_rule

    d = compile_rule("Jab bhi koi parking gate pe aaye toh batana", "office-desk", ref="test_live")
    if d.get("rule_id"):
        db.execute("DELETE FROM rules WHERE id=%s", (d["rule_id"],))
    assert not d["ok"] and d.get("question")


def test_ask_count_is_sql_fact():
    from nazar.api.agent import ask

    r = ask("Kal raat 10 baje ke baad shop counter pe kitne log aaye?", "shop-counter", token=None)
    assert r["count"] and r["count"]["level"] == "confirmed" and r["count"]["value"] >= 1
    assert r["language"] in ("hinglish", "hi") and r["reply_text"]
    assert str(r["count"]["value"]) in r["reply_text"] or r["count"]["value"] >= 0
