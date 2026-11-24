"""Cost guards: no embedding call that cannot match, repeated phrases embedded once, voice replies only when played."""
import json

import fakes
from nazar.api import agent, agent_tools
from nazar.core import openai_client as oc


class CountingAI:
    def __init__(self):
        self.embedded: list[str] = []

    def embed(self, texts, **kw):
        self.embedded.extend(texts)
        return [[0.1] * 4 for _ in texts]


def test_text_search_skips_the_embedding_when_no_track_in_the_window_is_described(monkeypatch):
    class DB:
        def fetch_one(self, sql, params=None):
            return None  # the probe: no caption_emb in this window

        def fetch_all(self, sql, params=None):
            return []

        def fetch_val(self, sql, params=None):
            return 0

    monkeypatch.setattr(agent_tools, "db", DB())
    ai = CountingAI()
    out = agent_tools.search_tracks({"time_from": "2026-11-21T10:00", "time_to": "2026-11-21T11:00", "text": "red bag"}, ai=ai)
    assert ai.embedded == [] and out["results"] == []


def test_a_repeated_search_phrase_is_embedded_once(monkeypatch):
    monkeypatch.setattr(agent_tools, "_QEMB", {})
    ai = CountingAI()
    a = agent_tools.query_embedding("Red   Bag", ai)
    b = agent_tools.query_embedding("red bag", ai)
    agent_tools.query_embedding("green bag", ai)
    assert a == b and ai.embedded == ["red bag", "green bag"]


def test_a_deferred_voice_reply_costs_nothing_until_it_is_played(monkeypatch, tmp_path):
    monkeypatch.setattr(agent.storage, "local_path", lambda key: tmp_path / key)
    monkeypatch.setattr(agent.storage, "put", lambda path, key: key)
    monkeypatch.setattr(oc.usage, "record", lambda *a, **k: None)
    monkeypatch.setattr("nazar.core.media.duration", lambda p: 2.0)
    fake = fakes.FakeClient()
    monkeypatch.setattr(agent, "get_ai", lambda: oc.NazarAI(client=fake))
    name = agent.defer_tts("inv:abc", "Namaste", "hi")
    assert name == "inv_abc.mp3" and fake.audio.speech_calls == []  # nothing synthesized yet
    assert json.loads((tmp_path / "tts" / (name + ".pending.json")).read_text(encoding="utf-8"))["text"] == "Namaste"
    agent.ensure_tts(name)  # first play
    assert len(fake.audio.speech_calls) == 1 and (tmp_path / "tts" / name).exists()
    agent.ensure_tts(name)  # second play: the file is there, no second call
    assert len(fake.audio.speech_calls) == 1
    agent.ensure_tts("never_deferred.mp3")
    assert len(fake.audio.speech_calls) == 1
