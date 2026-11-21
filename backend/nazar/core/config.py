"""Central configuration, loaded from the repo-root .env (never printed)."""
from __future__ import annotations

import os
import shutil
import sys
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = REPO_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ENV_FILE), env_file_encoding="utf-8", extra="ignore")

    OPENAI_API_KEY: str = ""
    OPENAI_VISION_MODEL: str = "gpt-6-luna"
    OPENAI_VISION_FALLBACK: str = "gpt-5.4-mini"
    OPENAI_AGENT_MODEL: str = "gpt-6-sol"
    OPENAI_EMBED_MODEL: str = "text-embedding-3-small"
    OPENAI_TRANSCRIBE_MODEL: str = "gpt-4o-transcribe"
    OPENAI_TTS_MODEL: str = "gpt-4o-mini-tts"
    OPENAI_TTS_VOICE: str = "coral"

    DATABASE_URL: str = "postgresql://nazar:nazar@localhost:5433/nazar"
    STORAGE_MODE: str = "local"
    DATA_DIR: str = ""
    S3_BUCKET: str = ""
    AWS_REGION: str = "us-west-2"

    API_BASE_URL: str = "http://localhost:8000"
    WEB_ORIGINS: str = "http://localhost:3000"
    DEMO_PASSCODE: str = "nazar2026"
    TZ_NAME: str = "Asia/Kolkata"
    USD_INR: float = 88.0
    PRICES_JSON: str = ""

    DETECT_FPS: float = 5.0
    SEGMENT_FPS: float = 10.0
    SEGMENT_SECONDS: float = 10.0
    SEGMENT_WIDTH: int = 854
    DETECT_IMGSZ: int = 640
    DETECT_CONF: float = 0.30
    TRACK_END_S: float = 2.0
    ACTIVE_UPSERT_S: float = 1.0
    MOTION_THRESH: float = 0.002

    ENRICH_MIN_SECONDS: float = 1.0
    ENRICH_CONCURRENCY: int = 4
    ENRICH_DAILY_USD_CAP: float = 5.0
    RETENTION_DAYS: int = 7
    MAX_EDGES: int = 2
    AUTO_START_EDGES: bool = True
    UPLOAD_MAX_MB: int = 2048
    LEVEL_PROBABLE_SIM: float = 0.35
    LEVEL_CANDIDATE_SIM: float = 0.25
    MEDIAMTX_HOST: str = "localhost"
    FFMPEG_DIR: str = ""
    RECORD_RAW: int = 0
    DOMAIN: str = ""

    @field_validator("*", mode="before")
    @classmethod
    def _blank_to_default(cls, v, info):
        # An empty value in .env means "use the default" for non-string fields.
        if v == "" and info.field_name in cls.model_fields:
            ann = cls.model_fields[info.field_name].annotation
            if ann is not str:
                return cls.model_fields[info.field_name].default
        return v

    @property
    def data_dir(self) -> Path:
        p = Path(self.DATA_DIR) if self.DATA_DIR else REPO_ROOT / "data"
        return p

    @property
    def web_origins(self) -> list[str]:
        return [o.strip() for o in self.WEB_ORIGINS.split(",") if o.strip()]

    @property
    def has_openai(self) -> bool:
        return bool(self.OPENAI_API_KEY.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()


def _windows_registry_path() -> list[str]:
    if sys.platform != "win32":
        return []
    try:
        import winreg

        out: list[str] = []
        for root, sub in (
            (winreg.HKEY_CURRENT_USER, "Environment"),
            (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
        ):
            try:
                with winreg.OpenKey(root, sub) as k:
                    val, _ = winreg.QueryValueEx(k, "Path")
                    out.extend(os.path.expandvars(p) for p in val.split(";") if p)
            except OSError:
                pass
        return out
    except Exception:
        return []


@lru_cache
def tool_bin(name: str) -> str:
    """Resolve ffmpeg/ffprobe even when the current shell has a stale PATH."""
    s = get_settings()
    exe = name + (".exe" if sys.platform == "win32" else "")
    if s.FFMPEG_DIR:
        cand = Path(s.FFMPEG_DIR) / exe
        if cand.exists():
            return str(cand)
    found = shutil.which(name)
    if found:
        return found
    for d in _windows_registry_path():
        cand = Path(d) / exe
        if cand.exists():
            return str(cand)
    return name  # let subprocess raise a clear FileNotFoundError


def ffmpeg_bin() -> str:
    return tool_bin("ffmpeg")


def ffprobe_bin() -> str:
    return tool_bin("ffprobe")
