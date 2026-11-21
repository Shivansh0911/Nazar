"""One wrapper around the OpenAI SDK (Responses API). Every call writes a `usage` row with its cost.

Model names come only from settings. Tests inject a fake client via set_ai(NazarAI(client=Fake())).
"""
from __future__ import annotations

import base64
import logging
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, TypeVar

from pydantic import BaseModel

from . import prices, usage
from .config import get_settings
from .schemas import TrackCaption, VisionCheck

log = logging.getLogger("nazar.openai")
T = TypeVar("T", bound=BaseModel)

CAPTION_SYSTEM = (
    "You describe crops from a shop's CCTV camera for later search. You see 1-3 face-blurred crops of ONE tracked "
    "object of the given detector class. Describe only what is visible: clothing colours, headwear, what is carried, "
    "the action, and vehicle type/colour if it is a vehicle. Never guess identity, name, ethnicity, religion, caste, "
    "or age (only 'child' or 'adult' if obvious). Never describe faces. If unsure about a field, answer 'unknown'. "
    "Use 'none' for vehicle_type and 'unknown' for vehicle_color when the object is not a vehicle. caption: at most 25 "
    "English words, factual. notable: at most 10 words or empty. quality: 'poor' when the crops are too blurry or tiny."
)
VISION_CHECK_SYSTEM = (
    "You verify a single statement about a face-blurred CCTV crop. Answer yes only if the statement is clearly "
    "visible in the image. Never identify people. Keep reason under 20 words."
)
TTS_INSTRUCTIONS = ("Speak warmly and naturally like a helpful Indian shop assistant. If the text is Hindi, use "
                    "natural Hindi pronunciation.")


class AIUnavailable(Exception):
    """No API key configured -> HTTP 503."""


class AIKeyProblem(Exception):
    """401 / insufficient_quota -> clear message for the owner."""


def _jpeg_data_url(img: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(img).decode("ascii")


def _usage_tokens(resp: Any) -> tuple[int, int, int]:
    u = getattr(resp, "usage", None)
    if u is None:
        return 0, 0, 0
    inp = int(getattr(u, "input_tokens", 0) or getattr(u, "prompt_tokens", 0) or 0)
    det = getattr(u, "input_tokens_details", None)
    cached = int(getattr(det, "cached_tokens", 0) or 0) if det is not None else 0
    out = int(getattr(u, "output_tokens", 0) or 0)
    return inp, cached, out


def detect_language(text: str) -> str:
    if re.search(r"[ऀ-ॿ]", text or ""):
        return "hi"
    hinglish = r"\b(kya|kitne|kitna|kab|kaun|kahan|raat|subah|kal|aaj|baje|log|aaye|aaya|batana|batao|mujhe|jab|bhi|koi|pe|ke|ki|hai|tha|thi|wala|wali|uthaye|dikhao|kisi|ne|se|ko)\b"
    hits = len(re.findall(hinglish, (text or "").lower()))
    return "hinglish" if hits >= 2 else "en"


class NazarAI:
    def __init__(self, client: Any | None = None):
        self._client = client
        self._lock = threading.Lock()
        self._vision_model_override: str | None = None
        self._warned_fallback = False

    # ---- plumbing -------------------------------------------------------
    @property
    def client(self):
        if self._client is None:
            s = get_settings()
            if not s.has_openai:
                raise AIUnavailable("OPENAI_API_KEY not set")
            with self._lock:
                if self._client is None:
                    import openai

                    self._client = openai.OpenAI(api_key=s.OPENAI_API_KEY, timeout=60.0, max_retries=0)
        return self._client

    def available(self) -> bool:
        return self._client is not None or get_settings().has_openai

    def _retry(self, fn: Callable[[], Any], what: str) -> Any:
        delay = 1.0
        last: Exception | None = None
        for attempt in range(4):  # 1 try + 3 retries
            try:
                return fn()
            except Exception as e:  # classify by class name so fakes can raise lookalikes
                name = type(e).__name__
                status = getattr(e, "status_code", None)
                body = str(getattr(e, "body", "") or e)
                if name == "AuthenticationError" or status == 401 or "insufficient_quota" in body:
                    raise AIKeyProblem("OpenAI credits/key problem: " + name) from e
                retriable = name in ("RateLimitError", "APITimeoutError", "APIConnectionError", "InternalServerError") or (
                    isinstance(status, int) and status >= 500)
                if not retriable or attempt == 3:
                    raise
                last = e
                log.warning("%s failed (%s), retry %d in %.0fs", what, name, attempt + 1, delay)
                time.sleep(delay)
                delay *= 2
        raise last  # pragma: no cover

    @staticmethod
    def _is_model_missing(e: Exception) -> bool:
        name = type(e).__name__
        status = getattr(e, "status_code", None)
        return name in ("NotFoundError", "PermissionDeniedError") or status in (403, 404) or "model_not_found" in str(e)

    def _record_tokens(self, kind: str, model: str, resp: Any, camera_id=None, ref=None, images=None) -> float:
        inp, cached, out = _usage_tokens(resp)
        cost, unknown = prices.cost_tokens(model, inp, cached, out)
        usage.record(kind, model, camera_id=camera_id, ref=ref, input_tokens=inp, cached_tokens=cached,
                     output_tokens=out, images=images, cost_usd=cost, unknown_price=unknown)
        return cost

    # ---- generic calls ----------------------------------------------------
    def parse(self, model: str, input: Any, schema: type[T], *, kind: str, instructions: str | None = None,
              camera_id: str | None = None, ref: str | None = None, images: int | None = None,
              max_output_tokens: int | None = None, reasoning: str | None = None) -> tuple[T, float]:
        kwargs: dict[str, Any] = {"model": model, "input": input, "text_format": schema}
        if reasoning:
            kwargs["reasoning"] = {"effort": reasoning}
        if instructions:
            kwargs["instructions"] = instructions
        if max_output_tokens:
            kwargs["max_output_tokens"] = max_output_tokens
        resp = self._retry(lambda: self.client.responses.parse(**kwargs), f"{kind}:{model}")
        cost = self._record_tokens(kind, model, resp, camera_id, ref, images)
        parsed = getattr(resp, "output_parsed", None)
        if parsed is None:
            raise ValueError(f"{kind}: model returned no structured output")
        if not isinstance(parsed, schema):
            parsed = schema.model_validate(parsed)
        return parsed, cost

    def agent_step(self, *, model: str, input: list, tools: list | None = None, instructions: str | None = None,
                   kind: str = "agent", ref: str | None = None, camera_id: str | None = None, text: dict | None = None,
                   tool_choice: Any = None, reasoning: str | None = None) -> tuple[Any, float]:
        kwargs: dict[str, Any] = {"model": model, "input": input}
        if reasoning:
            kwargs["reasoning"] = {"effort": reasoning}
        if tools:
            kwargs["tools"] = tools
        if instructions:
            kwargs["instructions"] = instructions
        if text:
            kwargs["text"] = text
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
        resp = self._retry(lambda: self.client.responses.create(**kwargs), f"{kind}:{model}")
        cost = self._record_tokens(kind, model, resp, camera_id, ref)
        return resp, cost

    # ---- vision -------------------------------------------------------------
    def _vision_model(self) -> str:
        return self._vision_model_override or get_settings().OPENAI_VISION_MODEL

    def caption_track(self, images: list[bytes], cls: str, *, camera_id: str | None = None,
                      ref: str | None = None) -> tuple[TrackCaption, float]:
        content: list[dict] = [{"type": "input_text", "text": f"Detector class: {cls}. {len(images)} crop(s) of the same object."}]
        for img in images[:3]:
            content.append({"type": "input_image", "image_url": _jpeg_data_url(img), "detail": "low"})
        inp = [{"role": "user", "content": content}]
        model = self._vision_model()
        try:
            return self.parse(model, inp, TrackCaption, kind="caption", instructions=CAPTION_SYSTEM,
                              camera_id=camera_id, ref=ref, images=len(images[:3]), max_output_tokens=1200,
                              reasoning=get_settings().VISION_REASONING_EFFORT or None)
        except (AIUnavailable, AIKeyProblem):
            raise
        except Exception as e:
            fb = get_settings().OPENAI_VISION_FALLBACK
            if self._is_model_missing(e) and fb and model != fb:
                if not self._warned_fallback:
                    log.error("vision model %s unavailable (%s); falling back to %s", model, type(e).__name__, fb)
                    self._warned_fallback = True
                self._vision_model_override = fb
                return self.parse(fb, inp, TrackCaption, kind="caption", instructions=CAPTION_SYSTEM,
                                  camera_id=camera_id, ref=ref, images=len(images[:3]), max_output_tokens=1200,
                              reasoning=get_settings().VISION_REASONING_EFFORT or None)
            raise

    def vision_check(self, image: bytes, question: str, *, camera_id: str | None = None,
                     ref: str | None = None) -> tuple[VisionCheck, float]:
        inp = [{"role": "user", "content": [
            {"type": "input_text", "text": f"Statement: {question}"},
            {"type": "input_image", "image_url": _jpeg_data_url(image), "detail": "low"},
        ]}]
        return self.parse(get_settings().OPENAI_AGENT_MODEL, inp, VisionCheck, kind="confirm",
                          instructions=VISION_CHECK_SYSTEM, camera_id=camera_id, ref=ref, images=1,
                          max_output_tokens=200)

    # ---- embeddings ----------------------------------------------------------
    def embed(self, texts: list[str], *, kind: str = "embed", camera_id: str | None = None,
              ref: str | None = None) -> list[list[float]]:
        model = get_settings().OPENAI_EMBED_MODEL
        out: list[list[float]] = []
        for i in range(0, len(texts), 64):
            batch = texts[i:i + 64]
            resp = self._retry(lambda: self.client.embeddings.create(model=model, input=batch), f"embed:{model}")
            u = getattr(resp, "usage", None)
            tok = int(getattr(u, "prompt_tokens", 0) or getattr(u, "total_tokens", 0) or 0) if u else 0
            cost, unknown = prices.cost_tokens(model, tok, 0, 0)
            usage.record(kind, model, camera_id=camera_id, ref=ref, input_tokens=tok, cost_usd=cost, unknown_price=unknown)
            data = sorted(resp.data, key=lambda d: getattr(d, "index", 0))
            out.extend([list(d.embedding) for d in data])
        return out

    # ---- audio -----------------------------------------------------------------
    def transcribe(self, file_path: str | Path, prompt: str = "", *, ref: str | None = None,
                   seconds: float | None = None) -> tuple[str, str, float]:
        from .media import duration

        model = get_settings().OPENAI_TRANSCRIBE_MODEL
        secs = seconds if seconds is not None else duration(file_path)

        def call():
            with open(file_path, "rb") as f:
                return self.client.audio.transcriptions.create(model=model, file=f, prompt=prompt or None)

        resp = self._retry(call, f"transcribe:{model}")
        text = (getattr(resp, "text", None) or (resp if isinstance(resp, str) else "")).strip()
        cost, unknown = prices.cost_audio(model, secs)
        usage.record("transcribe", model, ref=ref, audio_seconds=secs, cost_usd=cost, unknown_price=unknown)
        return text, detect_language(text), secs

    def tts(self, text: str, language: str = "en", *, out_path: str | Path | None = None,
            ref: str | None = None) -> Path:
        from .media import duration
        from .storage import data_dir

        s = get_settings()
        model = s.OPENAI_TTS_MODEL
        out = Path(out_path) if out_path else data_dir() / "tts" / f"{uuid.uuid4().hex}.mp3"
        out.parent.mkdir(parents=True, exist_ok=True)

        def call():
            return self.client.audio.speech.create(model=model, voice=s.OPENAI_TTS_VOICE, input=text[:4000],
                                                   instructions=TTS_INSTRUCTIONS, response_format="mp3")

        resp = self._retry(call, f"tts:{model}")
        data = resp.read() if hasattr(resp, "read") else (resp.content if hasattr(resp, "content") else bytes(resp))
        tmp = out.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(out)
        try:
            secs = duration(out)
        except Exception:
            secs = max(1.0, len(text) / 14.0)  # ~14 chars/sec speech estimate
        cost, unknown = prices.cost_audio(model, secs)
        usage.record("tts", model, ref=ref, audio_seconds=secs, cost_usd=cost, unknown_price=unknown)
        return out


_ai: NazarAI | None = None


def get_ai() -> NazarAI:
    global _ai
    if _ai is None:
        _ai = NazarAI()
    return _ai


def set_ai(ai: NazarAI | None) -> None:
    global _ai
    _ai = ai
