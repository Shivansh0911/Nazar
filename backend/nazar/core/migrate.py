"""Apply numbered SQL migrations once: python -m nazar.core.migrate"""
from __future__ import annotations

import sys
from pathlib import Path

import psycopg

from .config import get_settings

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def migrate(verbose: bool = True) -> list[str]:
    applied: list[str] = []
    with psycopg.connect(get_settings().DATABASE_URL, autocommit=False) as c:
        c.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
        c.commit()
        done = {r[0] for r in c.execute("SELECT name FROM schema_migrations").fetchall()}
        for f in sorted(SQL_DIR.glob("*.sql")):
            if f.name in done:
                continue
            if verbose:
                print(f"applying {f.name}")
            c.execute(f.read_text(encoding="utf-8"))
            c.execute("INSERT INTO schema_migrations(name) VALUES (%s)", (f.name,))
            c.commit()
            applied.append(f.name)
    if verbose:
        print("migrations up to date" if not applied else f"applied {len(applied)} migration(s)")
    return applied


if __name__ == "__main__":
    try:
        migrate()
    except psycopg.OperationalError as e:
        print(f"Cannot reach the database: {e}\nStart it with: docker compose -f infra/docker-compose.yml up -d")
        sys.exit(1)
