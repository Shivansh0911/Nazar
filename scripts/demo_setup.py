"""Build the demo dataset: downloaded clips stamped as last night's CCTV.

    python scripts/demo_setup.py --manifest samples/demo_manifest.yaml [--reset] [--ai-zones] [--only shop-counter]

Creates the cameras (with per-camera settings), zones (manifest zones, else AI suggestions when a key exists,
else default boxes), runs the edge with --fast --start-time for every clip, waits for the worker to eventize
(and enrich, when OPENAI_API_KEY is set) and prints sample questions that have real answers on this data.
Idempotent: a clip already processed for a camera at the same start time is skipped (use --reset to rebuild).
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import yaml  # noqa: E402
from psycopg.types.json import Jsonb  # noqa: E402

from nazar.core import db, storage  # noqa: E402
from nazar.core.config import get_settings  # noqa: E402
from nazar.core.media import duration  # noqa: E402
from nazar.core.migrate import migrate  # noqa: E402
from nazar.core.timeutil import fmt_local, now_local, parse_local, to_local  # noqa: E402
from nazar.core.zones import clean_zones, default_zones, suggest_zones  # noqa: E402
from nazar.worker import alive  # noqa: E402


def resolve_start(s: str, path: Path | None = None):
    if s == "file" and path is not None:  # the file's own recording time: modified time minus its duration
        from datetime import datetime, timezone

        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc) - timedelta(seconds=duration(path))
    t = parse_local(s)
    if t > now_local():
        t -= timedelta(days=1)
    return t


def reset(cam_ids: list[str]) -> None:
    db.execute("DELETE FROM cameras WHERE id = ANY(%s)", (cam_ids,))
    for cam in cam_ids:
        for sub in ("segments", "crops", "clips", "keyframes"):
            shutil.rmtree(storage.data_dir() / sub / cam, ignore_errors=True)
        try:
            (storage.data_dir() / "live" / f"{cam}.jpg").unlink(missing_ok=True)
        except OSError:
            pass
    print(f"reset: removed {len(cam_ids)} camera(s) and their media")


def progress_bar(done: float, total: float, width: int = 30) -> str:
    frac = 0 if total <= 0 else min(1.0, done / total)
    return "[" + "#" * int(frac * width) + "." * (width - int(frac * width)) + f"] {frac * 100:5.1f}%"


def ensure_worker() -> subprocess.Popen | None:
    if alive.is_alive():
        print("worker: already running")
        return None
    print("worker: not running -> starting one for this setup (python -m nazar.worker.run)")
    log = open(storage.data_dir() / "logs" / "worker_demo_setup.log", "a", encoding="utf-8")
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    return subprocess.Popen([sys.executable, "-m", "nazar.worker.run"], cwd=str(ROOT / "backend"), stdout=log,
                            stderr=subprocess.STDOUT, creationflags=flags)


def sample_questions() -> list[str]:
    """Questions whose answers exist in the processed data (counts checked with SQL)."""
    qs: list[str] = []

    def count(cam: str, zone: str | None, t_from, t_to, cls: str = "person") -> int:
        if zone:
            return db.fetch_val(
                "SELECT count(DISTINCT COALESCE(t.merged_into, t.id)) FROM events e JOIN tracks t ON t.id=e.track_id "
                "WHERE e.camera_id=%s AND e.zone=%s AND e.type='enter' AND t.cls=%s AND e.t BETWEEN %s AND %s",
                (cam, zone, cls, t_from, t_to)) or 0
        return db.fetch_val("SELECT count(*) FROM root_tracks WHERE camera_id=%s AND cls=%s AND t_start BETWEEN %s AND %s",
                            (cam, cls, t_from, t_to)) or 0

    now = now_local()
    y = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    cams = {r["id"]: r for r in db.fetch_all("SELECT id, name, zones FROM cameras")}
    if "shop-counter" in cams:
        n = count("shop-counter", None, y.replace(hour=22), now)
        qs.append(f"Kal raat 10 baje ke baad shop counter pe kitne log aaye?   (SQL: {n} people)")
        n2 = count("shop-counter", None, y.replace(hour=18), y.replace(hour=20))
        qs.append(f"How many people came to the shop counter between 6 and 8 pm yesterday?   (SQL: {n2})")
    if "office-desk" in cams:
        qs.append("Desk 14 se bag kisne uthaya?   (object pickup on the office desk camera)")
        qs.append("Jab bhi koi desk 14 se bag uthaye, mujhe batana   (rule: replays on last night's footage first)")
    if "main-road" in cams:
        n = count("main-road", None, y.replace(hour=23), now, cls="motorcycle")
        qs.append(f"Raat 11 baje ke baad main road pe kitni bikes guzri?   (SQL: {n} motorcycles)")
    if "lobby" in cams:
        qs.append("Aaj subah lobby mein sabse zyada bheed kab thi?   (peak occupancy)")
    if "night-market" in cams:
        n = count("night-market", None, (y + timedelta(days=1)).replace(hour=2), now)
        qs.append(f"रात 2 बजे के बाद night stall पर कितने लोग आए?   (SQL: {n} people)")
    if "market-street" in cams:
        qs.append("Show me people carrying a bag on the market street this morning")
    return qs[:8]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=str(ROOT / "samples" / "demo_manifest.yaml"))
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--ai-zones", action="store_true", help="ask the agent model for zones even if the manifest has some")
    ap.add_argument("--only", help="process only this camera id")
    ap.add_argument("--no-wait", action="store_true")
    args = ap.parse_args()
    s = get_settings()
    (s.data_dir / "logs").mkdir(parents=True, exist_ok=True)
    migrate(verbose=False)
    man = yaml.safe_load(Path(args.manifest).read_text(encoding="utf-8"))
    cams = [c for c in man["cameras"] if not args.only or c["id"] == args.only]
    if args.reset:
        reset([c["id"] for c in cams])

    worker = ensure_worker() if not args.no_wait else None
    job_ids: list[int] = []
    t_all = time.monotonic()
    for cam in cams:
        clips = cam["clips"]
        first = str((ROOT / clips[0]["file"]).resolve())
        settings = cam.get("settings") or {}
        db.execute(
            "INSERT INTO cameras(id, name, source_url, kind, settings) VALUES (%s,%s,%s,'file',%s) "
            "ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name, settings=EXCLUDED.settings",
            (cam["id"], cam["name"], first, Jsonb(settings)))
        row = db.fetch_one("SELECT zones FROM cameras WHERE id=%s", (cam["id"],))
        if not row["zones"] or args.ai_zones:
            zones = None
            if (args.ai_zones or not cam.get("zones")) and s.has_openai:
                try:
                    from nazar.core.media import first_frame_jpeg
                    import tempfile

                    tmp = Path(tempfile.gettempdir()) / f"nazar_zone_{cam['id']}.jpg"
                    first_frame_jpeg(first, tmp)
                    zones = suggest_zones(tmp.read_bytes(), cam["id"])  # first frame of a stock clip; faces too small
                    print(f"{cam['id']}: {len(zones)} AI-suggested zones")
                except Exception as e:
                    print(f"{cam['id']}: zone suggestion failed ({e}); using defaults")
            if not zones:
                zones = clean_zones(cam.get("zones") or default_zones())
            db.execute("UPDATE cameras SET zones=%s, zones_updated_at=now() WHERE id=%s", (Jsonb(zones), cam["id"]))
        for clip in clips:
            path = (ROOT / clip["file"]).resolve()
            if not path.exists():
                print(f"  missing {clip['file']} - run: python scripts/fetch_samples.py")
                continue
            start = resolve_start(clip["start"], path)
            done = db.fetch_one("SELECT id, state FROM jobs WHERE camera_id=%s AND source=%s AND start_time=%s "
                                "AND state <> 'error'", (cam["id"], str(path), start))
            if done:
                print(f"  {cam['id']} {clip['file']} @ {to_local(start):%a %H:%M} already processed (job {done['id']})")
                job_ids.append(done["id"])
                continue
            dur = duration(path)
            job = db.fetch_one("INSERT INTO jobs(camera_id, kind, source, start_time, duration_s) VALUES "
                               "(%s,'demo',%s,%s,%s) RETURNING id", (cam["id"], str(path), start, dur))["id"]
            job_ids.append(job)
            print(f"  {cam['id']}: {clip['file']} @ {to_local(start):%a %d %b %H:%M} ({dur:.0f}s) job {job}", flush=True)
            cmd = [sys.executable, "-m", "nazar.edge.run", "--camera", cam["id"], "--source", str(path),
                   "--start-time", to_local(start).isoformat(), "--fast", "--job", str(job)]
            r = subprocess.run(cmd, cwd=str(ROOT / "backend"), capture_output=True, text=True, encoding="utf-8",
                               errors="replace")
            summary = [ln for ln in r.stdout.splitlines() if ln.startswith("EDGE_SUMMARY")]
            if r.returncode != 0:
                print("    edge failed:\n" + (r.stdout + r.stderr)[-1500:])
                db.execute("UPDATE jobs SET state='error', error='edge failed' WHERE id=%s", (job,))
                continue
            print("    " + (summary[-1][13:] if summary else "done"), flush=True)
    print(f"edge processing took {time.monotonic() - t_all:.0f}s")

    if not args.no_wait and job_ids:
        print("waiting for the worker (eventize" + (" + enrich" if s.has_openai else "") + ") ...")
        t0 = time.monotonic()
        while True:
            rows = db.fetch_all("SELECT state FROM jobs WHERE id = ANY(%s)", (job_ids,))
            ready = sum(1 for r in rows if r["state"] in ("ready", "error"))
            tot = db.fetch_val("SELECT count(*) FROM tracks t JOIN jobs j ON j.id=t.job_id WHERE j.id = ANY(%s)", (job_ids,))
            enr = db.fetch_val("SELECT count(*) FROM tracks t WHERE t.job_id = ANY(%s) AND t.enriched", (job_ids,))
            sys.stdout.write(f"\r  jobs {progress_bar(ready, len(rows))} {ready}/{len(rows)} ready | tracks {tot} | "
                             f"enriched {enr}   ")
            sys.stdout.flush()
            if ready == len(rows):
                break
            if time.monotonic() - t0 > 1800:
                print("\n  timed out waiting; check data/logs/worker*.log")
                break
            time.sleep(2)
        print()
    if worker is not None:
        worker.terminate()

    print("\nCameras:")
    for r in db.fetch_all("SELECT c.id, c.name, count(t.id) tracks, min(t.t_start) t0, max(t.t_end) t1 FROM cameras c "
                          "LEFT JOIN root_tracks t ON t.camera_id=c.id GROUP BY c.id, c.name ORDER BY c.id"):
        span = f"{to_local(r['t0']):%a %H:%M} → {to_local(r['t1']):%a %H:%M}" if r["t0"] else "no data"
        print(f"  {r['id']:<14} {r['name']:<14} {r['tracks']:>4} tracks   {span}")
    print("\nTry these questions (they have real answers on this data):")
    for i, q in enumerate(sample_questions(), 1):
        print(f"  {i}. {q}")
    if not s.has_openai:
        print("\nNote: OPENAI_API_KEY is empty - counts/rules work, but descriptions (captions) and asking by voice "
              "need the key. With the key set, the running worker enriches existing tracks automatically.")
    db.close_pool()
    return 0


if __name__ == "__main__":
    sys.exit(main())
