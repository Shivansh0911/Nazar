"""Single demo passcode -> signed token (HMAC of passcode over the expiry)."""
from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import HTTPException, Request

from ..core.config import get_settings

TTL_S = 7 * 24 * 3600


def _sig(exp: int) -> str:
    key = ("nazar:" + get_settings().DEMO_PASSCODE).encode()
    return hmac.new(key, str(exp).encode(), hashlib.sha256).hexdigest()[:40]


def issue(passcode: str) -> str | None:
    if not hmac.compare_digest(passcode.strip(), get_settings().DEMO_PASSCODE):
        return None
    exp = int(time.time()) + TTL_S
    return f"{exp}.{_sig(exp)}"


def valid(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    exp_s, sig = token.split(".", 1)
    try:
        exp = int(exp_s)
    except ValueError:
        return False
    return exp > time.time() and hmac.compare_digest(sig, _sig(exp))


def token_from(request: Request) -> str | None:
    return request.headers.get("x-nazar-token") or request.query_params.get("token")


def require_token(request: Request) -> str:
    tok = token_from(request)
    if not valid(tok):
        raise HTTPException(status_code=401, detail="missing or invalid token")
    return tok  # type: ignore[return-value]
