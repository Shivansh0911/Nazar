"""Environment check: python check_env.py  -> ✅/⚠️/❌ table. Exit 1 when a required item fails."""
from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

rows: list[tuple[str, str, str]] = []  # (status, item, detail)


def add(ok: bool | None, item: str, detail: str = "") -> None:
    rows.append(("✅" if ok else ("⚠️ " if ok is None else "❌"), item, detail))


def main() -> int:
    for pkg in ["torch", "ultralytics", "cv2", "numpy", "psycopg", "psycopg_pool", "pgvector", "fastapi", "uvicorn",
                "openai", "pydantic", "pydantic_settings", "boto3", "yaml", "multipart", "lap"]:
        try:
            m = importlib.import_module(pkg)
            add(True, f"python: {pkg}", getattr(m, "__version__", ""))
        except Exception as e:
            add(False, f"python: {pkg}", str(e)[:80])
    try:
        import torch

        cuda = torch.cuda.is_available()
        add(True if cuda else None, "torch CUDA", f"{torch.__version__} cuda={cuda}" +
            (f" {torch.cuda.get_device_name(0)}" if cuda else " (CPU mode)"))
    except Exception as e:
        add(False, "torch CUDA", str(e)[:80])

    from nazar.core.config import ENV_FILE, ffmpeg_bin, ffprobe_bin, get_settings

    s = get_settings()
    add(ENV_FILE.exists(), ".env present", str(ENV_FILE))
    for name, fn in (("ffmpeg", ffmpeg_bin), ("ffprobe", ffprobe_bin)):
        b = fn()
        try:
            out = subprocess.run([b, "-version"], capture_output=True, text=True, timeout=15).stdout.splitlines()[0]
            add(True, name, out[:60])
        except Exception as e:
            add(False, name, f"not found ({e.__class__.__name__}); install ffmpeg or set FFMPEG_DIR")

    from nazar.core import db

    try:
        exts = {r["extname"] for r in db.fetch_all("SELECT extname FROM pg_extension")}
        add(True, "database", s.DATABASE_URL.split("@")[-1])
        add({"vector", "pg_trgm"} <= exts, "db extensions", ", ".join(sorted(exts)))
        mig = db.fetch_all("SELECT name FROM schema_migrations ORDER BY name")
        add(bool(mig), "db migrations", ", ".join(r["name"] for r in mig) or "run: python -m nazar.core.migrate")
    except Exception as e:
        add(False, "database", f"{str(e)[:70]} -> docker compose -f infra/docker-compose.yml up -d")

    d = s.data_dir
    try:
        d.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=d, delete=True) as f:
            f.write(b"x")
        add(True, "data dir writable", str(d))
    except Exception as e:
        add(False, "data dir writable", str(e)[:80])
    free_gb = shutil.disk_usage(d).free / 1e9
    add(free_gb > 5, "disk space", f"{free_gb:.0f} GB free")

    models = ROOT / "backend" / "models"
    add((models / "yolo11n.pt").exists() or any(models.glob("*n.pt")), "YOLO weights", "python scripts/download_models.py")
    add((models / "face_detection_yunet_2023mar.onnx").exists(), "YuNet face model", "python scripts/download_models.py")

    samples = [ROOT / "samples" / f"clip{i}.mp4" for i in range(1, 6)] + [ROOT / "samples" / "clip6_bag.mp4"]
    missing = [p.name for p in samples if not p.exists()]
    add(not missing, "sample clips", "all 6 present" if not missing else "missing: " + ", ".join(missing))

    add(True if s.has_openai else None, "OPENAI_API_KEY", "set" if s.has_openai else "empty - AI features return 503")
    add(True, "OpenAI models", f"vision={s.OPENAI_VISION_MODEL} agent={s.OPENAI_AGENT_MODEL} embed={s.OPENAI_EMBED_MODEL}")

    if s.STORAGE_MODE == "s3":
        try:
            import boto3

            boto3.client("s3", region_name=s.AWS_REGION).head_bucket(Bucket=s.S3_BUCKET)
            add(True, "S3 bucket", s.S3_BUCKET)
        except Exception as e:
            add(False, "S3 bucket", f"{str(e)[:60]} (refresh workshop credentials?)")
    else:
        add(True, "storage", "local mode")

    w = max(len(r[1]) for r in rows)
    for st, item, detail in rows:
        print(f"{st} {item.ljust(w)}  {detail}")
    failed = [r for r in rows if r[0] == "❌"]
    print(f"\n{len(rows) - len(failed)}/{len(rows)} ok" + (f", {len(failed)} failed" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
