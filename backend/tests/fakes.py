"""TEST-ONLY stand-ins for the OpenAI SDK client. Never imported by product code."""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Callable


def usage(inp=100, cached=0, out=20):
    return SimpleNamespace(input_tokens=inp, output_tokens=out,
                           input_tokens_details=SimpleNamespace(cached_tokens=cached))


class FakeResponses:
    def __init__(self, parse_fn: Callable[[dict], Any] | None = None, create_fn: Callable[[dict], Any] | None = None):
        self.parse_fn = parse_fn
        self.create_fn = create_fn
        self.parse_calls: list[dict] = []
        self.create_calls: list[dict] = []

    def parse(self, **kw):
        self.parse_calls.append(kw)
        schema = kw["text_format"]
        result = self.parse_fn(kw) if self.parse_fn else None
        if isinstance(result, Exception):
            raise result
        if isinstance(result, dict):
            result = schema.model_validate(result)
        return SimpleNamespace(output_parsed=result, usage=usage(), output=[])

    def create(self, **kw):
        self.create_calls.append(kw)
        result = self.create_fn(kw)
        if isinstance(result, Exception):
            raise result
        return result


class _FakeStream:
    def __init__(self, resp):
        self.resp = resp

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        text = getattr(self.resp, "output_text", "") or ""
        for i in range(0, len(text), 7):  # emit the final text in small deltas like the real API
            yield SimpleNamespace(type="response.output_text.delta", delta=text[i:i + 7])

    def get_final_response(self):
        return self.resp


def _stream(self, **kw):
    r = self.create(**kw)
    return _FakeStream(r)


FakeResponses.stream = _stream


def function_call(name: str, args: dict, call_id: str = "call_1"):
    return SimpleNamespace(type="function_call", name=name, arguments=json.dumps(args), call_id=call_id,
                           id="fc_" + call_id, status="completed",
                           model_dump=lambda **_: {"type": "function_call", "name": name,
                                                   "arguments": json.dumps(args), "call_id": call_id})


def message(text: str):
    return SimpleNamespace(type="message", content=[SimpleNamespace(type="output_text", text=text)],
                           model_dump=lambda **_: {"type": "message", "role": "assistant",
                                                   "content": [{"type": "output_text", "text": text}]})


def response(output: list, text: str = ""):
    return SimpleNamespace(output=output, output_text=text, usage=usage(500, 300, 60))


class FakeEmbeddings:
    def __init__(self, fn: Callable[[str], list[float]] | None = None, dims: int = 1536):
        self.fn = fn
        self.dims = dims
        self.calls = 0

    def create(self, model, input, **kw):
        self.calls += 1
        data = []
        for i, t in enumerate(input):
            vec = self.fn(t) if self.fn else _hash_vec(t, self.dims)
            data.append(SimpleNamespace(index=i, embedding=vec))
        return SimpleNamespace(data=data, usage=SimpleNamespace(prompt_tokens=10 * len(input), total_tokens=10 * len(input)))


def _hash_vec(text: str, dims: int) -> list[float]:
    import hashlib
    import math

    v = [0.0] * dims
    for w in text.lower().split():
        h = int(hashlib.md5(w.encode()).hexdigest(), 16)
        v[h % dims] += 1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class FakeAudio:
    def __init__(self, transcript: str = "Aaj kitne log aaye?"):
        self.transcript = transcript
        self.transcriptions = SimpleNamespace(create=self._transcribe)
        self.speech = SimpleNamespace(create=self._speech)
        self.speech_calls: list[dict] = []

    def _transcribe(self, **kw):
        return SimpleNamespace(text=self.transcript)

    def _speech(self, **kw):
        self.speech_calls.append(kw)
        return SimpleNamespace(read=lambda: b"ID3\x00fake-mp3")


class FakeClient:
    def __init__(self, parse_fn=None, create_fn=None, embed_fn=None, transcript="Aaj kitne log aaye?"):
        self.responses = FakeResponses(parse_fn, create_fn)
        self.embeddings = FakeEmbeddings(embed_fn)
        self.audio = FakeAudio(transcript)


class StatusError(Exception):
    """Looks like an openai APIStatusError for the retry/fallback classifier."""

    def __init__(self, status_code: int, name: str, msg: str = ""):
        super().__init__(msg or name)
        self.status_code = status_code
        self.__class__ = type(name, (StatusError,), {})
