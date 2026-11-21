"""analytics_query (W6.2): the model writes ONE SELECT over whitelisted views; the server validates it with sqlglot
and runs it as the read-only role nazar_ro (statement_timeout 5 s, read-only transaction, IST timezone).
Results are database facts (Confirmed) and the SQL is shown to the owner ("how this was computed")."""
from __future__ import annotations

import datetime as _dt
import decimal
import logging
import re
from functools import lru_cache

import psycopg
import sqlglot
from psycopg.rows import dict_row
from sqlglot import exp

from ..core.config import get_settings

log = logging.getLogger("nazar.analytics")
VIEWS = {
    "v_cameras": "camera_id, name, kind, location, brand",
    "v_tracks": "track_id, camera_id, cls, t_start, t_end, duration_s, zones text[], max_conf, caption, counted bool "
                "(counted = the 'people seen' rule: >= 1.5 s and confident; use WHERE counted for people counts)",
    "v_events": "event_id, camera_id, track_id, cls, type (enter|exit|dwell|cross_in|cross_out), zone, t, dwell_s",
    "v_crossings": "event_id, camera_id, track_id, cls, line, direction (in|out), t",
    "v_alerts": "alert_id, rule_id, camera_id, t, message, rule_text, ack",
    "v_hourly": "camera_id, cls, hour_local (timestamp, IST), tracks (counted tracks starting in that hour)",
    "v_sec_events": "sec_event_id, camera_id, type, t_start, t_end, level, reason",
}
BANNED_FUNC = re.compile(r"^(pg_|lo_|dblink|set_config|current_setting|query_to_|xml|copy|txid|has_|version$)", re.I)
MAX_ROWS = 1000


class UnsafeSQL(ValueError):
    pass


def describe_views() -> str:
    return "\n".join(f"- {k}({v})" for k, v in VIEWS.items())


def validate(sql: str) -> str:
    """Return a safe single SELECT with LIMIT <= 1000, or raise UnsafeSQL."""
    sql = sql.strip().rstrip(";")
    try:
        stmts = sqlglot.parse(sql, read="postgres")
    except Exception as e:
        raise UnsafeSQL(f"could not parse SQL: {str(e)[:120]}")
    if len(stmts) != 1 or stmts[0] is None:
        raise UnsafeSQL("exactly one statement is allowed")
    tree = stmts[0]
    if not isinstance(tree, (exp.Select, exp.Union, exp.Subquery)) and not (isinstance(tree, exp.With)):
        raise UnsafeSQL("only SELECT is allowed")
    for bad in (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter, exp.Command, exp.Into,
                exp.Merge, exp.TruncateTable, exp.Grant):
        if tree.find(bad) is not None:
            raise UnsafeSQL("only read-only SELECT is allowed")
    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    for t in tree.find_all(exp.Table):
        name = t.name.lower()
        if t.args.get("db") or t.args.get("catalog"):
            raise UnsafeSQL("schema-qualified names are not allowed")
        if name not in VIEWS and name not in ctes:
            raise UnsafeSQL(f"table {name!r} is not available; use only: {', '.join(VIEWS)}")
    for f in tree.find_all(exp.Func):
        nm = (f.sql_name() if not isinstance(f, exp.Anonymous) else f.name) or ""
        if BANNED_FUNC.match(nm):
            raise UnsafeSQL(f"function {nm} is not allowed")
    limit = tree.args.get("limit") if isinstance(tree, exp.Select) else None
    out = tree.sql(dialect="postgres")
    if limit is None:
        out = f"SELECT * FROM ({out}) AS q LIMIT {MAX_ROWS}"
    else:
        try:
            n = int(limit.expression.sql())
            if n > MAX_ROWS:
                out = f"SELECT * FROM ({out}) AS q LIMIT {MAX_ROWS}"
        except Exception:
            out = f"SELECT * FROM ({out}) AS q LIMIT {MAX_ROWS}"
    return out


@lru_cache
def ro_url() -> str:
    url = get_settings().DATABASE_URL
    return re.sub(r"//[^@/]+@", "//nazar_ro:nazar_ro@", url, count=1)


def _jsonable(v):
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (_dt.datetime, _dt.date)):
        return v.isoformat()
    if isinstance(v, _dt.timedelta):
        return v.total_seconds()
    return v


def run(sql: str) -> dict:
    safe = validate(sql)
    with psycopg.connect(ro_url(), autocommit=False, row_factory=dict_row, connect_timeout=5) as c:
        c.execute("SET TRANSACTION READ ONLY")
        c.execute("SET LOCAL statement_timeout = '5s'")
        c.execute("SET LOCAL timezone = 'Asia/Kolkata'")
        cur = c.execute(safe)
        cols = [d.name for d in cur.description or []]
        rows = [{k: _jsonable(v) for k, v in r.items()} for r in cur.fetchall()]
        c.rollback()
    return {"sql": safe, "columns": cols, "rows": rows, "row_count": len(rows), "level": "confirmed"}
