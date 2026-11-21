"""Sync psycopg 3 pool + helpers (Windows-safe: no async psycopg)."""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any, Iterable, Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import get_settings

_pool: ConnectionPool | None = None
_lock = threading.Lock()


def _configure(conn: psycopg.Connection) -> None:
    try:
        from pgvector.psycopg import register_vector

        register_vector(conn)
    except Exception:
        # The vector extension may not exist yet (before the first migration).
        conn.rollback()
    conn.execute("SET statement_timeout = '15s'")
    conn.commit()


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        with _lock:
            if _pool is None:
                _pool = ConnectionPool(
                    get_settings().DATABASE_URL,
                    min_size=1,
                    max_size=10,
                    kwargs={"row_factory": dict_row, "connect_timeout": 5},
                    configure=_configure,
                    open=True,
                    timeout=10,
                )
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def conn() -> Iterator[psycopg.Connection]:
    with get_pool().connection() as c:
        yield c


def fetch_all(sql: str, params: Any = None) -> list[dict]:
    with conn() as c:
        return list(c.execute(sql, params).fetchall())


def fetch_one(sql: str, params: Any = None) -> dict | None:
    with conn() as c:
        return c.execute(sql, params).fetchone()


def fetch_val(sql: str, params: Any = None) -> Any:
    row = fetch_one(sql, params)
    if not row:
        return None
    return next(iter(row.values()))


def execute(sql: str, params: Any = None) -> int:
    with conn() as c:
        cur = c.execute(sql, params)
        return cur.rowcount


def executemany(sql: str, seq: Iterable[Any]) -> None:
    with conn() as c:
        with c.cursor() as cur:
            cur.executemany(sql, list(seq))


def ping() -> bool:
    try:
        return fetch_val("SELECT 1") == 1
    except Exception:
        return False


def connect_raw(autocommit: bool = True) -> psycopg.Connection:
    """A dedicated connection (e.g. LISTEN) outside the pool."""
    c = psycopg.connect(get_settings().DATABASE_URL, autocommit=autocommit, row_factory=dict_row)
    try:
        from pgvector.psycopg import register_vector

        register_vector(c)
    except Exception:
        pass
    return c
