import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))


def pytest_collection_modifyitems(config, items):
    """`live` tests run automatically only when OPENAI_API_KEY is set; `db` tests need the dev Postgres."""
    from nazar.core.config import get_settings
    from nazar.core import db

    has_key = get_settings().has_openai
    has_db = None
    for item in items:
        if "live" in item.keywords and not has_key:
            item.add_marker(pytest.mark.skip(reason="OPENAI_API_KEY not set"))
        if "db" in item.keywords:
            if has_db is None:
                has_db = db.ping()
            if not has_db:
                item.add_marker(pytest.mark.skip(reason="dev database not reachable"))


def make_path(points, t0=1_700_000_000_000, step_ms=200, w=0.04, h=0.12, conf=0.9):
    """points: list of (x_feet, y_feet) -> path rows with boxes whose feet anchor is that point."""
    out = []
    for i, (x, y) in enumerate(points):
        out.append([t0 + i * step_ms, x - w / 2, y - h, x + w / 2, y, conf])
    return out


@pytest.fixture
def mk_path():
    return make_path
