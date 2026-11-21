"""Logging setup with secret redaction."""
from __future__ import annotations

import logging
import re
import sys

_SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_\-]{8,}|AKIA[0-9A-Z]{16}|(?<=token=)[A-Za-z0-9._\-]+)")


class _Redact(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        red = _SECRET_RE.sub("***", msg)
        if red != msg:
            record.msg = red
            record.args = ()
        return True


_configured = False


def setup_logging(name: str = "nazar", level: int = logging.INFO, logfile: str | None = None) -> logging.Logger:
    global _configured
    root = logging.getLogger()
    if not _configured:
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S")
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(fmt)
        h.addFilter(_Redact())
        root.addHandler(h)
        if logfile:
            fh = logging.FileHandler(logfile, encoding="utf-8")
            fh.setFormatter(fmt)
            fh.addFilter(_Redact())
            root.addHandler(fh)
        root.setLevel(level)
        for noisy in ("httpx", "httpcore", "openai", "botocore", "urllib3", "ultralytics", "psycopg.pool"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
        _configured = True
    return logging.getLogger(name)


def redact(text: str) -> str:
    return _SECRET_RE.sub("***", text)
