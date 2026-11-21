"""Shared API helpers: error mapping, time parsing, media URLs, camera lookup."""
from __future__ import annotations

from datetime import datetime, timedelta

import psycopg
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from psycopg_pool import PoolTimeout

from ..core import db, storage
from ..core.openai_client import AIKeyProblem, AIUnavailable
from ..core.timeutil import now_local, parse_local


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AIUnavailable)
    async def _ai_missing(_: Request, e: AIUnavailable):
        return JSONResponse(status_code=503, content={"error": "OPENAI_API_KEY not set"})

    @app.exception_handler(AIKeyProblem)
    async def _ai_key(_: Request, e: AIKeyProblem):
        return JSONResponse(status_code=502, content={"error": str(e)})

    @app.exception_handler(psycopg.OperationalError)
    async def _db_down(_: Request, e: Exception):
        return JSONResponse(status_code=503, content={"error": "database unavailable"})

    @app.exception_handler(PoolTimeout)
    async def _db_pool(_: Request, e: Exception):
        return JSONResponse(status_code=503, content={"error": "database unavailable"})

    @app.exception_handler(HTTPException)
    async def _http(_: Request, e: HTTPException):
        detail = e.detail if isinstance(e.detail, dict) else {"error": str(e.detail)}
        return JSONResponse(status_code=e.status_code, content=detail, headers=getattr(e, "headers", None))


def http_error(status: int, msg: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"error": msg})


def parse_time(s: str | None, default: datetime) -> datetime:
    if not s:
        return default
    try:
        return parse_local(s)
    except Exception:
        raise http_error(400, f"bad time: {s}")


def window(t_from: str | None, t_to: str | None, default_hours: int = 24) -> tuple[datetime, datetime]:
    end = parse_time(t_to, now_local())
    start = parse_time(t_from, end - timedelta(hours=default_hours))
    if start >= end:
        raise http_error(400, "from must be before to")
    return start, end


def camera_or_404(camera_id: str) -> dict:
    row = db.fetch_one("SELECT * FROM cameras WHERE id=%s", (camera_id,))
    if not row:
        raise http_error(404, f"camera {camera_id} not found")
    return row


def media_url(key: str | None, token: str | None) -> str | None:
    return storage.url(key, token) if key else None
