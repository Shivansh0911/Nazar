"""Media storage: local disk (served by the API) or S3 (presigned URLs).

Segments always stay on local disk because ffmpeg cuts clips from them.
Key prefixes: crops/<camera>/<track>_<n>.jpg, clips/<camera>/<hash>.mp4, tts/<id>.mp3, snap/<alert>.jpg
"""
from __future__ import annotations

import logging
import os
import shutil
from functools import lru_cache
from pathlib import Path

from .config import get_settings

log = logging.getLogger("nazar.storage")
LOCAL_ONLY_PREFIXES = ("segments/", "live/", "uploads/", "recordings/", "logs/", "inspect/", "eval/")


def data_dir() -> Path:
    d = get_settings().data_dir
    d.mkdir(parents=True, exist_ok=True)
    return d


def local_path(key: str) -> Path:
    key = key.replace("\\", "/").lstrip("/")
    p = (data_dir() / key).resolve()
    if data_dir().resolve() not in p.parents and p != data_dir().resolve():
        raise ValueError("key escapes data dir")
    return p


def _is_s3(key: str) -> bool:
    return get_settings().STORAGE_MODE == "s3" and not key.startswith(LOCAL_ONLY_PREFIXES)


@lru_cache
def _s3():
    import boto3

    return boto3.client("s3", region_name=get_settings().AWS_REGION)


_CT = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".mp4": "video/mp4", ".mp3": "audio/mpeg", ".png": "image/png",
       ".pdf": "application/pdf", ".json": "application/json"}


def put(src: str | os.PathLike, key: str, delete_src: bool = False) -> str:
    """Store a local file under `key`. Returns the key."""
    src = Path(src)
    if _is_s3(key):
        ct = _CT.get(src.suffix.lower(), "application/octet-stream")
        _s3().upload_file(str(src), get_settings().S3_BUCKET, key, ExtraArgs={"ContentType": ct})
        # keep a local copy too (clip cache / thumbnails), small files only
        dst = local_path(key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.resolve() != dst.resolve():
            shutil.copyfile(src, dst)
        if delete_src and src.resolve() != dst.resolve():
            src.unlink(missing_ok=True)
        return key
    dst = local_path(key)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() != dst.resolve():
        if delete_src:
            os.replace(src, dst)
        else:
            tmp = dst.with_suffix(dst.suffix + ".tmp")
            shutil.copyfile(src, tmp)
            os.replace(tmp, dst)
    return key


def put_bytes(data: bytes, key: str) -> str:
    dst = local_path(key)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, dst)
    if _is_s3(key):
        put(dst, key)
    return key


def exists(key: str) -> bool:
    if local_path(key).exists():
        return True
    if _is_s3(key):
        try:
            _s3().head_object(Bucket=get_settings().S3_BUCKET, Key=key)
            return True
        except Exception:
            return False
    return False


def url(key: str | None, token: str | None = None) -> str | None:
    if not key:
        return None
    if _is_s3(key):
        return _s3().generate_presigned_url(
            "get_object", Params={"Bucket": get_settings().S3_BUCKET, "Key": key}, ExpiresIn=3600
        )
    base = get_settings().API_BASE_URL.rstrip("/")
    u = f"{base}/media/{key}"
    return f"{u}?token={token}" if token else u


def delete(key: str) -> None:
    try:
        local_path(key).unlink(missing_ok=True)
    except Exception:
        pass
    if _is_s3(key):
        try:
            _s3().delete_object(Bucket=get_settings().S3_BUCKET, Key=key)
        except Exception as e:
            log.warning("s3 delete %s failed: %s", key, e)
