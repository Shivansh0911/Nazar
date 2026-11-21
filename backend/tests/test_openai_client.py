"""OpenAI plumbing with a test-only fake client: request building, parsing, cost logging, fallback, errors."""
import pytest

from fakes import FakeClient, StatusError
from nazar.core import openai_client as oc
from nazar.core import prices
from nazar.core.openai_client import AIKeyProblem, NazarAI, detect_language
from nazar.core.schemas import TrackCaption

CAP = {"caption": "Adult in a red shirt carrying a backpack, walking left.", "upper_color": "red",
       "lower_color": "blue", "headwear": "none", "carrying": ["backpack"], "action": "walking",
       "vehicle_type": "none", "vehicle_color": "unknown", "notable": "", "quality": "good"}


@pytest.fixture
def recorded(monkeypatch):
    rows = []
    monkeypatch.setattr(oc.usage, "record", lambda kind, model, **kw: rows.append((kind, model, kw)))
    return rows


def test_caption_builds_request_and_logs_cost(recorded):
    fake = FakeClient(parse_fn=lambda kw: CAP)
    ai = NazarAI(client=fake)
    cap, cost = ai.caption_track([b"\xff\xd8jpeg1", b"\xff\xd8jpeg2"], "person", camera_id="cam", ref="7")
    assert isinstance(cap, TrackCaption) and cap.upper_color == "red"
    call = fake.responses.parse_calls[0]
    content = call["input"][0]["content"]
    imgs = [c for c in content if c["type"] == "input_image"]
    assert len(imgs) == 2 and imgs[0]["detail"] == "low" and imgs[0]["image_url"].startswith("data:image/jpeg;base64,")
    assert call["text_format"] is TrackCaption
    assert "ethnicity" in call["instructions"]
    kind, model, kw = recorded[0]
    assert kind == "caption" and kw["images"] == 2 and kw["camera_id"] == "cam"
    assert kw["input_tokens"] == 100 and kw["output_tokens"] == 20
    assert cost == pytest.approx(kw["cost_usd"])


def test_vision_fallback_on_model_not_found(recorded, monkeypatch):
    seen = []

    def parse_fn(kw):
        seen.append(kw["model"])
        if len(seen) == 1:
            return StatusError(404, "NotFoundError", "model_not_found")
        return CAP

    ai = NazarAI(client=FakeClient(parse_fn=parse_fn))
    cap, _ = ai.caption_track([b"x"], "person")
    from nazar.core.config import get_settings

    assert seen == [get_settings().OPENAI_VISION_MODEL, get_settings().OPENAI_VISION_FALLBACK]
    ai.caption_track([b"x"], "person")
    assert seen[-1] == get_settings().OPENAI_VISION_FALLBACK  # sticky after the first failure


def test_retry_then_key_problem(recorded, monkeypatch):
    monkeypatch.setattr(oc.time, "sleep", lambda s: None)
    calls = []

    def flaky(kw):
        calls.append(1)
        return StatusError(429, "RateLimitError") if len(calls) < 3 else CAP

    ai = NazarAI(client=FakeClient(parse_fn=flaky))
    ai.caption_track([b"x"], "person")
    assert len(calls) == 3
    ai2 = NazarAI(client=FakeClient(parse_fn=lambda kw: StatusError(401, "AuthenticationError")))
    with pytest.raises(AIKeyProblem):
        ai2.caption_track([b"x"], "person")


def test_embed_batches_and_cost(recorded):
    fake = FakeClient()
    vecs = NazarAI(client=fake).embed([f"text {i}" for i in range(130)])
    assert len(vecs) == 130 and len(vecs[0]) == 1536
    assert fake.embeddings.calls == 3
    assert [r[0] for r in recorded] == ["embed"] * 3


def test_missing_key_raises_unavailable(monkeypatch):
    from nazar.core import config

    s = config.get_settings()
    monkeypatch.setattr(s, "OPENAI_API_KEY", "")
    with pytest.raises(oc.AIUnavailable):
        NazarAI().client


def test_prices():
    usd, unknown = prices.cost_tokens("gpt-6-luna", 1_000_000, 0, 1_000_000)
    assert usd == pytest.approx(0.60) and not unknown
    usd, _ = prices.cost_tokens("gpt-6-sol", 1_000_000, 500_000, 0)
    assert usd == pytest.approx(0.5 * 2.0 + 0.5 * 0.2)
    assert prices.cost_tokens("mystery-model", 100, 0, 100) == (0.0, True)
    assert prices.cost_audio("gpt-4o-transcribe", 60)[0] == pytest.approx(0.006)


def test_detect_language():
    assert detect_language("आज कितने लोग आए?") == "hi"
    assert detect_language("Kal raat kitne log aaye counter pe?") == "hinglish"
    assert detect_language("How many people came yesterday?") == "en"
